#!/usr/bin/env python3
"""Read-only verification of a completed private host backup, without extraction.

Run beside backup_host_security_20261117.py while all four applications remain stopped.
The producer already hashed and fsynced each archive. This check verifies sizes,
ten selected archived files against stopped live files, and Docker's image
configuration digest; it deliberately does not re-hash the complete archives.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import stat
import tarfile

BASE = Path('/var/backups/chess-security')
SELECTED = (
    '/home/astra/.local/share/astra-chess/astra.sqlite3',
    '/home/or-chess/.local/share/or-chess/astra.sqlite3',
    '/home/gpt-2/.local/share/gpt2-codex/chats.sqlite3',
    '/var/lib/astra-chess-ops/maintenance.json',
    '/var/lib/arcturus-chess-ops/maintenance.json',
    '/var/lib/gpt2-maintenance-ops/maintenance.json',
    '/home/astra/.config/astra-chess/Caddyfile',
    '/home/gpt-2/.venvs/gpt2-public-security-20261116/pyvenv.cfg',
    '/home/gpt-2/.venvs/gpt2-public-security-20261116/lib/python3.12/site-packages/certifi/cacert.pem',
    '/home/gpt-2/.venvs/gpt2-public-pre-security-20261117/pyvenv.cfg',
)
ARTIFACTS = {'applications.tar', 'gpt2-codex-image.tar', 'rpm-inventory.txt',
             'installed-units.txt', 'iptables.txt'}
BACKUP_HELPER_SHA256 = '41baf453ead6b75f41d1af0884f8b79918b4eb794c61313f56867a455ce5d7b8'


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def canonical_directory(value, base=BASE):
    path = Path(value)
    require(path.is_absolute() and path == path.resolve(strict=True),
            'Backup directory must be an exact resolved absolute path')
    require(path.parent == base and path != base, 'Backup directory must be directly under the backup root')
    require(not any(p.is_symlink() for p in (path, *path.parents)), 'Symlink in backup directory path')
    return path


def private_path(path, directory=False, owner=0):
    info = path.lstat()
    require((stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
            and info.st_uid == owner and stat.S_IMODE(info.st_mode) == (0o700 if directory else 0o600),
            'Backup ownership, permissions, or file type is unsafe')


def read_json(path, limit=1024 * 1024):
    require(path.stat().st_size <= limit, 'JSON metadata exceeds the size limit')
    return json.loads(path.read_bytes())


def check_manifest(directory, owner=0):
    private_path(directory, directory=True, owner=owner)
    names = set()
    for path in directory.iterdir():
        private_path(path, owner=owner)
        names.add(path.name)
    require(names == ARTIFACTS | {'manifest.json'}, 'Backup artifact inventory differs from expected files')
    manifest = read_json(directory / 'manifest.json')
    require(isinstance(manifest, dict) and manifest.get('complete') is True, 'Backup manifest is incomplete')
    records = manifest.get('files')
    require(isinstance(records, dict) and set(records) == ARTIFACTS, 'Manifest artifact inventory is invalid')
    for name, record in records.items():
        require(isinstance(record, dict) and type(record.get('bytes')) is int
                and record['bytes'] > 0 and (directory / name).stat().st_size == record['bytes'],
                'An artifact size does not match the manifest')
        digest = record.get('sha256', '')
        require(isinstance(digest, str) and len(digest) == 64
                and all(c in '0123456789abcdef' for c in digest), 'A recorded archive digest is invalid')
    return manifest


def member_name(member):
    name = member.name
    require(bool(name) and not PurePosixPath(name).is_absolute()
            and '..' not in PurePosixPath(name).parts and '\\' not in name,
            'Unsafe path in archive')
    return str(PurePosixPath(name))


def stream_digest(stream):
    result = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
        result.update(chunk)
    return result.hexdigest()


def compare_selected(archive, selected):
    """selected maps relative archive names to absolute live paths."""
    seen = set()
    with tarfile.open(archive, 'r:') as tar:
        for member in tar:
            name = member_name(member)
            if name not in selected:
                continue
            require(name not in seen and member.isfile(), 'A selected archived file is duplicated or not regular')
            seen.add(name)
            live = Path(selected[name])
            require(stat.S_ISREG(live.lstat().st_mode), 'A selected live file is not regular')
            require(member.size == live.stat().st_size, 'A selected archived file size differs from live')
            with tar.extractfile(member) as stored, live.open('rb') as current:
                require(stream_digest(stored) == stream_digest(current), 'A selected archived file differs from live')
    require(seen == set(selected), 'A selected file is missing from the archive')
    return len(seen)


def verify_image(archive, expected):
    require(isinstance(expected, dict) and isinstance(expected.get('tag'), str)
            and isinstance(expected.get('id'), str), 'Missing Docker identity in backup manifest')
    with tarfile.open(archive, 'r:') as tar:
        members = {}
        for member in tar:
            name = member_name(member)
            require(name not in members, 'Duplicate path in Docker archive')
            members[name] = member

        def small_file(name, limit):
            item = members.get(name)
            require(item is not None and item.isfile() and item.size <= limit,
                    'Missing or invalid Docker metadata member')
            with tar.extractfile(item) as stream:
                return stream.read(limit + 1)

        listing = json.loads(small_file('manifest.json', 1024 * 1024))
        require(isinstance(listing, list), 'Invalid Docker archive manifest')
        matches = [row for row in listing if isinstance(row, dict)
                   and isinstance(row.get('RepoTags'), list) and expected['tag'] in row['RepoTags']]
        require(len(matches) == 1, 'Expected Docker tag does not identify exactly one archived image')
        config = matches[0].get('Config')
        require(isinstance(config, str), 'Docker configuration path is invalid')
        config_bytes = small_file(config, 16 * 1024 * 1024)
        require('sha256:' + hashlib.sha256(config_bytes).hexdigest() == expected['id'],
                'Archived Docker image configuration does not match the recorded image ID')


def backup_helper():
    """Load only the reviewed sibling bytes, including under Python -I."""
    path = Path(__file__).resolve(strict=True).with_name('backup_host_security_20261117.py')
    require(stat.S_ISREG(path.lstat().st_mode), 'Backup guard helper is not a regular file')
    source = path.read_bytes()
    require(hashlib.sha256(source).hexdigest() == BACKUP_HELPER_SHA256,
            'Backup guard helper does not match the reviewed version')
    spec = importlib.util.spec_from_file_location('backup_host_security_20261117', path)
    module = importlib.util.module_from_spec(spec)
    # Compile the verified bytes themselves, rather than reopening a path after
    # the hash check or loading a potentially stale cached bytecode file.
    exec(compile(source, str(path), 'exec'), module.__dict__)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory')
    args = parser.parse_args()
    try:
        require(hasattr(os, 'geteuid') and os.geteuid() == 0, 'Run as root on the stopped host')
        directory = canonical_directory(args.directory)
        # Reuse the producer's read-only guards, including stopped/disabled units,
        # checkpoints, no sandbox containers, and the live rollback image tag.
        backup = backup_helper()
        backup.preflight()
        manifest = check_manifest(directory)
        expected = {'tag': backup.IMAGE_TAG, 'id': backup.IMAGE}
        require(manifest.get('docker_image') == expected, 'Backup records an unexpected Docker image')
        count = compare_selected(directory / 'applications.tar', {p.lstrip('/'): Path(p) for p in SELECTED})
        backup.check_gpt2_archive(directory / 'applications.tar')
        verify_image(directory / 'gpt2-codex-image.tar', expected)
        backup.preflight()
        print(json.dumps({'verified': True, 'artifact_sizes_match_manifest': True,
                          'selected_files_match_stopped_live_files': count,
                          'comparison_scope': '3 primary databases, 3 maintenance checkpoints, Caddyfile, active GPT-2 venv config and CA bundle, retained venv config',
                          'gpt2_venv_symlink_and_target_coverage_verified': True,
                          'docker_tag_and_configuration_digest_verified': True,
                          'full_archive_rehash_performed': False,
                          'scope_note': 'Producer hashes are recorded, not recomputed; other archived contents and Docker layers were not byte-compared.'}, indent=2))
    except (RuntimeError, OSError, ValueError, tarfile.TarError, ImportError) as error:
        # Never print OS/tar/JSON exception payloads, archive contents or private URLs.
        print(json.dumps({'verified': False, 'error': str(error) if type(error) is RuntimeError
                          else 'Verification failed; inspect private files on-host (' + type(error).__name__ + ')'}))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
