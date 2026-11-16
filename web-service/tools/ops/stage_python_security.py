"""Prepare isolated Python candidates; never change a live service or its venv.

Run as ec2-user on the reviewed Lightsail host. All writes stay in STAGE.
The only elevated operations read git archives from the two deployed checkouts.
Full fixture tests are run separately in a private-network transient unit.
"""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import tarfile
import urllib.request


STAGE = Path('/home/ec2-user/chess-security-stage-20261115/python')
RELEASE = '20261110'
ARCHIVE = 'cpython-3.12.16+20261110-x86_64-unknown-linux-gnu-install_only.tar.gz'
SHA256 = 'c2f87d4b4e8db3abddb0f116c6ccfc503d0cbdbb9ee8faacddad1b679ec12e99'
REVISIONS = {
    'astra': '60bc178f3b442a2c333ed35dc304a99e17106b00',
    'or-chess': 'a98784cdafacbe5e6616cc55b0e94a34e8056bf2',
}
BUILD_TOOLS = {'pip': '26.3', 'setuptools': '84.2.1', 'wheel': '0.48.0', 'packaging': '26.3'}


def run(args, *, cwd=None, timeout=180):
    clean = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8',
             'PYTHONDONTWRITEBYTECODE': '1', 'PIP_DISABLE_PIP_VERSION_CHECK': '1',
             'PIP_CONFIG_FILE': '/dev/null', 'PIP_NO_CACHE_DIR': '1'}
    result = subprocess.run([str(x) for x in args], cwd=cwd, env=clean,
                            text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f'Command failed ({result.returncode}): {args}\n'
                           f'{result.stdout[-5000:]}\n{result.stderr[-5000:]}')
    return result.stdout


def fetch(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'chess-security-staging'})
    with urllib.request.urlopen(request, timeout=90) as response:
        return response.read()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_json(name, value):
    (STAGE / name).write_text(json.dumps(value, indent=2) + '\n')


