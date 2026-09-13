"""Audit Caddy SIGUSR1 reload in a private, disposable Lightsail fixture.

This copies the installed binary, then runs only that copy as or-chess on a
fresh loopback port. No real proxy configuration, process or service is changed.
The only signals target the fixture child. Requires the operator's SSH/sudo
authorization and preserves a sanitized local report plus private remote logs.
"""
import argparse
import json
from pathlib import Path
import subprocess


REMOTE = r'''
import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import signal
import socket
import subprocess
import tempfile
import time
import urllib.request

account = pwd.getpwnam('or-chess')
home = Path(account.pw_dir).resolve()
if home != Path('/home/or-chess'):
    raise RuntimeError('Unexpected fixture account home')
cache = home / '.cache'
cache.mkdir(mode=0o700, exist_ok=True)
if not cache.resolve().is_relative_to(home):
    raise RuntimeError('Fixture cache escaped target account')
os.chown(cache, account.pw_uid, account.pw_gid)
fixture = Path(tempfile.mkdtemp(prefix='caddy-signal-audit-', dir=cache)).resolve()
os.chown(fixture, account.pw_uid, account.pw_gid)
source = Path('/home/astra/.local/bin/caddy')
source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
binary = fixture / 'caddy'
shutil.copyfile(source, binary)
binary.chmod(0o700)
os.chown(binary, account.pw_uid, account.pw_gid)
for name in ('home', 'config', 'data', 'cache'):
    folder = fixture / name
    folder.mkdir(mode=0o700)
    os.chown(folder, account.pw_uid, account.pw_gid)
environment = {'PATH': '/usr/bin:/bin', 'HOME': str(fixture / 'home'),
    'USER': 'or-chess', 'LOGNAME': 'or-chess',
    'XDG_CONFIG_HOME': str(fixture / 'config'),
    'XDG_DATA_HOME': str(fixture / 'data'), 'XDG_CACHE_HOME': str(fixture / 'cache')}
identity = {'user': account.pw_uid, 'group': account.pw_gid, 'extra_groups': []}
version = subprocess.run([str(binary), 'version'], cwd=fixture, env=environment,
    capture_output=True, check=True, timeout=10, **identity).stdout.decode().strip()
if not version.startswith('v2.11.4 '):
    raise RuntimeError('This audit requires installed Caddy v2.11.4')
with socket.socket() as candidate:
    candidate.bind(('127.0.0.1', 0))
    port = candidate.getsockname()[1]
    if port < 20000:
        raise RuntimeError('The fixture port was not a high loopback port')
config = fixture / 'Caddyfile'
def rewrite(text):
    with config.open('w', encoding='utf-8') as output:
        output.write("""{
    admin off
    auto_https off
}

http://127.0.0.1:%d {
    respond "%s" 200
}
""" % (port, text))
        output.flush()
        os.fsync(output.fileno())
    config.chmod(0o600)
    os.chown(config, account.pw_uid, account.pw_gid)
rewrite('before')
inode = config.stat().st_ino
url = 'http://127.0.0.1:%d/' % port
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
report = {'caddy_version': version, 'fixture_directory': str(fixture),
    'listen_address': '127.0.0.1:%d' % port, 'admin_api': False,
    'automatic_https': False, 'source_sha256': source_hash,
    'pid_before': None, 'pid_after': None, 'before': None, 'after': None,
    'same_config_inode': False, 'fixture_terminated': False,
    'original_binary_unchanged': False, 'success': False}
process = None
log_path = fixture / 'caddy.log'
def wait_for(expected):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError('Fixture process exited before verification')
        try:
            with opener.open(url, timeout=1) as response:
                body = response.read(1024).decode()
                if response.status == 200 and body == expected:
                    return body
        except OSError:
            pass
        time.sleep(.1)
    raise RuntimeError('Fixture response verification timed out')
try:
    with log_path.open('wb') as log:
        os.chmod(log_path, 0o600)
        os.chown(log_path, account.pw_uid, account.pw_gid)
        process = subprocess.Popen([str(binary), 'run', '--config', str(config),
            '--adapter', 'caddyfile'], cwd=fixture, env=environment,
            stdout=log, stderr=subprocess.STDOUT, start_new_session=True, **identity)
        report['pid_before'] = process.pid
        report['before'] = wait_for('before')
        uid_line = next(line for line in Path('/proc/%d/status' % process.pid).read_text().splitlines()
                        if line.startswith('Uid:'))
        if any(int(value) != account.pw_uid for value in uid_line.split()[1:]):
            raise RuntimeError('Fixture did not run as or-chess')
        report['fixture_uid'] = account.pw_uid
        rewrite('after')
        report['same_config_inode'] = config.stat().st_ino == inode
        if not report['same_config_inode']:
            raise RuntimeError('The config inode changed')
        process.send_signal(signal.SIGUSR1)
        report['after'] = wait_for('after')
        report['pid_after'] = process.pid
        report['success'] = process.poll() is None and report['pid_before'] == report['pid_after']
except Exception as error:
    report['error_type'] = type(error).__name__
finally:
    if process is not None:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        report['fixture_terminated'] = process.poll() is not None
    report['original_binary_unchanged'] = hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
    report['success'] = bool(report['success'] and report['fixture_terminated'] and report['original_binary_unchanged'])
    report_path = fixture / 'audit.json'
    report_path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    report_path.chmod(0o600)
    os.chown(report_path, account.pw_uid, account.pw_gid)
    print(json.dumps(report))
raise SystemExit(0 if report['success'] else 1)
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ssh-target', default='lightsail')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = subprocess.run(['ssh', '-o', 'BatchMode=yes', args.ssh_target,
        'sudo', '-n', 'python3', '-'], input=REMOTE.encode(), capture_output=True, timeout=45)
    try:
        report = json.loads(result.stdout)
    except (ValueError, UnicodeError):
        print('Fixture audit failed before a report was available; SSH exit:', result.returncode)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
    return 0 if result.returncode == 0 and report.get('success') else 1


if __name__ == '__main__':
    raise SystemExit(main())
