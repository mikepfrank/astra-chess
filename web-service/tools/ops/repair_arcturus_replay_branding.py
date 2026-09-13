"""Repair one experimental game's existing replay snapshots, without recapture.

Default: read-only dry run, reporting a deterministic plan hash. Apply requires
that hash, a new private backup directory outside the data directory, and a
stopped or-chess.service. CLI apply is restricted to the installed or-chess data
directory. No game, transcript, engine, clock, token budget or shared-link state
is rewritten. Legacy /replay/ links are counted and left to a separate review.

    python tools/ops/repair_arcturus_replay_branding.py --data-dir DATA --game ID
    sudo python tools/ops/repair_arcturus_replay_branding.py --data-dir DATA \\
        --game ID --apply --expect-plan HASH --backup-dir NEW_PRIVATE_DIRECTORY

The backup includes the coherent database and exact affected HTML. Application
code must already include the persona-aware replay/index fix before restart.
The index is a generated projection and is rebuilt by the application. Keep the
service stopped until successful completion or explicit recovery from backup.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from copy import deepcopy
import hashlib
from html import escape
import json
import os
from pathlib import Path
import re
import signal
import sqlite3
import stat
import subprocess
import sys


APP_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP_ROOT))
from astra_web.player_profiles import saved_player_name


DATA = Path('/home/or-chess/.local/share/or-chess')
MARKER = '<script id="replay-data" type="application/json">'
MAX_HTML_BYTES = 32_000_000
MODEL = 'z-ai/glm-5.3-flash:nitro'
NAME = 'Arcturus'
TOKEN = re.compile(r'[0-9a-f]{32}')
CODEX_ALIAS_TARGET = '/home/or-chess/.local/share/or-chess-runtime/codex/bin/codex'
CODEX_ALIAS_NAMES = {'apply_patch', 'applypatch', 'codex-linux-sandbox', 'codex-execve-wrapper'}


def canonical(value):
    def encode(item):
        if isinstance(item, bytes):
            return {'blob_hex': item.hex()}
        raise TypeError('Unsupported value in repair evidence.')
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                      allow_nan=False, default=encode)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def unique_object(pairs):
    output = {}
    for key, value in pairs:
        if key in output:
            raise ValueError('Duplicate JSON keys require manual review.')
        output[key] = value
    return output


def decode_json(raw):
    def invalid_constant(value):
        raise ValueError('Nonfinite JSON values require manual review.')
    return json.loads(raw, object_pairs_hook=unique_object, parse_constant=invalid_constant)


def page_data(raw):
    if len(raw) > MAX_HTML_BYTES:
        raise ValueError('Replay exceeds the existing HTML size limit.')
    page = raw.decode('utf-8')
    if page.count(MARKER) != 1:
        raise ValueError('Expected one recognized replay JSON element.')
    start = page.index(MARKER) + len(MARKER)
    end = page.index('</script>', start)
    return page, start, end, decode_json(page[start:end])


def pgn_line(key, value):
    if not isinstance(value, str):
        raise ValueError('Unexpected PGN header value.')
    value = value.replace('\\', '\\\\').replace('"', '\\"').replace('\n', ' ').replace('\r', ' ')
    return '[' + key + ' "' + value + '"]'


def repair_pgn(data, side):
    pgn = data['pgn']
    header_text, separator, moves = pgn.partition('\n\n')
    if not separator or '\r' in pgn:
        raise ValueError('Unexpected archived PGN structure.')
    headers = data['headers']
    expected_lines = [pgn_line(key, value) for key, value in headers.items()]
    lines = header_text.split('\n')
    if len(lines) != len(expected_lines) or set(lines) != set(expected_lines):
        raise ValueError('Embedded PGN and captured headers disagree.')
    updates = {side.title(): NAME, 'Event': NAME + ' Chess Public Beta', 'Site': NAME + ' Chess'}
    for key, value in updates.items():
        old = headers.get(key)
        allowed = {'Astra', NAME} if key == side.title() else {
            'Astra Chess Public Beta', value} if key == 'Event' else {'Astra Chess', value}
        if old not in allowed:
            raise ValueError('Unexpected original PGN branding requires manual review.')
        lines[lines.index(pgn_line(key, old))] = pgn_line(key, value)
        headers[key] = value
    for old_key, new_key, value in (('AstraModel', 'Model', MODEL),
                                    ('AstraReasoning', 'Reasoning', 'high')):
        if (old_key in headers) == (new_key in headers):
            raise ValueError('Expected exactly one captured model/reasoning header.')
        actual = old_key if old_key in headers else new_key
        if headers[actual] != value:
            raise ValueError('Captured model or reasoning differs from Arcturus.')
        lines[lines.index(pgn_line(actual, value))] = pgn_line(new_key, value)
        if actual != new_key:
            del headers[actual]
        headers[new_key] = value
    data['pgn'] = '\n'.join(lines) + separator + moves


def immutable_snapshot(data):
    """Hash all captured replay data except the explicit branding sinks."""
    value = deepcopy(data)
    side = value['playerSide']
    value.pop('playerName', None)
    value['archive'].pop('playerName', None)
    value['displayNames'][side] = '<player>'
    for message in value['messages']:
        if message['author'] == 'astra':
            message['name'] = '<player>'
    value['evaluations']['description'] = value['evaluations']['description'].replace(
        "Saved evidence for Astra's actual moves.", 'Saved evidence for <player> actual moves.', 1).replace(
        "Saved evidence for Arcturus's actual moves.", 'Saved evidence for <player> actual moves.', 1)
    for key in (side.title(), 'Event', 'Site'):
        value['headers'][key] = '<branding>'
    for old, new in (('AstraModel', 'Model'), ('AstraReasoning', 'Reasoning')):
        if old in value['headers']:
            value['headers'][new] = value['headers'].pop(old)
    value['pgn'] = value['pgn'].partition('\n\n')[2]
    return digest(canonical(value).encode())


def replace_sink(page, old, new):
    if old == new:
        return page
    if page.count(old) == 1 and page.count(new) == 0:
        return page.replace(old, new, 1)
    if page.count(old) == 0 and page.count(new) == 1:
        return page
    raise ValueError('Unexpected replay HTML branding sink requires manual review.')


def repair_page(raw, *, archive_id, include_commentary, side):
    page, start, end, data = page_data(raw)
    before = immutable_snapshot(data)
    archive = data['archive']
    if (archive.get('gameId') != archive_id or archive.get('model') != MODEL
            or archive.get('reasoning') != 'high' or archive.get('source') != 'hosted_service'
            or data['playerSide'] != side or side not in ('white', 'black')
            or archive.get('messageCount') != len(data['messages'])
            or not include_commentary and data['messages']):
        raise ValueError('Captured replay identity or chat choice does not match its stored reference.')
    if not data['frames'] or data['headers'].get('Round') != 'hosted-' + archive_id:
        raise ValueError('Captured replay frames or archive round are invalid.')
    if data['displayNames'][side] not in ('Astra', NAME):
        raise ValueError('Unexpected captured player display name.')
    if any(value is not None and value != NAME for value in (data.get('playerName'), archive.get('playerName'))):
        raise ValueError('Existing explicit replay player identity disagrees.')
    opponent = data['displayNames']['white' if side == 'black' else 'black']
    old_title = 'Astra (High) vs. ' + opponent
    new_title = NAME + ' (High) vs. ' + opponent
    data['displayNames'][side] = NAME
    data['playerName'] = archive['playerName'] = NAME
    for message in data['messages']:
        if message['author'] == 'astra':
            if message.get('name') not in ('Astra', NAME):
                raise ValueError('Unexpected captured assistant message display name.')
            message['name'] = NAME
    description = data['evaluations']['description']
    prefix, replacement = "Saved evidence for Astra's actual moves.", "Saved evidence for Arcturus's actual moves."
    if not description.startswith((prefix, replacement)):
        raise ValueError('Unexpected recorded evaluation description.')
    data['evaluations']['description'] = description.replace(prefix, replacement, 1)
    repair_pgn(data, side)
    if immutable_snapshot(data) != before:
        raise ValueError('Repair would alter captured replay content.')
    page = page[:start] + canonical(data).replace('<', '\\u003c') + page[end:]
    page = replace_sink(page, '<title>' + escape(old_title) + ' — Game replay</title>',
                        '<title>' + escape(new_title) + ' — Game replay</title>')
    page = replace_sink(page, '<h1>' + escape(old_title) + '</h1>', '<h1>' + escape(new_title) + '</h1>')
    page = replace_sink(page, '<p class="eyebrow">ASTRA CHESS · HOSTED GAME REPLAY</p>',
                        '<p class="eyebrow">CHESS · HOSTED GAME REPLAY</p>')
    result = page.encode('utf-8')
    if len(result) > MAX_HTML_BYTES:
        raise ValueError('Repaired replay exceeds the existing HTML size limit.')
    return result, before


def checked_file(root, relative):
    root = Path(root).resolve(strict=True)
    path = root / relative
    if not path.is_file() or any(part.is_symlink() or getattr(part, 'is_junction', lambda: False)()
                                 for part in (path, *path.parents) if part != root.parent):
        raise ValueError('Repair files must be regular files without symbolic-link ancestors.')
    if not path.resolve().is_relative_to(root):
        raise ValueError('Repair path escaped the selected data directory.')
    return path


def file_digest(path):
    result = hashlib.sha256()
    with path.open('rb') as source:
        while chunk := source.read(1024 * 1024):
            result.update(chunk)
    return result.hexdigest()


def codex_alias_evidence(relative, target):
    """Recognize only the installed Codex arg0 aliases; never resolve a target."""
    parts = Path(relative).parts
    if (len(parts) != 7 or parts[0] != 'players' or not TOKEN.fullmatch(parts[1])
            or parts[2:5] != ('codex-home', 'tmp', 'arg0')
            or not re.fullmatch(r'codex-arg0[A-Za-z0-9]{6,32}', parts[5])
            or parts[6] not in CODEX_ALIAS_NAMES or target != CODEX_ALIAS_TARGET):
        raise ValueError('Protected evidence tree contains an unrecognized symbolic link.')
    return {'kind': 'codex_arg0_alias', 'target_text': target}


def protected_files(root):
    result = {}
    for relative in ('games', 'players'):
        folder = root / relative
        if folder.is_symlink() or getattr(folder, 'is_junction', lambda: False)():
            raise ValueError('Protected evidence roots must not be symbolic links.')
        if folder.exists():
            for path in sorted(folder.rglob('*')):
                if path.is_symlink():
                    relative_path = path.relative_to(root)
                    result[str(relative_path)] = codex_alias_evidence(relative_path, os.readlink(path))
                    continue
                if getattr(path, 'is_junction', lambda: False)():
                    raise ValueError('Protected evidence tree contains an unrecognized junction.')
                if path.is_file():
                    result[str(path.relative_to(root))] = file_digest(checked_file(root, path.relative_to(root)))
    budget = root / 'openrouter-budget.json'
    if budget.is_symlink() or getattr(budget, 'is_junction', lambda: False)():
        raise ValueError('The protected budget must not be a symbolic link.')
    if budget.exists():
        result[budget.name] = file_digest(checked_file(root, budget.name))
    return result


def database_rows(db):
    result = {}
    tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    for table in sorted(tables):
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', table):
            raise ValueError('Unexpected database table name.')
        rows = [dict(row) for row in db.execute('SELECT * FROM "' + table + '"')]
        result[table] = sorted(rows, key=canonical)
    return result


def connect(root, *, writable=False):
    path = checked_file(root, 'astra.sqlite3')
    db = sqlite3.connect(path.as_uri() + ('?mode=rw' if writable else '?mode=ro'), uri=True, timeout=10)
    db.row_factory = sqlite3.Row
    if not writable:
        db.execute('PRAGMA query_only=ON')
    return db


def make_plan(data_dir, game_id):
    root = Path(data_dir).resolve(strict=True)
    if root.is_relative_to(Path('/home/astra')) or not TOKEN.fullmatch(game_id):
        raise ValueError('Select one explicit experimental game and its isolated data directory.')
    with closing(connect(root)) as db:
        db.execute('BEGIN')
        rows = database_rows(db)
    state_row = next((row for row in rows['games'] if row['id'] == game_id), None)
    if state_row is None:
        raise ValueError('The selected game does not exist.')
    state = decode_json(state_row['state'])
    if (state.get('id') != game_id or state.get('model') != MODEL or state.get('reasoning') != 'high'
            or state.get('status') != 'finished' or saved_player_name(state) != NAME
            or state.get('player_persona', {}).get('name') != 'arcturus'):
        raise ValueError('This tool repairs only finished games with saved Arcturus identity.')
    if any(decode_json(row['state']).get('active_started') is not None
           or decode_json(row['state']).get('compaction_pause')
           or decode_json(row['state']).get('worker', {}).get('state') in ('thinking', 'queued', 'compacting', 'calculating')
           for row in rows['games']):
        raise ValueError('Wait for all experimental responses to become idle.')
    if any(row['reserved'] for row in rows.get('budget', [])) or any(
            row['state'] == 'building' for row in rows.get('replay_variant_jobs', [])):
        raise ValueError('Wait for replay construction and resource reservations to become idle.')
    if any(rows.get(table) for table in ('replay_archives', 'replay_publications', 'replay_unlisted')):
        raise ValueError('Retired replay tables must already have completed variant migration.')
    references = {}
    metadata = []
    for row in rows.get('replay_versions', []):
        if row['game_id'] != game_id:
            continue
        if row['state'] != 'ready':
            raise ValueError('Selected private replay version is not ready.')
        if row['include_commentary'] not in (0, 1) or not TOKEN.fullmatch(row['archive_id']):
            raise ValueError('Invalid private replay reference.')
        relative = Path('replay-archives') / game_id / ('chat' if row['include_commentary'] else 'moves') / (row['archive_id'] + '.html')
        references[str(relative)] = (row['archive_id'], bool(row['include_commentary']))
    for row in rows.get('replay_variant_shares', []):
        if row['game_id'] != game_id:
            continue
        if (row['include_commentary'] not in (0, 1) or row['listed'] not in (0, 1)
                or not TOKEN.fullmatch(row['token']) or not TOKEN.fullmatch(row['archive_id'])):
            raise ValueError('Invalid published replay reference.')
        references[str(Path('public-replays') / (row['token'] + '.html'))] = (row['archive_id'], bool(row['include_commentary']))
        original = decode_json(row['metadata'])
        if original.get('player_name') not in (None, NAME):
            raise ValueError('Publication has an unexpected explicit player name.')
        repaired = {**original, 'player_name': NAME}
        if repaired != original:
            metadata.append({'game_id': game_id, 'include_commentary': row['include_commentary'],
                             'before': row['metadata'], 'after': canonical(repaired)})
    changes = []
    for relative, (archive_id, include) in sorted(references.items()):
        if not TOKEN.fullmatch(archive_id):
            raise ValueError('Invalid saved archive identifier.')
        path = checked_file(root, relative)
        raw = path.read_bytes()
        repaired, snapshot_hash = repair_page(raw, archive_id=archive_id, include_commentary=include, side=state['astra_side'])
        if repaired != raw:
            changes.append({'path': relative, 'before_sha256': digest(raw), 'after_sha256': digest(repaired),
                            'snapshot_sha256': snapshot_hash, 'archive_id': archive_id, 'include_commentary': include})
    evidence = protected_files(root)
    plan = {'schema_version': 1, 'game_id': game_id, 'data_dir': str(root), 'files': changes,
            'metadata': metadata, 'database_sha256': digest(canonical(rows).encode()),
            'protected_files_sha256': digest(canonical(evidence).encode()), 'protected_file_count': len(evidence),
            'legacy_shares_skipped': sum(row.get('game_id') == game_id for row in rows.get('shares', []))}
    plan['plan_sha256'] = digest(canonical(plan).encode())
    return plan


def private_write(path, raw):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with path.open('xb') as output:
        os.chmod(path, 0o600)
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())


def rewrite_file(path, raw):
    temporary = path.with_name('.' + path.name + '.branding-repair.tmp')
    original_stat = path.stat()
    try:
        private_write(temporary, raw)
        os.chmod(temporary, stat.S_IMODE(original_stat.st_mode))
        if hasattr(os, 'chown'):
            os.chown(temporary, original_stat.st_uid, original_stat.st_gid)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def apply_plan(data_dir, game_id, expected_hash, backup_dir):
    plan = make_plan(data_dir, game_id)
    if plan['plan_sha256'] != expected_hash:
        raise ValueError('The current repair plan differs from the reviewed dry run.')
    root = Path(plan['data_dir'])
    backup = Path(backup_dir).absolute()
    if (backup.exists() or backup.is_symlink() or not backup.parent.is_dir()
            or backup.resolve().is_relative_to(root) or root.is_relative_to(backup.resolve())):
        raise ValueError('Use a new backup directory outside the live data directory and its ancestors.')
    backup.mkdir(mode=0o700)
    backup.chmod(0o700)
    private_write(backup / 'plan.json', (canonical(plan) + '\n').encode())
    with closing(connect(root)) as source, closing(sqlite3.connect(backup / 'astra.sqlite3')) as destination:
        source.backup(destination)
    (backup / 'astra.sqlite3').chmod(0o600)
    original_files, candidate_files = {}, {}
    for item in plan['files']:
        path = checked_file(root, item['path'])
        raw = path.read_bytes()
        if digest(raw) != item['before_sha256']:
            raise ValueError('Replay bytes changed before backup.')
        repaired, _ = repair_page(raw, archive_id=item['archive_id'], include_commentary=item['include_commentary'],
                                  side=page_data(raw)[3]['playerSide'])
        if digest(repaired) != item['after_sha256']:
            raise ValueError('The repaired candidate differs from the reviewed plan.')
        private_write(backup / 'files' / item['path'], raw)
        original_files[item['path']], candidate_files[item['path']] = raw, repaired
    if make_plan(root, game_id)['plan_sha256'] != expected_hash:
        raise ValueError('Data changed while creating the backup; no repair was applied.')
    written = []
    with closing(connect(root, writable=True)) as db:
        db.execute('BEGIN IMMEDIATE')
        before_rows = database_rows(db)
        if digest(canonical(before_rows).encode()) != plan['database_sha256']:
            raise ValueError('Database changed after the reviewed backup.')
        expected_rows = deepcopy(before_rows)
        try:
            for item in plan['metadata']:
                changed = db.execute('UPDATE replay_variant_shares SET metadata=? WHERE game_id=? AND include_commentary=? AND metadata=?',
                                     (item['after'], game_id, item['include_commentary'], item['before']))
                if changed.rowcount != 1:
                    raise ValueError('Publication metadata changed during repair.')
                for row in expected_rows['replay_variant_shares']:
                    if row['game_id'] == game_id and row['include_commentary'] == item['include_commentary']:
                        row['metadata'] = item['after']
            expected_rows['replay_variant_shares'] = sorted(expected_rows.get('replay_variant_shares', []), key=canonical)
            for item in plan['files']:
                path = checked_file(root, item['path'])
                if file_digest(path) != item['before_sha256']:
                    raise ValueError('A replay changed during repair.')
                rewrite_file(path, candidate_files[item['path']])
                written.append(item['path'])
            if database_rows(db) != expected_rows or digest(canonical(protected_files(root)).encode()) != plan['protected_files_sha256']:
                raise ValueError('Protected database, game evidence or budget content changed.')
            db.commit()
        except BaseException:
            db.rollback()
            for relative in reversed(written):
                path = checked_file(root, relative)
                if file_digest(path) != digest(candidate_files[relative]):
                    raise RuntimeError('Concurrent replay edit prevents rollback; retain stopped service and inspect backup.')
                rewrite_file(path, original_files[relative])
            raise
    if any(file_digest(checked_file(root, item['path'])) != item['after_sha256'] for item in plan['files']):
        raise RuntimeError('Post-commit file verification failed; retain stopped service and inspect backup.')
    report = {'applied': True, 'plan_sha256': expected_hash, 'html_files_changed': len(plan['files']),
              'publication_rows_changed': len(plan['metadata']), 'protected_records_preserved': True,
              'captured_snapshots_preserved': True, 'legacy_shares_skipped': plan['legacy_shares_skipped']}
    private_write(backup / 'result.json', (canonical(report) + '\n').encode())
    return report


def require_stopped_service(root):
    if sys.platform != 'linux' or root != DATA:
        raise ValueError('CLI apply is restricted to the installed isolated or-chess data directory.')
    result = subprocess.run(['systemctl', 'show', 'or-chess.service', '--property=ActiveState',
                             '--property=MainPID', '--property=ControlGroup'], capture_output=True, text=True, timeout=10, check=True)
    info = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    if info.get('ActiveState') != 'inactive' or info.get('MainPID') != '0':
        raise ValueError('Stop only or-chess.service before applying the repair.')
    group = info.get('ControlGroup')
    if group:
        path = Path('/sys/fs/cgroup') / group.lstrip('/')
        if path.exists() and any(item.read_text().strip() for item in path.rglob('cgroup.procs')):
            raise ValueError('Experimental service descendants are still running.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--game', required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--expect-plan')
    parser.add_argument('--backup-dir', type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.apply:
            if not args.backup_dir or not re.fullmatch(r'[0-9a-f]{64}', args.expect_plan or ''):
                raise ValueError('Apply requires the reviewed plan hash and a new private backup directory.')
            require_stopped_service(args.data_dir.resolve(strict=True))
            if hasattr(signal, 'SIGTERM'):
                def interrupted(*unused):
                    raise InterruptedError('Repair interrupted; inspect backup before restarting.')
                signal.signal(signal.SIGTERM, interrupted)
            report = apply_plan(args.data_dir, args.game, args.expect_plan, args.backup_dir)
        else:
            plan = make_plan(args.data_dir, args.game)
            report = {'dry_run': True, 'plan_sha256': plan['plan_sha256'], 'html_files_to_change': len(plan['files']),
                      'publication_rows_to_change': len(plan['metadata']), 'protected_file_count': plan['protected_file_count'],
                      'legacy_shares_skipped': plan['legacy_shares_skipped'], 'source_writes': False}
        print(json.dumps(report, indent=2))
        return 0
    except (ValueError, OSError, RuntimeError, sqlite3.Error, KeyError, TypeError) as error:
        print(json.dumps({'repair_stopped': True, 'error_type': type(error).__name__,
                          'message': str(error) if type(error) in (ValueError, RuntimeError) else 'Inspect the private backup before restarting.'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