def main():
    if os.geteuid() == 0:
        raise RuntimeError('Run as unprivileged ec2-user, not root.')
    os.umask(0o077)
    if (STAGE / 'stage-complete.json').exists():
        raise RuntimeError('This candidate is sealed. Use the retained hashed artifacts; '
                           'restaging requires a new reviewed directory.')
    STAGE.mkdir(parents=True, exist_ok=True)
    if STAGE.is_symlink() or STAGE.resolve() != STAGE:
        raise RuntimeError('Unexpected staging path.')
    downloads = STAGE / 'downloads'
    downloads.mkdir(exist_ok=True)
    archive = downloads / ARCHIVE
    url = ('https://github.com/astral-sh/python-build-standalone/releases/download/'
           + RELEASE + '/' + ARCHIVE.replace('+', '%2B'))
    if not archive.exists():
        archive.write_bytes(fetch(url))
    if digest(archive) != SHA256:
        raise RuntimeError('Python artifact digest mismatch.')
    sums = fetch('https://github.com/astral-sh/python-build-standalone/releases/'
                 'download/' + RELEASE + '/SHA256SUMS').decode()
    expected = [line.split()[0] for line in sums.splitlines() if line.split()[-1] == ARCHIVE]
    if expected != [SHA256]:
        raise RuntimeError('Published checksum file disagrees with pinned asset digest.')
    (downloads / 'SHA256SUMS').write_text(sums)
    runtime = STAGE / 'runtime'
    python = runtime / 'python/bin/python3.12'
    if not runtime.exists():
        runtime.mkdir()
        # Validate members before invoking the system extractor as ec2-user.
        with tarfile.open(archive) as handle:
            for member in handle.getmembers():
                path = Path(member.name)
                if path.is_absolute() or '..' in path.parts or path.parts[0] != 'python':
                    raise RuntimeError('Unsafe archive member.')
                if member.isdev() or member.isfifo():
                    raise RuntimeError('Unexpected special archive member.')
                if member.issym() or member.islnk():
                    target = (runtime / path.parent / member.linkname if member.issym()
                              else runtime / member.linkname).resolve()
                    if runtime.resolve() not in target.parents:
                        raise RuntimeError('Archive link leaves runtime.')
        run(['tar', '--extract', '--gzip', '--no-same-owner', '--no-same-permissions',
             '--file', archive, '--directory', runtime])
    versions = json.loads(run([python, '-c',
        'import sys,ssl,sqlite3,pyexpat,json;print(json.dumps(dict('
        'python=sys.version.split()[0],openssl=ssl.OPENSSL_VERSION,'
        'sqlite=sqlite3.sqlite_version,expat=pyexpat.EXPAT_VERSION)))']))
    if versions['python'] != '3.12.16':
        raise RuntimeError('Unexpected Python version.')
    if tuple(map(int, versions['openssl'].split()[1].split('.'))) < (3, 5, 9):
        raise RuntimeError('Candidate OpenSSL still predates the reviewed patch.')
    if tuple(map(int, versions['expat'].removeprefix('expat_').split('.'))) < (2, 9, 0):
        raise RuntimeError('Candidate Expat still predates the reviewed patch.')
    save_json('runtime-manifest.json', {'source': url, 'sha256': SHA256, **versions})
    print(json.dumps({'runtime': versions}), flush=True)

    for user, revision in REVISIONS.items():
        source = Path('/home') / user / 'astra-chess'
        actual = run(['sudo', '-u', user, 'git', '-C', source, 'rev-parse', 'HEAD']).strip()
        if actual != revision:
            raise RuntimeError(f'{user} live source changed; review before continuing.')
        archive_path = downloads / (user + '-source.tar')
        if not archive_path.exists():
            with archive_path.open('wb') as output:
                subprocess.run(['sudo', '-u', user, 'git', '-C', str(source),
                                'archive', revision], stdout=output, check=True)
        checkout = STAGE / ('source-' + user)
        if not checkout.exists():
            checkout.mkdir()
            run([python, '-c', 'import tarfile,sys;tarfile.open(sys.argv[1]).extractall('
                 'sys.argv[2],filter="data")', archive_path, checkout])
        requirements = (checkout / 'web-service/requirements.txt').read_text()
        if requirements.count('certifi==2026.7.22') != 1:
            raise RuntimeError('Unexpected certifi pin in deployed baseline.')
        candidate = requirements.replace('certifi==2026.7.22', 'certifi==2026.10.23')
        (STAGE / ('requirements-' + user + '.txt')).write_text(candidate)

    wheels = STAGE / 'wheels'
    wheels.mkdir(exist_ok=True)
    bootstrap = STAGE / 'bootstrap-venv'
    if not bootstrap.exists():
        run([python, '-m', 'venv', bootstrap])
    bootstrap_python = bootstrap / 'bin/python'
    def metadata_for(name, version=None):
        suffix = f'/{version}' if version else ''
        return json.loads(run([python, '-c',
            'import urllib.request,sys;print(urllib.request.urlopen(sys.argv[1],timeout=30).read().decode())',
            f'https://pypi.org/pypi/{name}{suffix}/json']))

    # python-chess publishes 1.11.2 as source only. Build that unchanged pin
    # from its verified sdist, using isolated, verified build-tool wheels.
    build_wheels = STAGE / 'build-tool-wheels'
    build_wheels.mkdir(exist_ok=True)
    build_manifest = []
    for name, version in BUILD_TOOLS.items():
        meta = metadata_for(name, version)
        if meta.get('vulnerabilities'):
            raise RuntimeError(f'Review build-tool advisories before using {name}.')
        candidates = [entry for entry in meta['urls'] if entry['filename'].endswith('py3-none-any.whl')
                      and not entry.get('yanked')]
        if len(candidates) != 1:
            raise RuntimeError(f'Unexpected build-tool wheel for {name}.')
        entry = candidates[0]
        destination = build_wheels / entry['filename']
        if not destination.exists():
            destination.write_bytes(fetch(entry['url']))
        if digest(destination) != entry['digests']['sha256']:
            raise RuntimeError('Build-tool digest mismatch.')
        build_manifest.append({'package': name, 'version': meta['info']['version'],
            'filename': entry['filename'], 'sha256': digest(destination), 'url': entry['url']})
    run([bootstrap_python, '-m', 'pip', '--isolated', 'install', '--no-index', '--no-deps',
         *[build_wheels / item['filename'] for item in build_manifest]])
    save_json('build-tool-manifest.json', build_manifest)
    chess_meta = metadata_for('chess', '1.11.2')
    chess_sources = [entry for entry in chess_meta['urls']
                     if entry['packagetype'] == 'sdist' and not entry.get('yanked')]
    if len(chess_sources) != 1:
        raise RuntimeError('Unexpected python-chess source artifact.')
    chess_source = chess_sources[0]
    chess_archive = downloads / chess_source['filename']
    if not chess_archive.exists():
        chess_archive.write_bytes(fetch(chess_source['url']))
    if digest(chess_archive) != chess_source['digests']['sha256']:
        raise RuntimeError('python-chess source digest mismatch.')
    retained_wheels = list(wheels.glob('chess-1.11.2-*.whl'))
    if retained_wheels:
        retained = json.loads((STAGE / 'wheel-manifest.json').read_text())
        expected = [item for item in retained if item['package'] == 'chess==1.11.2']
        if len(retained_wheels) != 1 or len(expected) != 1 or digest(retained_wheels[0]) != expected[0]['sha256']:
            raise RuntimeError('Retained replay wheel differs from its reviewed manifest.')
    else:
        run([bootstrap_python, '-m', 'pip', '--isolated', 'wheel', '--no-index',
             '--no-build-isolation', '--no-deps', '--wheel-dir', wheels, chess_archive])
    binary_requirements = STAGE / 'requirements-binary.txt'
    binary_requirements.write_text('\n'.join(line for line in
        (STAGE / 'requirements-astra.txt').read_text().splitlines() if not line.startswith('chess==')) + '\n')
    # CPython 3.12.16 blocks the compromised CA keys during these HTTPS reads.
    run([bootstrap_python, '-m', 'pip', '--isolated', 'download', '--only-binary=:all:',
         '--no-deps', '--dest', wheels, '--index-url', 'https://pypi.org/simple',
         '-r', binary_requirements, 'pip==26.3'])
    other = (STAGE / 'requirements-or-chess.txt').read_text()
    if other != (STAGE / 'requirements-astra.txt').read_text():
        raise RuntimeError('Service requirements differ; review the combined wheel set.')
    manifest = []
    pins = [line.strip() for line in other.splitlines()
            if line.strip() and not line.startswith('#')] + ['pip==26.3']
    hashes = []
    for pin in pins:
        name, version = pin.split('==')
        if name == 'chess':
            built = list(wheels.glob('chess-1.11.2-*.whl'))
            if len(built) != 1:
                raise RuntimeError('Unexpected python-chess wheel output.')
            actual = digest(built[0])
            manifest.append({'package': pin, 'filename': built[0].name, 'sha256': actual,
                             'source_url': chess_source['url'],
                             'source_sha256': chess_source['digests']['sha256'],
                             'build_tools': 'build-tool-manifest.json'})
            hashes.append(pin + ' --hash=sha256:' + actual)
            continue
        metadata = metadata_for(name, version)
        matches = [entry for entry in metadata['urls']
                   if entry['packagetype'] == 'bdist_wheel' and (wheels / entry['filename']).exists()]
        if len(matches) != 1 or matches[0].get('yanked'):
            raise RuntimeError(f'Unexpected wheel selection for {pin}.')
        entry = matches[0]
        actual = digest(wheels / entry['filename'])
        if actual != entry['digests']['sha256']:
            raise RuntimeError(f'Wheel digest mismatch for {pin}.')
        manifest.append({'package': pin, 'filename': entry['filename'], 'sha256': actual,
                         'url': entry['url']})
        hashes.append(pin + ' --hash=sha256:' + actual)
    save_json('wheel-manifest.json', manifest)
    locked = STAGE / 'requirements-hashed.txt'
    locked.write_text('\n'.join(hashes) + '\n')
    for user in REVISIONS:
        venv = STAGE / ('venv-' + user)
        if not venv.exists():
            run([python, '-m', 'venv', venv])
        vpython = venv / 'bin/python'
        run([vpython, '-m', 'pip', '--isolated', 'install', '--no-index', '--find-links',
             wheels, '--require-hashes', '--no-deps', '-r', locked])
        checked = run([vpython, '-m', 'pip', 'check']).strip()
        versions = json.loads(run([vpython, '-m', 'pip', 'list', '--format=json']))
        save_json('venv-' + user + '-manifest.json', {'source_revision': REVISIONS[user],
                  'python': str(vpython), 'pip_check': checked, 'packages': versions})
        print(json.dumps({'user': user, 'pip_check': checked, 'package_count': len(versions)}), flush=True)
    save_json('stage-complete.json', {'version': 1, 'wheel_manifest_sha256':
        digest(STAGE / 'wheel-manifest.json'), 'requirements_sha256': digest(locked),
        'runtime_manifest_sha256': digest(STAGE / 'runtime-manifest.json')})
    print('Isolated Python candidates ready and sealed; no production paths changed.', flush=True)


if __name__ == '__main__':
    main()
