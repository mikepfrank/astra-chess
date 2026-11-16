#!/usr/bin/env python3
"""Create private, offline application recovery archives after all four drains.

Never stops a service or changes application state. --check is read-only and
refuses until every required stopped checkpoint exists. Backups stay on-host;
their contents include credentials and must not be committed or printed.
"""
from pathlib import Path
import argparse
import datetime
import hashlib
import json
import os
import stat
import subprocess
import tarfile

APPS = ('astra-chess.service', 'or-chess.service', 'gpt2-public.service', 'gpt2-codex.service')
TIMERS = ('astra-game-notify.timer', 'or-chess-game-notify.timer')
JOBS = ('astra-game-notify.service', 'or-chess-game-notify.service', 'gpt2-preview.service')
CHECKPOINTS = ('/var/lib/astra-chess-ops/maintenance.json',
               '/var/lib/arcturus-chess-ops/maintenance.json',
               '/var/lib/gpt2-maintenance-ops/maintenance.json')
ROOTS = (
    'etc', 'usr/local/libexec', 'usr/local/bin',
    'home/astra/astra-chess', 'home/astra/.config/astra-chess',
    'home/astra/.config/astra-chess-monitor', 'home/astra/.local/share/astra-chess',
    'home/astra/.local/share/astra-chess-runtime', 'home/astra/.local/share/astra-caddy',
    'home/astra/.local/state/astra-chess-monitor', 'home/astra/.local/bin', 'home/astra/.codex',
    'home/or-chess/astra-chess', 'home/or-chess/.config/or-chess',
    'home/or-chess/.config/or-chess-monitor', 'home/or-chess/.local/share/or-chess',
    'home/or-chess/.local/share/or-chess-runtime', 'home/or-chess/.local/state/or-chess-monitor',
    'home/gpt-2/GPT-2-releases', 'home/gpt-2/GPT-2-codex', 'home/gpt-2/GPT-2-tools',
    'home/gpt-2/.venvs/gpt2-public', 'home/gpt-2/.cache/gpt2-public/huggingface',
    'home/gpt-2/.local/share/gpt2-codex', 'var/lib/astra-chess-ops',
    'var/lib/arcturus-chess-ops', 'var/lib/gpt2-codex-ops', 'var/lib/gpt2-maintenance-ops',
    'home/ec2-user/astra-down.sh', 'home/ec2-user/astra-up.sh',
    'home/ec2-user/arcturus-down.sh', 'home/ec2-user/arcturus-up.sh',
    'home/ec2-user/chess-security-stage-20261116/ops',
)
IMAGE = 'sha256:9d9274de90e73ba2e215935f0dfbd09eb5c2fe248ba7a6b3052e45969de496fb'
IMAGE_TAG = 'gpt2-codex-runtime:0.154.0'
DB_ROOTS = {'astra': '/home/astra/.local/share/astra-chess',
            'or-chess': '/home/or-chess/.local/share/or-chess',
            'gpt-2': '/home/gpt-2/.local/share/gpt2-codex'}


def require(value, message):
    if not value:
        raise RuntimeError(message)


def run(args, timeout=60):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    require(result.returncode == 0, 'Private backup command failed; inspect on-host, no secrets printed')
    return result.stdout


def preflight():
    units = {}
    for name in (*APPS, *TIMERS, *JOBS):
        raw = run(['systemctl', 'show', name, '-p', 'ActiveState', '-p', 'MainPID', '-p', 'UnitFileState'])
        info = dict(line.split('=', 1) for line in raw.splitlines() if '=' in line)
        require(info.get('ActiveState') == 'inactive' and info.get('MainPID', '0') == '0',
                'Unit is not stopped: ' + name)
        if name in (*APPS, *TIMERS):
            require(info.get('UnitFileState') == 'disabled', 'Unit can restart at boot: ' + name)
        units[name] = info
    for index, path in enumerate(CHECKPOINTS):
        p = Path(path)
        info = p.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o077,
                'Unsafe maintenance checkpoint')
        record = json.loads(p.read_text())
        if index < 2:
            require(record.get('phase') == 'stopped', 'Chess drain checkpoint is not stopped')
        else:
            services = record.get('services', {})
            require(set(services) == set(APPS[2:]) and all(v.get('phase') == 'stopped' for v in services.values()),
                    'GPT-2 drain checkpoint is not stopped')
    require(not run(['docker', 'ps', '-q', '--filter', 'label=io.gpt2-codex=sandbox']).strip(),
            'GPT-2 sandbox still running')
    require(run(['docker', 'image', 'inspect', '--format', '{{.Id}}', IMAGE_TAG]).strip() == IMAGE,
            'Rollback image tag changed; inspect before backup')
    for root in ROOTS:
        require(Path('/' + root).exists(), 'Required backup source missing: ' + root)
    return units


