#!/usr/bin/env python3
"""Check or activate the sealed shared GPT-2 certifi environment while stopped.

Default/--check is read-only. --apply preserves the old directory and installs
one symlink; it never starts a service, imports application constructors, reads
credentials or changes the selected source/image. Run beside the reviewed
backup_host_security.py and gpt2_maintenance-v2.py helpers.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
import types

LIVE = Path('/home/gpt-2/.venvs/gpt2-public')
CANDIDATE = Path('/home/gpt-2/.venvs/gpt2-public-security-20261116')
ROLLBACK = Path('/home/gpt-2/.venvs/gpt2-public-pre-security-20261117')
STAGE = Path('/home/gpt-2/.local/share/gpt2-security-stage/20261116/python')
INVENTORY_HASHES = {
    'live': '80ba8af4d3c6be3756d4216e149fc6c4c3c0a90a9e5163772bb5ea4622f1899b',
    'candidate': '87ae9d531b9c4ae378eef417cff19ead37f5141d2048ea284cfab6dd59b67f6a',
}
PACKAGE_HASH = 'a6fbb60f2a026548d60659351070694986d939cfc405964f1afb1ecbd6a352ac'
HELPERS = {
    'backup_host_security.py': 'dba364ed5ab800ab3843d45710a9b9ae36237b82d848609d253027fe8b36f5e7',
    'gpt2_maintenance-v2.py': '80018c27bb074cd66782b9313346b5033bce808cc0a1058c543b92585b1f7912',
}


def require(value, message):
    if not value:
        raise RuntimeError(message)


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(part)
    return result.hexdigest()


def canonical_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def files(root):
    result = {}
    for path in sorted(root.rglob('*')):
        if '__pycache__' in path.parts or path.suffix == '.pyc':
            continue
        name = path.relative_to(root).as_posix()
        if path.is_symlink():
            result[name] = {'symlink': os.readlink(path)}
        elif path.is_file():
            result[name] = {'sha256': digest(path), 'mode': oct(path.stat().st_mode & 0o777)}
        else:
            require(path.is_dir(), 'Unexpected special file in venv')
    return result


def check_inventory(root, name):
    expected = json.loads((STAGE / (name + '-files.json')).read_bytes())
    require(canonical_digest(expected) == INVENTORY_HASHES[name], 'Recorded inventory changed')
    actual = files(root)
    require(actual == expected, 'Venv content, paths or file modes changed')
    return len(actual)


def ordinary_directory(path):
    require(path.is_dir() and not path.is_symlink() and path.resolve() == path,
            'Expected a resolved ordinary directory')


def placement(live=LIVE, candidate=CANDIDATE, rollback=ROLLBACK):
    ordinary_directory(candidate)
    if live.is_symlink():
        require(os.readlink(live) == str(candidate), 'Unexpected live symlink')
        ordinary_directory(rollback)
        return 'activated'
    ordinary_directory(live)
    require(not os.path.lexists(rollback), 'Rollback path already exists')
    return 'original'


def load_helper(name):
    path = Path(__file__).resolve().with_name(name)
    require(stat.S_ISREG(path.lstat().st_mode), 'Helper must be a regular file')
    source = path.read_bytes()
    require(hashlib.sha256(source).hexdigest() == HELPERS[name], 'Guard helper digest changed')
    module = types.ModuleType('reviewed_' + name.replace('.', '_'))
    module.__file__ = str(path)
    exec(compile(source, str(path), 'exec'), module.__dict__)
    return module


def probe(python):
    code = r'''import sys,ssl,certifi,importlib.metadata as m,json,hashlib
assert sys.version_info[:3]==(3,12,16) and sys.base_prefix=='/usr'
assert ssl.OPENSSL_VERSION.startswith('OpenSSL 3.5.8 ')
assert certifi.__version__=='2026.10.23'
ssl.create_default_context(cafile=certifi.where())
packages={d.metadata['Name']:d.version for d in m.distributions()}
print(json.dumps({'python':sys.version.split()[0],'openssl':ssl.OPENSSL_VERSION,
 'certifi':certifi.__version__,'base_prefix':sys.base_prefix,
 'package_digest':hashlib.sha256(json.dumps(packages,sort_keys=True).encode()).hexdigest()}))
'''
    base = ['/usr/sbin/runuser', '-u', 'gpt-2', '--', '/usr/bin/env', '-i',
            'PATH=/usr/bin:/bin', 'PYTHONDONTWRITEBYTECODE=1',
            'PIP_CONFIG_FILE=/dev/null', 'PIP_DISABLE_PIP_VERSION_CHECK=1', str(python), '-I', '-B']
    result = subprocess.run([*base, '-c', code], cwd='/', capture_output=True, text=True, timeout=120)
    require(result.returncode == 0, 'Candidate runtime/TLS probe failed')
    data = json.loads(result.stdout)
    require(data['package_digest'] == PACKAGE_HASH, 'Installed package set differs from approved candidate')
    result = subprocess.run([*base, '-m', 'pip', 'check'], cwd='/', capture_output=True, text=True, timeout=120)
    require(result.returncode == 0, 'Candidate dependency consistency check failed')
    data['pip_check'] = True
    return data


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def swap(live=LIVE, candidate=CANDIDATE, rollback=ROLLBACK):
    require(placement(live, candidate, rollback) == 'original', 'Already activated; use --check')
    os.rename(live, rollback)
    try:
        os.symlink(candidate, live)
        # Preserve the service account's ownership of its path; target untouched.
        info = rollback.stat()
        os.chown(live, info.st_uid, info.st_gid, follow_symlinks=False)
        sync_directory(live.parent)
    except BaseException:
        if live.is_symlink() and os.readlink(live) == str(candidate):
            live.unlink()
        require(not os.path.lexists(live), 'Swap failed with unexpected live path; retained original requires review')
        os.rename(rollback, live)
        sync_directory(live.parent)
        raise


def require_stopped(backup):
    # Separate from full backup preflight: a changed image/checkpoint can fail
    # that guard while reverting the venv is still safe. Never revert a running
    # service's runtime path, even when another post-activation check failed.
    for name in (*backup.APPS, *backup.TIMERS, *backup.JOBS):
        raw = backup.run(['systemctl', 'show', name, '-p', 'ActiveState',
                          '-p', 'MainPID', '-p', 'UnitFileState'])
        info = dict(line.split('=', 1) for line in raw.splitlines() if '=' in line)
        require(info.get('ActiveState') == 'inactive' and info.get('MainPID', '0') == '0',
                'Rollback refused: a scoped service is running')
        if name in (*backup.APPS, *backup.TIMERS):
            require(info.get('UnitFileState') == 'disabled', 'Rollback refused: boot setting changed')


def restore_original(stopped_guard, live=LIVE, candidate=CANDIDATE, rollback=ROLLBACK):
    require(placement(live, candidate, rollback) == 'activated', 'Rollback path identity is unexpected')
    stopped_guard()
    # placement checked the exact symlink string and an ordinary rollback dir.
    # Remove only this link, never its target or any application data.
    live.unlink()
    os.rename(rollback, live)
    sync_directory(live.parent)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--check', action='store_true')
    group.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    require(sys.platform == 'linux' and os.geteuid() == 0, 'Run as root on the reviewed host')
    backup = load_helper('backup_host_security.py')
    maintenance = load_helper('gpt2_maintenance-v2.py')
    # Serialize with the existing GPT-2 lifecycle helper, including starts.
    with maintenance.lock(maintenance.STATE_DIR / 'operation.lock'):
        backup.preflight()
        saved = maintenance.load()
        for name in (maintenance.PUBLIC, maintenance.LAB):
            maintenance.verify_gate(saved, name)
        state = placement()
        require(not args.apply or state == 'original', 'Already activated; use --check')
        old_path = LIVE if state == 'original' else ROLLBACK
        import pwd
        owner = pwd.getpwnam('gpt-2')
        for root in (old_path, CANDIDATE):
            for path in (root, *root.rglob('*')):
                info = path.lstat()
                require(info.st_uid == owner.pw_uid and info.st_gid == owner.pw_gid,
                        'Unexpected venv ownership')
        counts = {'original': check_inventory(old_path, 'live'),
                  'candidate': check_inventory(CANDIDATE, 'candidate')}
        runtime = probe(CANDIDATE / 'bin/python')
        backup.preflight()
        if args.apply:
            swap()
            try:
                runtime = probe(LIVE / 'bin/python')
                backup.preflight()
                state = placement()
            except BaseException as error:
                try:
                    restore_original(lambda: require_stopped(backup))
                except BaseException as rollback_error:
                    raise RuntimeError('Post-activation check failed; rollback refused or failed; inspect retained paths') from rollback_error
                raise RuntimeError('Post-activation check failed; original venv restored while services stayed stopped') from error
        print(json.dumps({'placement': state, 'applied': args.apply, 'inventories': counts,
                          'runtime': runtime, 'live_path': str(LIVE),
                          'candidate_path': str(CANDIDATE), 'rollback_path': str(ROLLBACK),
                          'services_started': False}, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({'passed': False, 'error': str(error) if type(error) is RuntimeError
                          else 'Activation/check failed: ' + type(error).__name__}))
        raise SystemExit(1)
