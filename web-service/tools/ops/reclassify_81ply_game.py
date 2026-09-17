"""Backed-up, explicitly authorized one-game historical chat reclassification.

Default is read-only planning. Apply requires the exact inspected state hash,
the reviewed Linux host, an idle Arcturus gate and an atomic compare-and-swap.
No native thread, other game, clock, replay artifact or service is rewritten.
Only aggregate counts/hashes leave this script; original text stays private.
"""
import argparse
from contextlib import closing, contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
import time


APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP))
from astra_web.chat_export import transcript_rtf
from game_note_reclassification import plan

GAME_ID = 'ba3c481cd28412092728c5e00036c3c3'
THREAD_ID = '01a09e71-95a1-7560-a037-19e44e41c564'
DATA = Path('/home/or-chess/.local/share/or-chess')
DB = DATA / 'astra.sqlite3'
BACKUPS = Path('/home/or-chess/game-note-backups')


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(value):
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


@contextmanager
def game_user():
    """SQLite must create/checkpoint sidecars under the service identity."""
    import pwd
    account = pwd.getpwnam('or-chess')
    uid, gid = os.geteuid(), os.getegid()
    require(uid in (0, account.pw_uid), 'Use root or the service account on the reviewed host.')
    if uid == 0:
        os.setegid(account.pw_gid)
        os.seteuid(account.pw_uid)
    try:
        yield account
    finally:
        if uid == 0:
            os.seteuid(uid)
            os.setegid(gid)


@contextmanager
def game_db(path=DB, *, read_only=False):
    with game_user():
        target = path.as_uri() + '?mode=ro' if read_only else path
        with closing(sqlite3.connect(target, uri=read_only, timeout=15)) as db:
            with db:
                yield db


def read_row(db):
    row = db.execute('SELECT user_id,updated,state FROM games WHERE id=?', (GAME_ID,)).fetchone()
    require(row is not None, 'Target game not found.')
    state = json.loads(row[2])
    require(state['id'] == GAME_ID and state['user_id'] == row[0]
            and state['thread_id'] == THREAD_ID and state['status'] == 'finished'
            and len(state['moves']) == 81 and state['result'] == '1-0'
            and state['termination'] == 'checkmate' and state['worker']['state'] == 'idle'
            and state['player_persona']['name'] == 'arcturus',
            'The exact authorized finished game must be idle and unchanged.')
    return tuple(row), state


def rollout_path():
    folder = DATA / 'players' / GAME_ID / 'codex-home' / 'sessions'
    paths = list(folder.rglob('*.jsonl'))
    require(len(paths) == 1, 'Expected one native game rollout; inspect changed layout.')
    path = paths[0]
    require(not path.is_symlink() and path.resolve().is_relative_to(DATA)
            and THREAD_ID in path.name, 'Unexpected native game rollout path.')
    return path


def rows(path):
    with path.open(encoding='utf-8') as stream:
        first = json.loads(next(stream))
        require(first.get('type') == 'session_meta'
                and first.get('payload', {}).get('id') == THREAD_ID,
                'Native rollout belongs to another thread.')
        yield first
        for line in stream:
            # The planner selects ordinary assistant text and accepted comment
            # calls only; hidden reasoning never enters the resulting record.
            yield json.loads(line)


def prepare():
    with game_db(read_only=True) as db:
        original, state = read_row(db)
    source = rollout_path()
    source_sha = digest(source.read_bytes())
    revised, summary = plan(state, rows(source))
    require(digest(source.read_bytes()) == source_sha, 'Native history changed during planning.')
    allowed = {'messages', 'assistant_notes', 'version'}
    require({k:v for k,v in state.items() if k not in allowed}
            == {k:v for k,v in revised.items() if k not in allowed},
            'Planner changed an unrelated game field.')
    require(revised['version'] == state['version'] + 1, 'Version must increase exactly once.')
    report = dict(game_id=GAME_ID, state_sha256=digest(original[2]),
        source_sha256=source_sha, source_bytes=source.stat().st_size,
        original_messages=len(state['messages']), public_messages=len(revised['messages']),
        old_notes=len(state.get('assistant_notes', [])), internal_notes=len(revised['assistant_notes']),
        old_version=state['version'], new_version=revised['version'], plan=summary)
    return original, revised, source, report


