"""Build an inactive copy of GPT-2's venv with only the reviewed certifi fix.

Run as root on the reviewed host. Does not activate a venv, change a live
service, load a model, read application state or use network access. Refuses
an existing destination. Runtime tests run separately in a restricted unit.
"""
from pathlib import Path
import datetime
import hashlib
import json
import os
import pwd
import shutil
import subprocess


LIVE = Path('/home/gpt-2/.venvs/gpt2-public')
CANDIDATE = Path('/home/gpt-2/.venvs/gpt2-public-security-20261116')
STAGE = Path('/home/gpt-2/.local/share/gpt2-security-stage/20261116/python')
WHEEL = Path('/home/ec2-user/chess-security-stage-20261115/python/wheels/certifi-2026.10.23-py3-none-any.whl')
WHEEL_SHA = 'e9b54de76e530bb6cf0ccd036787103acb58fd42ba930ea8bf948ddbaa2f61d1'
PUBLIC = Path('/home/gpt-2/GPT-2-releases/seed-78ebbdc')
LAB = Path('/home/gpt-2/GPT-2-codex')


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for part in iter(lambda: f.read(1024 * 1024), b''):
            h.update(part)
    return h.hexdigest()


def run(args, **kwargs):
    env = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8',
           'PYTHONDONTWRITEBYTECODE': '1', 'PIP_CONFIG_FILE': '/dev/null',
           'PIP_DISABLE_PIP_VERSION_CHECK': '1', 'PIP_NO_CACHE_DIR': '1'}
    p = subprocess.run([str(a) for a in args], env=env, text=True,
                       capture_output=True, timeout=300, **kwargs)
    if p.returncode:
        raise RuntimeError(f'Command failed: {args[0]} ({p.returncode})\n{p.stdout[-3000:]}\n{p.stderr[-3000:]}')
    return p.stdout


def owner_run(args, **kwargs):
    return run(['/usr/sbin/runuser', '-u', 'gpt-2', '--', *args], **kwargs)


def files(root):
    result = {}
    for p in sorted(root.rglob('*')):
        rel = p.relative_to(root).as_posix()
        if '__pycache__' in p.parts or p.suffix == '.pyc':
            continue
        if p.is_symlink():
            result[rel] = {'symlink': os.readlink(p)}
        elif p.is_file():
            result[rel] = {'sha256': digest(p), 'mode': oct(p.stat().st_mode & 0o777)}
    return result


def services():
    return run(['systemctl', 'show', 'gpt2-public.service', 'gpt2-codex.service',
                '-p', 'Id', '-p', 'MainPID', '-p', 'ActiveState', '-p', 'NRestarts'])


def packages(python):
    return json.loads(owner_run([python, '-c',
        'import importlib.metadata as m,json;print(json.dumps({d.metadata["Name"]:d.version for d in m.distributions()}))']))


def main():
    if os.geteuid() != 0:
        raise RuntimeError('Run as root; commands using Python/pip run as gpt-2.')
    os.umask(0o077)
    if not LIVE.is_dir() or LIVE.is_symlink() or LIVE.resolve() != LIVE:
        raise RuntimeError('Live venv is not the expected ordinary directory.')
    if CANDIDATE.exists() or CANDIDATE.is_symlink() or STAGE.exists():
        raise RuntimeError('Candidate/stage already exists; never overwrite a prepared candidate.')
    if shutil.disk_usage(LIVE).free < 4 * 1024**3:
        raise RuntimeError('Insufficient free disk space.')
    if digest(WHEEL) != WHEEL_SHA:
        raise RuntimeError('Verified wheel hash mismatch.')
    before_services = services()
    before_files = files(LIVE)
    before_packages = packages(LIVE / 'bin/python')
    if before_packages.get('certifi') != '2026.7.22':
        raise RuntimeError('Unexpected live certifi version; re-review.')
    owner_run(['mkdir', '-p', STAGE])
    # No hard links: candidate modifications cannot write through into live files.
    owner_run(['cp', '-a', '--reflink=auto', LIVE, CANDIDATE])
    repaired = []
    for p in [CANDIDATE / 'pyvenv.cfg', *(CANDIDATE / 'bin').iterdir()]:
        if p.is_symlink() or not p.is_file():
            continue
        data = p.read_bytes()
        if str(LIVE).encode() in data:
            p.write_bytes(data.replace(str(LIVE).encode(), str(CANDIDATE).encode()))
            repaired.append(str(p.relative_to(CANDIDATE)))
    shutil.copyfile(WHEEL, STAGE / WHEEL.name)
    account = pwd.getpwnam('gpt-2')
    os.chown(STAGE / WHEEL.name, account.pw_uid, account.pw_gid)
    install_log = owner_run([CANDIDATE / 'bin/python', '-m', 'pip', 'install',
                            '--no-index', '--no-deps', STAGE / WHEEL.name])
    pip_check = owner_run([CANDIDATE / 'bin/python', '-m', 'pip', 'check']).strip()
    after_packages = packages(CANDIDATE / 'bin/python')
    expected = dict(before_packages, certifi='2026.10.23')
    if after_packages != expected:
        raise RuntimeError('Unexpected package version change.')
    candidate_files = files(CANDIDATE)
    changes = sorted(k for k in set(before_files) | set(candidate_files)
                     if before_files.get(k) != candidate_files.get(k))
    def expected_change(k):
        return k in repaired or '/certifi/' in k or '/certifi-' in k
    if any(not expected_change(k) for k in changes):
        raise RuntimeError('Unexpected changed package files: ' + repr([k for k in changes if not expected_change(k)]))
    live_after = files(LIVE)
    if before_files != live_after or services() != before_services:
        raise RuntimeError('Live files/process identity changed during staging; investigate before activation.')
    source_manifests = {}
    for name, src in [('public', PUBLIC), ('lab', LAB)]:
        target = STAGE / ('source-' + name)
        owner_run(['mkdir', target])
        for item in ('src', 'tests', 'scripts', 'deploy', 'pyproject.toml',
                     'requirements.txt', 'requirements.lock.txt'):
            if (src / item).exists():
                owner_run(['cp', '-a', '--reflink=auto', src / item, target / item])
        source_manifests[name] = files(target)
    manifest = {
        'prepared_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'candidate': str(CANDIDATE), 'live': str(LIVE), 'stage': str(STAGE),
        'wheel': {'filename': WHEEL.name, 'sha256': WHEEL_SHA},
        'activation_performed': False, 'model_calls': 0, 'emails': 0,
        'live_processes_before_after': before_services,
        'live_files_unchanged': True, 'package_versions_before': before_packages,
        'package_versions_after': after_packages, 'pip_check': pip_check,
        'repaired_path_files': repaired, 'changed_files': changes,
        'live_file_inventory_sha256': hashlib.sha256(json.dumps(before_files,sort_keys=True).encode()).hexdigest(),
        'candidate_file_inventory_sha256': hashlib.sha256(json.dumps(candidate_files,sort_keys=True).encode()).hexdigest(),
    }
    for name, value in [('stage-manifest.json', manifest), ('live-files.json', before_files),
                        ('candidate-files.json', candidate_files), ('source-files.json',source_manifests)]:
        (STAGE / name).write_text(json.dumps(value, indent=2) + '\n')
        os.chown(STAGE / name, account.pw_uid, account.pw_gid)
    (STAGE / 'pip-install.log').write_text(install_log)
    os.chown(STAGE / 'pip-install.log', account.pw_uid, account.pw_gid)
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
