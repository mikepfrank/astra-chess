#!/usr/bin/env python3
"""Check, or explicitly switch, both stopped chess services' prepared venv paths.

Default is read-only. --apply preserves both original directories and creates
symlinks to the already-tested final paths. No source, requirements, services,
notifiers, credentials, gates, data, or old Python aliases are changed. Capture
the sanitized JSON result in the operator's maintenance record.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess

STAGE = Path('/home/ec2-user/chess-security-stage-20261115/python')
REVISIONS = {'astra': '60bc178f3b442a2c333ed35dc304a99e17106b00',
             'or-chess': 'a98784cdafacbe5e6616cc55b0e94a34e8056bf2'}
BASELINE_REQUIREMENTS = 'ceb349ab6d4f93b2ee43d7adefbc8931a17bd9afd5a98f8406e9c5c236905df7'
CANDIDATE_REQUIREMENTS = '92ad905de7224d4eade9b73859d3ea8fed14726b656988576558edeb661dd4ab'
SEALED = {
    'wheel-manifest.json': '0f9ab694a3bb3b96d30d529442d07ffb9f4a5ec930517a804352020e3d1e39c5',
    'requirements-hashed.txt': '96773569c651f8cc0c92b009c463d2e79987d69be3f9b06124440e99552c1549',
    'runtime-manifest.json': 'a72ea355f823c76fa319a937ea32a460ce52749af5140fd9ff7cd605f283444c',
}
UNITS = ('astra-chess.service', 'or-chess.service', 'astra-game-notify.timer',
         'or-chess-game-notify.timer', 'astra-game-notify.service', 'or-chess-game-notify.service')
CHECKPOINTS = ('/var/lib/astra-chess-ops/maintenance.json', '/var/lib/arcturus-chess-ops/maintenance.json')
VERSIONS = {'python': '3.12.16', 'openssl': 'OpenSSL 3.5.9 29 Sep 2026',
            'sqlite': '3.53.1', 'expat': 'expat_2.10.0', 'certifi': '2026.10.23', 'pip': '26.3'}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def run(args):
    result = subprocess.run([str(arg) for arg in args], text=True, capture_output=True,
                            timeout=120, env={'PATH': '/usr/sbin:/usr/bin:/bin', 'LANG': 'C.UTF-8',
                            'PYTHONDONTWRITEBYTECODE': '1', 'PIP_CONFIG_FILE': '/dev/null',
                            'PIP_DISABLE_PIP_VERSION_CHECK': '1'})
    require(result.returncode == 0, 'A read-only validation command failed; private output was suppressed')
    return result.stdout


def regular_file(path):
    require(stat.S_ISREG(path.lstat().st_mode), 'Expected an ordinary file')
    return path.read_bytes()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def check_stopped():
    for name in UNITS:
        raw = run(['systemctl', 'show', name, '-p', 'ActiveState', '-p', 'MainPID', '-p', 'UnitFileState'])
        info = dict(line.split('=', 1) for line in raw.splitlines() if '=' in line)
        require(info.get('ActiveState') == 'inactive' and info.get('MainPID', '0') == '0',
                'A required chess unit is not completely stopped')
        if name in UNITS[:4]:
            require(info.get('UnitFileState') == 'disabled', 'A chess app or notifier timer remains enabled')
    for name in CHECKPOINTS:
        path = Path(name)
        info = path.lstat()
        require(info.st_uid == 0 and not stat.S_IMODE(info.st_mode) & 0o077,
                'Maintenance checkpoint is not root-private')
        require(json.loads(regular_file(path)).get('phase') == 'stopped', 'Missing stopped chess checkpoint')


def ordinary_directory(path, uid):
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode) and path.resolve(strict=True) == path and info.st_uid == uid,
            'An expected owned directory is absent, redirected, or has changed ownership')
    return info.st_dev, info.st_ino


def probe(owner, executable, candidate, runtime, packages):
    code = ('import sys,ssl,sqlite3,pyexpat,certifi,pip,json,pathlib;'
            'print(json.dumps(dict(python=sys.version.split()[0],openssl=ssl.OPENSSL_VERSION,'
            'sqlite=sqlite3.sqlite_version,expat=pyexpat.EXPAT_VERSION,certifi=certifi.__version__,'
            'pip=pip.__version__,prefix=str(pathlib.Path(sys.prefix).resolve()),'
            'base_prefix=str(pathlib.Path(sys.base_prefix).resolve()))));'
            'ssl.create_default_context(cafile=certifi.where())')
    command = ['runuser', '-u', owner, '--', executable, '-I', '-B']
    result = json.loads(run([*command, '-c', code]))
    require({key: result.get(key) for key in VERSIONS} == VERSIONS,
            'Candidate runtime or certificate versions differ from the reviewed candidate')
    require(result['prefix'] == str(candidate) and result['base_prefix'] == str(runtime),
            'Candidate interpreter prefixes differ from final paths')
    require(run([*command, '-m', 'pip', 'check']).strip() == 'No broken requirements found.',
            'Candidate dependency check failed')
    installed = json.loads(run([*command, '-m', 'pip', 'list', '--format=json']))
    normalized = {item['name'].lower().replace('_', '-'): item['version'] for item in installed}
    require(normalized == packages, 'Candidate installed package versions differ from sealed requirements')


def prepare():
    import pwd
    check_stopped()
    for name, expected in SEALED.items():
        require(digest(regular_file(STAGE / name)) == expected, 'Staged dependency artifacts have changed')
    packages = {}
    for line in (STAGE / 'requirements-hashed.txt').read_text().splitlines():
        pin = line.split()[0]
        name, version = pin.split('==')
        packages[name.lower().replace('_', '-')] = version
    plans = []
    for owner, revision in REVISIONS.items():
        uid = pwd.getpwnam(owner).pw_uid
        source = Path('/home') / owner / 'astra-chess'
        require(run(['runuser', '-u', owner, '--', 'git', '-C', source, 'rev-parse', 'HEAD']).strip() == revision,
                'Deployed source revision differs from the reviewed baseline')
        require(not run(['runuser', '-u', owner, '--', 'git', '-C', source,
                         'status', '--porcelain', '--untracked-files=no']).strip(),
                'Tracked production source has local changes')
        original = regular_file(source / 'web-service/requirements.txt')
        candidate_requirements = regular_file(STAGE / ('requirements-' + owner + '.txt'))
        require(digest(original) == BASELINE_REQUIREMENTS
                and digest(candidate_requirements) == CANDIDATE_REQUIREMENTS
                and original.replace(b'certifi==2026.7.22', b'certifi==2026.10.23') == candidate_requirements,
                'Source and staged requirements are not the reviewed certifi-only change')
        root = Path('/home') / owner / '.local/share' / ('astra-chess-runtime' if owner == 'astra' else 'or-chess-runtime')
        candidate = root / 'venvs/security-20261115'
        runtime = root / 'python/cpython-3.12.16-linux-x86_64-gnu'
        live = source / 'web-service/.venv'
        rollback = source / 'web-service/.venv-pre-security-20261117'
        identity = ordinary_directory(live, uid)
        ordinary_directory(candidate, uid)
        ordinary_directory(runtime, uid)
        require(not os.path.lexists(rollback), 'Rollback name already exists; review before proceeding')
        require((candidate / 'bin/python').resolve(strict=True).is_relative_to(runtime),
                'Candidate interpreter is outside the reviewed private runtime')
        probe(owner, candidate / 'bin/python', candidate, runtime, packages)
        plans.append(dict(owner=owner, source_revision=revision, live=live, candidate=candidate,
                          runtime=runtime, rollback=rollback, uid=uid, identity=identity, packages=packages))
    check_stopped()
    return plans


def restore(plan):
    """Restore only our exact new symlink and preserved ordinary directory."""
    live, candidate, rollback = plan['live'], plan['candidate'], plan['rollback']
    require(ordinary_directory(rollback, plan['uid']) == plan['identity'], 'Rollback directory identity changed')
    if os.path.lexists(live):
        require(live.is_symlink() and os.readlink(live) == str(candidate), 'Refusing to replace an unexpected live path')
        live.unlink()
    os.rename(rollback, live)
    sync_parent(live)


def sync_parent(path):
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def activate(plans):
    check_stopped()
    for plan in plans:
        require(ordinary_directory(plan['live'], plan['uid']) == plan['identity'], 'Live venv identity changed')
        require(not os.path.lexists(plan['rollback']), 'Rollback path collision')
    moved = []
    try:
        for plan in plans:
            os.rename(plan['live'], plan['rollback'])
            moved.append(plan)
            os.symlink(plan['candidate'], plan['live'])
            sync_parent(plan['live'])
        for plan in plans:
            require(plan['live'].is_symlink() and os.readlink(plan['live']) == str(plan['candidate']),
                    'Activated venv link differs from the intended candidate')
            probe(plan['owner'], plan['live'] / 'bin/python', plan['candidate'], plan['runtime'], plan['packages'])
        check_stopped()
    except BaseException:
        try:
            check_stopped()
        except BaseException:
            raise RuntimeError('Activation failed; rollback was not attempted because the stopped-unit guard failed. Inspect before changing runtime paths') from None
        failed = False
        for plan in reversed(moved):
            try:
                restore(plan)
            except BaseException:
                failed = True
        if failed:
            raise RuntimeError('Activation failed and rollback needs manual inspection; services remain stopped') from None
        raise RuntimeError('Activation failed; original venv directories were restored and services remain stopped') from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        require(hasattr(os, 'geteuid') and os.geteuid() == 0, 'Run as root on the reviewed host')
        plans = prepare()
        if args.apply:
            activate(plans)
        print(json.dumps({'verified': True, 'applied': args.apply, 'services_started': False,
            'requirements_modified': False, 'versions': VERSIONS,
            'plans': [{key: str(plan[key]) for key in ('owner', 'source_revision', 'live', 'candidate', 'runtime', 'rollback')}
                      for plan in plans]}, indent=2))
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({'verified': False, 'error': str(error) if type(error) is RuntimeError
                          else 'Validation failed; private details suppressed (' + type(error).__name__ + ')'}))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