def primitives():
    path = Path(__file__).parent / 'history/2026-09-14/deploy_parallel_workers.py'
    spec = importlib.util.spec_from_file_location('reviewed_ops_primitives', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def table_hashes(db, except_tables):
    result = {}
    for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        if name in except_tables:
            continue
        quoted = '"' + name.replace('"', '""') + '"'
        result[name] = digest('\n'.join(sorted(repr(tuple(r)) for r in db.execute('SELECT * FROM ' + quoted))))
    return result


def apply(expected_sha, expected_source_sha):
    require(sys.platform == 'linux' and os.geteuid() == 0 and not sys.flags.optimize,
            'Apply requires the reviewed Linux host, root and enabled assertions.')
    os.umask(0o077)
    base = primitives()
    from arcturus_maintenance_gate import arcturus_maintenance_gate
    base.idle()
    initial_pids = base.pids()
    require(all(int(pid) > 0 for pid in initial_pids.values()), 'Required services must be running.')
    with arcturus_maintenance_gate() as gate:
        base.idle()
        original, revised, source, report = prepare()
        require(report['state_sha256'] == expected_sha, 'Game changed since the reviewed dry run.')
        require(report['source_sha256'] == expected_source_sha, 'Native history changed since the reviewed dry run.')
        stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
        backup = BACKUPS / ('single-game-notes-' + stamp)
        with game_user() as account:
            BACKUPS.mkdir(mode=0o700, exist_ok=True)
            require(not BACKUPS.is_symlink() and BACKUPS.stat().st_uid == account.pw_uid
                    and not BACKUPS.stat().st_mode & 0o077, 'Backup parent must be service-owned and private.')
            backup.mkdir(mode=0o700)
        with game_db(read_only=True) as current, game_db(backup / 'before.sqlite3') as copy:
            current.backup(copy)
        (backup / 'original-game.json').write_text(original[2], encoding='utf-8')
        (backup / 'plan.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        base.idle()
        require(base.pids() == initial_pids, 'Service changed during planning.')
        require(digest(source.read_bytes()) == report['source_sha256'], 'Native history changed before apply.')
        encoded = json.dumps(revised)
        with game_db() as db:
            db.execute('BEGIN IMMEDIATE')
            current, _ = read_row(db)
            require(current == original, 'Game changed; refuse stale migration.')
            with game_db(backup / 'before.sqlite3', read_only=True) as saved:
                require(read_row(saved)[0] == original, 'Backup does not match the exact original row.')
            other_games = db.execute('SELECT * FROM games WHERE id<>? ORDER BY id', (GAME_ID,)).fetchall()
            other_tables = table_hashes(db, {'games', 'events'})
            old_events = db.execute('SELECT * FROM events ORDER BY id').fetchall()
            updated = db.execute('UPDATE games SET state=? WHERE id=? AND state=? AND user_id=? AND updated=?',
                                 (encoded, GAME_ID, original[2], original[0], original[1]))
            require(updated.rowcount == 1, 'Compare-and-swap did not update exactly one game.')
            audit = db.execute('INSERT INTO events(game_id,at,kind,data) VALUES(?,?,?,?)',
                (GAME_ID, time.time(), 'operator_reclassified_assistant_notes', json.dumps({
                    **report, 'after_state_sha256': digest(encoded), 'backup': str(backup),
                    'authorization': 'Owner requested this single finished game as a retrospective test case.'})))
            require(db.execute('SELECT user_id,updated,state FROM games WHERE id=?', (GAME_ID,)).fetchone()
                    == (original[0], original[1], encoded), 'Unexpected target row change.')
            require(db.execute('SELECT * FROM games WHERE id<>? ORDER BY id', (GAME_ID,)).fetchall()
                    == other_games, 'Another game changed within the transaction.')
            require(table_hashes(db, {'games', 'events'}) == other_tables, 'An unrelated table changed.')
            require(db.execute('SELECT * FROM events WHERE id<>? ORDER BY id', (audit.lastrowid,)).fetchall()
                    == old_events, 'Historical audit events changed.')
            # Generate both exports before commit; format failures roll back.
            public_rtf = transcript_rtf(revised)
            notes_rtf = transcript_rtf(revised, include_notes=True)
        require(digest(source.read_bytes()) == report['source_sha256'], 'Native history changed after apply.')
        with game_db(read_only=True) as db:
            require(read_row(db)[0] == (original[0], original[1], encoded), 'Post-commit row verification failed.')
        require(base.pids() == initial_pids and base.health(), 'Service health or identity changed.')
        report.update(success=True, backup=str(backup), applied_at=stamp,
            after_state_sha256=digest(encoded), other_games_unchanged=len(other_games),
            unrelated_tables_unchanged=True, old_events_unchanged=True, native_history_unchanged=True,
            service_pids_unchanged=True, public_rtf_bytes=len(public_rtf), notes_rtf_bytes=len(notes_rtf),
            public_rtf_sha256=digest(public_rtf), notes_rtf_sha256=digest(notes_rtf))
        (backup / 'result.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    report['gate_restored'] = gate['restored']
    require(report['gate_restored'], 'Maintenance gate restoration needs inspection.')
    (backup / 'result.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--expected-state-sha256')
    parser.add_argument('--expected-source-sha256')
    args = parser.parse_args()
    if args.apply and any(not value or len(value) != 64 for value in (
            args.expected_state_sha256, args.expected_source_sha256)):
        parser.error('Apply requires the exact dry-run state and source SHA-256 values.')
    result = apply(args.expected_state_sha256, args.expected_source_sha256) if args.apply else prepare()[3]
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
