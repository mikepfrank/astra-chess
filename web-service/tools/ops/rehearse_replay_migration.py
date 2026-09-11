"""Rehearse replay migration on a new private copy; never restart a service."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import sys


APP_ROOT = Path(__file__).resolve().parents[2]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))
from tools.ops.report_games import inventory, read_database, table_names


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':')).encode()).hexdigest()


def _hash_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _rows(db, table):
    quoted = '"' + table.replace('"', '""') + '"'
    rows = [dict(row) for row in db.execute('SELECT * FROM ' + quoted)]
    return sorted(rows, key=lambda row: json.dumps(row, sort_keys=True))


def _protected(db):
    tables = table_names(db)
    # Hash every non-replay table, including identity tables, without printing
    # their contents. Migration has no reason to modify any of these records.
    return {table: _digest(_rows(db, table)) for table in sorted(tables)
            if not table.startswith('replay_') and not table.startswith('sqlite_')}


def _references(db):
    tables = table_names(db)
    downloads, shared = {}, {}
    for table in ('replay_archives', 'replay_versions'):
        if table in tables:
            for row in db.execute("SELECT * FROM " + table + " WHERE state='ready'"):
                key = (row['game_id'], bool(row['include_commentary']))
                path = Path('replay-archives') / row['game_id']
                if table == 'replay_versions':
                    path /= 'chat' if row['include_commentary'] else 'moves'
                path /= row['archive_id'] + '.html'
                downloads[key] = {'archive_id': row['archive_id'], 'path': path}
    for table, listed in (('replay_unlisted', False), ('replay_publications', True), ('replay_variant_shares', None)):
        if table in tables:
            for row in db.execute('SELECT * FROM ' + table):
                key = (row['game_id'], bool(row['include_commentary']))
                shared[key] = {'archive_id': row['archive_id'], 'token': row['token'],
                               'listed': bool(row['listed']) if listed is None else listed,
                               'path': Path('public-replays') / (row['token'] + '.html')}
    return downloads, shared


def _replay_files(source):
    files = {}
    for name in ('replay-archives', 'public-replays'):
        folder = source / name
        if folder.is_symlink() or getattr(folder, 'is_junction', lambda: False)():
            raise ValueError('Replay folders must not be symbolic links.')
        if not folder.exists():
            continue
        for path in folder.rglob('*'):
            if (path.is_symlink() or getattr(path, 'is_junction', lambda: False)()
                    or not path.resolve().is_relative_to(source)):
                raise ValueError('Replay copies must not follow symbolic links or leave the source directory.')
            if path.is_file() and path.suffix == '.html':
                files[path.relative_to(source)] = _hash_file(path)
    return files


def rehearse(source, destination):
    source = Path(source).expanduser().resolve(strict=True)
    requested = Path(destination).expanduser()
    if requested.exists() or requested.is_symlink():
        raise ValueError('The rehearsal destination must be a new directory; existing directories are never reused or deleted.')
    destination = requested.parent.resolve(strict=True) / requested.name
    if destination == source or destination.is_relative_to(source) or source.is_relative_to(destination):
        raise ValueError('Use a new private destination outside the live data directory and its ancestors.')
    if (source / 'astra.sqlite3').is_symlink():
        raise ValueError('The source database must not be a symbolic link.')
    # Read all metadata from one transaction, and keep it open during backup.
    with read_database(source) as db:
        initial = inventory(db)
        if not initial['activity']['idle_snapshot']:
            raise ValueError('Rehearse when responses, replay builds, and token reservations are idle.')
        protected_before = _protected(db)
        source_before = {table: _digest(_rows(db, table)) for table in sorted(table_names(db)) if not table.startswith('sqlite_')}
        downloads, shares = _references(db)
        files_before = _replay_files(source)
        for item in list(downloads.values()) + list(shares.values()):
            path = item['path']
            if path not in files_before:
                raise ValueError('A referenced replay HTML file is missing from the source copy inventory.')
            item['sha256'] = files_before[path]
        destination.mkdir(mode=0o700)
        # A full SQLite backup includes private identities/messages. Its private
        # directory is retained for inspection, even if a later assertion fails.
        with closing(sqlite3.connect(destination / 'astra.sqlite3')) as copied:
            db.backup(copied)
        (destination / 'astra.sqlite3').chmod(0o600)
        for relative, expected in files_before.items():
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / relative, target)
            if _hash_file(target) != expected:
                raise ValueError('Replay files changed while copying; discard this rehearsal and retry during maintenance.')
    with read_database(source) as db:
        source_after = {table: _digest(_rows(db, table)) for table in sorted(table_names(db)) if not table.startswith('sqlite_')}
        if source_after != source_before:
            raise ValueError('Source records changed during the copy. The private copy is retained; retry during maintenance.')
    if _replay_files(source) != files_before:
        raise ValueError('Source replay files changed during the copy. Retry during maintenance.')

    # Import only after the safe private copy is complete. Instantiating these
    # classes may migrate/write the COPY, never the operator's source directory.
    from astra_web.config import Config
    from astra_web.store import Store
    from astra_web.replay_library import ReplayLibrary
    config = Config(data_dir=destination, origin='http://testserver', player_mode='disabled', secure_cookies=False)
    store = Store(config)
    library = ReplayLibrary(config, store)
    library.recover()
    for (game_id, include), item in downloads.items():
        library.download(game_id, item['archive_id'])
        path = destination / 'replay-archives' / game_id / ('chat' if include else 'moves') / (item['archive_id'] + '.html')
        if _hash_file(path) != item['sha256']:
            raise ValueError('A saved private replay changed during migration.')
    for (game_id, include), item in shares.items():
        status = library.status(game_id, 'chat' if include else 'moves')
        if (status['shared_archive_id'] != item['archive_id'] or status['share_url'] != f"/games/{item['token']}.html"
                or status['listed'] != item['listed']):
            raise ValueError('A shared replay identity or visibility changed during migration.')
        library.public_page(item['token'])
        if _hash_file(destination / item['path']) != item['sha256']:
            raise ValueError('A shared replay changed during migration.')
        if (game_id, include) not in downloads:
            library.download(game_id, item['archive_id'])
            path = destination / 'replay-archives' / game_id / ('chat' if include else 'moves') / (item['archive_id'] + '.html')
            if _hash_file(path) != item['sha256']:
                raise ValueError('A shared-only replay did not retain its private download.')
    with store.connection() as db:
        replay_after_first = {table: _digest(_rows(db, table)) for table in sorted(table_names(db)) if table.startswith('replay_')}
    files_after_first = _replay_files(destination)
    library.recover()
    with store.connection() as db:
        replay_after_second = {table: _digest(_rows(db, table)) for table in sorted(table_names(db)) if table.startswith('replay_')}
        if replay_after_second != replay_after_first or _replay_files(destination) != files_after_first:
            raise ValueError('Replay metadata or HTML changed during the second recovery; migration is not idempotent.')
        if _protected(db) != protected_before:
            raise ValueError('Non-replay database records changed during migration.')
        variants = db.execute('SELECT COUNT(*) FROM replay_versions').fetchone()[0]
    result = dict(rehearsal_passed=True, source_writes=False, games=initial['summary']['total_games'],
                  previous_downloads=len(downloads), previous_shared_links=len(shares), saved_variants=variants,
                  protected_records_preserved=True, replay_bytes_and_visibility_preserved=True,
                  idempotent=True, completed_at=datetime.now(timezone.utc).isoformat(timespec='seconds'))
    output = destination / 'result.json'
    output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    output.chmod(0o600)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', required=True, type=Path, help='Live or backup source; opened read-only')
    parser.add_argument('--copy-dir', required=True, type=Path, help='New private directory outside the source; parent must already exist')
    args = parser.parse_args(argv)
    try:
        result = rehearse(args.data_dir, args.copy_dir)
    except (ValueError, OSError, sqlite3.Error, RuntimeError) as error:
        parser.exit(1, 'Replay rehearsal stopped: ' + str(error) + '\n')
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
