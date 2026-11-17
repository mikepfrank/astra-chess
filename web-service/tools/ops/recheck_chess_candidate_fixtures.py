"""Rerun sealed final-path chess candidates without production state or network.

Operator-only preparation helper for the November 2026 maintenance. Run as root
on the reviewed host. Creates uniquely named disposable source copies/results;
never changes an active service, runtime, gate, source checkout or credential.
"""
from pathlib import Path
import datetime
import hashlib
import json
import os
import pwd
import re
import shutil
import subprocess
import tempfile
import tarfile
import time

STAGE = Path('/home/ec2-user/chess-security-stage-20261115/python')
EXPECTED = {'astra': (282, 3), 'or-chess': (594, 3)}
SERVICES = ('astra-chess.service', 'or-chess.service', 'gpt2-public.service',
            'gpt2-codex.service', 'astra-caddy.service')


def identities():
    result = {}
    for unit in SERVICES:
        text = subprocess.check_output(['systemctl', 'show', unit, '-p', 'MainPID',
            '-p', 'NRestarts', '-p', 'ActiveState'], text=True)
        result[unit] = dict(line.split('=', 1) for line in text.splitlines())
        assert result[unit]['ActiveState'] == 'active', unit
    return result


def main():
    assert os.geteuid() == 0
    started = datetime.datetime.now(datetime.timezone.utc).isoformat()
    before = identities()
    base = Path(tempfile.mkdtemp(prefix='chess-security-fixtures-20261117-', dir='/var/tmp'))
    base.chmod(0o755)
    records = []
    for owner, (expected_count, expected_skips) in EXPECTED.items():
        account = pwd.getpwnam(owner)
        runtime_root = Path('/home') / owner / '.local/share' / (owner + '-runtime' if owner == 'or-chess' else 'astra-chess-runtime')
        venv = runtime_root / 'venvs/security-20261115'
        runtime = runtime_root / 'python/cpython-3.12.16-linux-x86_64-gnu'
        source = base / ('source-' + owner)
        shutil.copytree(STAGE / ('source-' + owner), source,
                        symlinks=True, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        for current, dirs, files in os.walk(source):
            for path in [Path(current), *[Path(current) / name for name in files + dirs]]:
                os.chown(path, account.pw_uid, account.pw_gid, follow_symlinks=False)
        archive_path = STAGE / 'downloads' / (owner + '-source.tar')
        source_files = 0
        with tarfile.open(archive_path) as archive:
            for member in archive:
                path = source / member.name
                assert path.resolve().is_relative_to(source.resolve())
                if member.isfile():
                    assert hashlib.sha256(path.read_bytes()).digest() == hashlib.sha256(archive.extractfile(member).read()).digest(), member.name
                    source_files += 1
                elif member.issym():
                    assert path.is_symlink() and os.readlink(path) == member.linkname
        python = venv / 'bin/python'
        assert python.resolve().is_relative_to(runtime)
        probe = '''import os,sys,json,tempfile,unittest,pathlib,ssl
assert os.getuid()==EXPECTED_UID
assert not any(k in os.environ for k in ['OPENAI_API_KEY','OPENROUTER_API_KEY','AWS_ACCESS_KEY_ID','SMTP_PASSWORD'])
assert all(not os.access(p,os.R_OK) for p in ['/home/astra/.config/astra-chess/service.env','/home/or-chess/.config/or-chess/service.env','/home/ec2-user/.ssh','/home/gpt-2/.local/share/gpt2-codex','/etc/gpt2-codex.env'])
with tempfile.TemporaryDirectory(prefix='chess-fixture-home-') as home:
 os.environ['HOME']=home
 print(json.dumps({'uid':os.getuid(),'python':sys.version.split()[0],'openssl':ssl.OPENSSL_VERSION,'production_state_unreadable':True,'credentials_absent':True}),flush=True)
 suite=unittest.defaultTestLoader.discover('tests')
 result=unittest.TextTestRunner(verbosity=2).run(suite)
 raise SystemExit(0 if result.wasSuccessful() else 1)
'''.replace('EXPECTED_UID', str(account.pw_uid))
        unit = 'chess-candidate-fixtures-' + owner + '-' + base.name.rsplit('-', 1)[-1]
        command = ['systemd-run', '--quiet', '--collect', '--wait', '--pipe', '--unit=' + unit]
        props = ['User=' + owner, 'Group=' + owner, 'PrivateNetwork=yes', 'PrivateTmp=yes',
                 'NoNewPrivileges=yes', 'ProtectSystem=strict', 'ProtectHome=tmpfs',
                 'CPUQuota=50%', 'MemoryMax=2G', 'TasksMax=128', 'Nice=10',
                 'RuntimeMaxSec=600', 'InaccessiblePaths=-/etc/gpt2-codex.env',
                 'BindReadOnlyPaths=' + str(source), 'BindReadOnlyPaths=' + str(venv),
                 'BindReadOnlyPaths=' + str(runtime), 'WorkingDirectory=' + str(source / 'web-service')]
        for prop in props:
            command.extend(['--property', prop])
        command.extend(['/usr/bin/env', '-i', 'PATH=/usr/bin:/bin', 'LANG=C.UTF-8',
                        'PYTHONDONTWRITEBYTECODE=1', 'PYTHONUNBUFFERED=1',
                        str(python), '-B', '-c', probe])
        print(json.dumps({'starting': owner, 'directory': str(base), 'unit': unit}), flush=True)
        start = time.monotonic()
        p = subprocess.run(command, text=True, capture_output=True, timeout=640)
        log = p.stdout + '\n' + p.stderr
        path = base / ('fixtures-' + owner + '.log')
        path.write_text(log); path.chmod(0o600)
        count = re.search(r'Ran (\d+) tests? in ', log)
        status = [line for line in log.splitlines() if re.match(r'^(Ran \d+ tests|OK|FAILED)', line)]
        skip_lines = [line for line in log.splitlines() if " ... skipped " in line]
        passed = (p.returncode == 0 and count and int(count.group(1)) == expected_count
                  and len(skip_lines) == expected_skips)
        record = {'user': owner, 'returncode': p.returncode, 'seconds': round(time.monotonic()-start, 2),
                  'candidate': str(venv), 'source_revision': json.loads((STAGE / ('venv-'+owner+'-manifest.json')).read_text())['source_revision'],
                  'source_files_matching_retained_git_archive': source_files,
                  'source_archive_sha256': hashlib.sha256(archive_path.read_bytes()).hexdigest(),
                  'status': status, 'skipped_tests': skip_lines, 'passed': bool(passed)}
        records.append(record)
        (base / 'results.json').write_text(json.dumps(records, indent=2) + '\n')
        (base / 'results.json').chmod(0o600)
        print(json.dumps(record), flush=True)
        if not passed:
            print(json.dumps({'failure_tail': log[-9000:]}), flush=True)
            break
    after = identities()
    report = {'started_utc': started, 'completed_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'remote_directory': str(base), 'scope': 'Isolated candidate fixtures, no live state/network/credentials/model requests',
              'limits': {'cpu_percent': 50, 'memory_gib': 2, 'tasks': 128, 'nice': 10, 'runtime_seconds': 600},
              'source_copies_read_only': True, 'services_before': before, 'services_after': after,
              'production_processes_unchanged': before == after, 'results': records,
              'passed': len(records) == 2 and all(r['passed'] for r in records) and before == after}
    (base / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    (base / 'report.json').chmod(0o600)
    print(json.dumps({'report': str(base / 'report.json'), 'passed': report['passed']}), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