def check_databases():
    # Execute as each owning account. Do not import applications or their stores.
    code = '''import pathlib,sqlite3,json,sys
root=pathlib.Path(sys.argv[1]); checked=0
main=root/sys.argv[2]
if main.is_symlink() or not main.is_file(): raise RuntimeError('Primary database missing or unexpected symlink')
with main.open('rb') as f:
 if f.read(16)!=b'SQLite format 3\\0': raise RuntimeError('Primary database header invalid')
for p in root.rglob('*'):
 if p.is_symlink() or not p.is_file() or p.suffix not in ('.db','.sqlite','.sqlite3'): continue
 with p.open('rb') as f: header=f.read(16)
 if header!=b'SQLite format 3\\0': continue
 c=sqlite3.connect(p.as_uri()+'?mode=ro',uri=True)
 try:
  result=c.execute('PRAGMA quick_check').fetchall()
  if result!=[('ok',)]: raise RuntimeError('SQLite quick_check failed')
 finally: c.close()
 checked+=1
print(json.dumps({'checked':checked,'all_ok':True}))
'''
    results = {owner: json.loads(run(['runuser', '-u', owner, '--', '/usr/bin/python3', '-I', '-B',
                                    '-c', code, path, 'chats.sqlite3' if owner == 'gpt-2' else 'astra.sqlite3'],
                                   timeout=300)) for owner, path in DB_ROOTS.items()}
    require(all(r.get('checked', 0) > 0 and r.get('all_ok') is True for r in results.values()),
            'No verified databases for a required application account')
    return results


def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def sync_file(path):
    with path.open('rb') as stream:
        os.fsync(stream.fileno())


def finish_manifest(dest, result):
    # A checksum can read dirty page cache: flush archive blocks before reporting
    # completion so an immediate EBS snapshot has a durable recovery checkpoint.
    for path in dest.iterdir():
        if path.is_file():
            sync_file(path)
    temporary = dest / '.manifest-final.json'
    with temporary.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, dest / 'manifest.json')
    for directory in (dest, dest.parent, dest.parent.parent):
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    require(os.geteuid() == 0, 'Run as root on the reviewed Linux host')
    os.umask(0o077)
    units = preflight()
    if args.check:
        print('All four stopped checkpoints, inactive jobs and backup paths verified; no changes.')
        return
    parent = Path('/var/backups/chess-security')
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = parent.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o077,
            'Backup directory is not root-private')
    now = datetime.datetime.now(datetime.timezone.utc)
    dest = parent / now.strftime('%Y%m%dT%H%M%SZ')
    dest.mkdir(mode=0o700)
    result = {'created_at_utc': now.isoformat(), 'units': units, 'docker_image': {'tag': IMAGE_TAG, 'id': IMAGE},
              'sqlite': check_databases(), 'complete': False}
    (dest / 'manifest.json').write_text(json.dumps(result, indent=2) + '\n')
    archive = dest / 'applications.tar'
    print('Creating private application archive; services remain stopped.', flush=True)
    run(['tar', '--create', '--file', str(archive), '--acls', '--xattrs', '--selinux',
         '--numeric-owner', '--sparse', '--directory', '/', '--', *ROOTS], timeout=1800)
    count = 0
    with tarfile.open(archive, 'r|') as handle:
        for member in handle:
            p = Path(member.name)
            require(not p.is_absolute() and '..' not in p.parts, 'Unsafe archive member')
            count += 1
    require(count > len(ROOTS), 'Archive unexpectedly empty')
    image = dest / 'gpt2-codex-image.tar'
    run(['docker', 'image', 'save', '--output', str(image), IMAGE_TAG], timeout=600)
    for name, args in {'rpm-inventory.txt': ['rpm', '-qa'],
                       'installed-units.txt': ['systemctl', 'list-unit-files', '--no-pager'],
                       'iptables.txt': ['iptables-save']}.items():
        (dest / name).write_text(run(args))
    preflight()
    result.update(complete=True, archive_members=count, files={p.name: {'bytes': p.stat().st_size,
                  'sha256': sha256(p)} for p in dest.iterdir() if p.name != 'manifest.json'})
    finish_manifest(dest, result)
    print(json.dumps({'backup_directory': str(dest), 'complete': True, 'archive_members': count,
                      'sqlite': result['sqlite'], 'files': result['files']}, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError, tarfile.TarError) as exc:
        print('Backup incomplete: ' + (str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__))
        raise SystemExit(1)
