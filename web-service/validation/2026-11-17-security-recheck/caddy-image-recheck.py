"""One-time preparation recheck: no promotion, live reload, or provider calls.

Run on the reviewed host as root, substituting PROBE64 with the existing,
reviewed gpt2_image_security_probe.PROBE string encoded in base64.
"""
import base64
import datetime
import hashlib
import json
import os
from pathlib import Path
import pwd
import runpy
import subprocess
import time

CADDY = Path('/home/ec2-user/chess-security-stage-20261115/caddy')
IMAGE = Path('/home/ec2-user/chess-security-stage-20261116/gpt2-image')
PROBE = base64.b64decode('__PROBE64__').decode()


def digest(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def call(args, **kwargs):
    return subprocess.run(args, capture_output=True, text=True, check=True, timeout=60, **kwargs).stdout


def units():
    names = ['astra-chess.service', 'or-chess.service', 'gpt2-public.service',
             'gpt2-codex.service', 'astra-caddy.service']
    return {name: dict(line.split('=', 1) for line in call(['systemctl', 'show', name,
        '-p', 'MainPID', '-p', 'ActiveState', '-p', 'NRestarts']).splitlines()) for name in names}


def main():
    assert os.geteuid() == 0
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    report = {'checked_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'production_units_before': units()}
    preserved = [CADDY / name for name in ['build-report.json', 'fixture-report.json',
        'live-adapt-report.json', 'vulnerability-report.json', 'stage_caddy_security.py']]
    preserved += [IMAGE / 'manifest.json', IMAGE / 'probe-results-v3.json',
                  Path('/usr/local/libexec/gpt2-codex-sandbox'),
                  Path('/usr/local/libexec/gpt2-codex-seccomp.json')]
    saved_hashes = {str(p): digest(p) for p in preserved}
    build = json.loads((CADDY / 'build-report.json').read_text())
    expected = 'e8903acf0e525a53d9ad7c8d72b10bc63b71392ff39f9b7786c15d51a0639d01'
    assert digest(CADDY / 'bin/caddy') == build['binary_sha256'] == expected
    assert digest(CADDY / 'downloads/go1.27.4.linux-amd64.tar.gz') == build['go_archive_sha256']
    assert digest(CADDY / 'src/go.sum') == build['go_sum_sha256']
    assert (CADDY / 'src/go.mod').read_text() == build['go_mod']
    info = call([str(CADDY / 'bin/caddy'), 'build-info'])
    assert info == build['build_info']
    report['caddy_artifact'] = {'binary_sha256': expected,
        'version': call([str(CADDY / 'bin/caddy'), 'version']).strip(),
        'go_archive_matches': True, 'go_mod_and_sum_match': True, 'build_info_matches': True}

    live_paths = [Path('/home/astra/.local/bin/caddy'),
        Path('/home/astra/.config/astra-chess/Caddyfile'),
        Path('/home/astra/.config/astra-chess/new-games.caddy')]
    live_hashes = {str(p): digest(p) for p in live_paths}
    account = pwd.getpwnam('astra')
    env = {'PATH': '/usr/bin:/bin', 'HOME': '/nonexistent-caddy-recheck', 'USER': 'astra',
           'LOGNAME': 'astra', 'XDG_CONFIG_HOME': '/nonexistent-caddy-recheck/config',
           'XDG_DATA_HOME': '/nonexistent-caddy-recheck/data'}
    adapted, modules = {}, {}
    for label, binary in [('installed', live_paths[0]), ('candidate', CADDY / 'bin/caddy')]:
        fd = os.open(binary, os.O_RDONLY)
        try:
            common = dict(pass_fds=(fd,), user=account.pw_uid, group=account.pw_gid,
                          extra_groups=[], env=env, cwd='/tmp')
            adapted[label] = json.loads(call(['/proc/self/fd/' + str(fd), 'adapt', '--config',
                str(live_paths[1]), '--adapter', 'caddyfile'], **common))
            modules[label] = sorted(line.strip() for line in call(['/proc/self/fd/' + str(fd),
                'list-modules'], **common).splitlines() if line.strip() and 'modules:' not in line)
        finally:
            os.close(fd)
    assert adapted['installed'] == adapted['candidate']
    missing = sorted(set(modules['installed']) - set(modules['candidate']))
    assert not missing
    report['caddy_config'] = {'adapted_as_user': 'astra', 'canonical_configs_equal': True,
        'canonical_config_sha256': hashlib.sha256(json.dumps(adapted['candidate'], sort_keys=True).encode()).hexdigest(),
        'installed_module_count': len(modules['installed']), 'candidate_module_count': len(modules['candidate']),
        'missing_modules': missing, 'live_config_provisioned': False}

    fixture = CADDY / ('fixture-recheck-' + stamp)
    fixture.mkdir(mode=0o700)
    os.chown(fixture, 1000, 1000)
    constant = runpy.run_path(str(CADDY / 'stage_caddy_security.py'), run_name='read_fixture')['FIXTURE_GO']
    source = fixture / 'fixture.go'
    source.write_text(constant); source.chmod(0o600); os.chown(source, 1000, 1000)
    props = ['User=ec2-user', 'Group=ec2-user', 'CPUQuota=50%', 'MemoryMax=768M',
        'TasksMax=128', 'Nice=10', 'RuntimeMaxSec=180', 'PrivateNetwork=yes', 'PrivateTmp=yes',
        'NoNewPrivileges=yes', 'ProtectSystem=strict', 'ProtectHome=tmpfs',
        'BindReadOnlyPaths=' + str(CADDY), 'BindPaths=' + str(fixture),
        'BindPaths=' + str(CADDY / 'cache'), 'ReadWritePaths=' + str(fixture),
        'ReadWritePaths=' + str(CADDY / 'cache'), 'WorkingDirectory=' + str(CADDY / 'src')]
    command = ['systemd-run', '--quiet', '--collect', '--wait', '--pipe',
               '--unit=caddy-preparation-recheck-' + stamp.lower()]
    for value in props:
        command += ['-p', value]
    environment = {'PATH': str(CADDY / 'go/bin') + ':/usr/bin:/bin', 'HOME': str(fixture),
        'GOROOT': str(CADDY / 'go'), 'GOPATH': str(CADDY / 'gopath'), 'GOCACHE': str(CADDY / 'cache'),
        'GOTOOLCHAIN': 'local', 'GOPROXY': 'off', 'GOSUMDB': 'off', 'GOMAXPROCS': '1',
        'GOMEMLIMIT': '512MiB', 'CGO_ENABLED': '0', 'GOFLAGS': '-p=1 -mod=readonly',
        'XDG_CONFIG_HOME': str(fixture / 'config'), 'XDG_DATA_HOME': str(fixture / 'data'),
        'XDG_CACHE_HOME': str(fixture / 'cache')}
    command += ['/usr/bin/env', '-i', *[k + '=' + v for k, v in environment.items()],
                str(CADDY / 'go/bin/go'), 'run', str(source), str(CADDY / 'bin/caddy'), str(fixture)]
    proc = subprocess.run(command, capture_output=True, text=True, timeout=195)
    (fixture / 'runner.stdout').write_text(proc.stdout)
    (fixture / 'runner.stderr').write_text(proc.stderr)
    assert proc.returncode == 0, 'Caddy fixture failed; inspect new private staging logs'
    report['caddy_fixture'] = json.loads(proc.stdout)
    report['caddy_fixture']['private_network'] = True
    report['caddy_fixture']['cpu_quota'] = '50%'
    report['caddy_fixture']['memory_max'] = '768M'
    assert report['caddy_fixture']['success']

    manifest = json.loads((IMAGE / 'manifest.json').read_text())
    for name, checksum in manifest['artifacts'].items():
        assert digest(IMAGE / name) == checksum, 'Image sealed artifact mismatch: ' + name
    candidate = 'sha256:cd4677302c525c03f02fefe65da2944ec07c6d4bb52aa0bf611a54dc504e71d1'
    baseline = 'sha256:9d9274de90e73ba2e215935f0dfbd09eb5c2fe248ba7a6b3052e45969de496fb'
    assert manifest['candidate_image_id'] == candidate
    assert call(['docker', 'image', 'inspect', '--format', '{{.Id}}', manifest['candidate_tag']]).strip() == candidate
    assert call(['docker', 'image', 'inspect', '--format', '{{.Id}}', manifest['production_tag']]).strip() == baseline
    report['image_artifact'] = {'candidate_id': candidate, 'production_id': baseline,
        'sealed_manifest_artifacts_verified': len(manifest['artifacts']), 'codex_unchanged': manifest['codex_unchanged']}
    proc = subprocess.run(['docker', 'run', '--rm', '--network', 'none', '--user', '1015:1018',
        '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
        '--security-opt', 'seccomp=/usr/local/libexec/gpt2-codex-seccomp.json',
        '--memory', '768m', '--memory-swap', '768m', '--cpus', '0.5', '--pids-limit', '96',
        '--tmpfs', '/tmp:rw,nosuid,nodev,size=128m',
        '--tmpfs', '/probe-home:rw,nosuid,nodev,size=32m,uid=1015,gid=1018',
        '--entrypoint', 'python3', candidate, '-c', PROBE], capture_output=True, text=True, timeout=75)
    assert proc.returncode == 0, 'Candidate sandbox probe failed'
    report['image_probe'] = json.loads(proc.stdout)
    expected_schema = json.loads((IMAGE / 'probe-results-v3.json').read_text())['probes']['baseline']['schema']
    report['image_probe']['schema_matches_baseline'] = report['image_probe']['schema'] == expected_schema
    assert report['image_probe']['passed'] and report['image_probe']['schema_matches_baseline']
    assert call(['docker', 'image', 'inspect', '--format', '{{.Id}}', manifest['production_tag']]).strip() == baseline
    report['previous_reports_and_policy_unchanged'] = all(digest(p) == value for p, value in saved_hashes.items())
    report['production_files_unchanged'] = all(digest(p) == value for p, value in live_hashes.items())
    report['production_units_after'] = units()
    report['production_units_unchanged'] = report['production_units_before'] == report['production_units_after']
    assert report['previous_reports_and_policy_unchanged'] and report['production_files_unchanged'] and report['production_units_unchanged']
    report['passed'] = True
    report['scope'] = 'Preparation only; no production restart/reload/promotion, real provider request or email'
    (fixture / 'recheck-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
