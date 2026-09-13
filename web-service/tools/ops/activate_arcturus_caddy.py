"""Plan, then explicitly activate the separate Arcturus Caddy hostname on Linux.

Run as root on the reviewed host. The default only saves a private candidate,
backup and report, validates Caddy, and performs read-only HTTP checks. Apply
requires the original SHA-256 printed by that plan. This tool never starts,
stops or restarts a service, accesses a game database, or starts a model turn.

    sudo python3 tools/ops/activate_arcturus_caddy.py
    sudo python3 tools/ops/activate_arcturus_caddy.py --apply \\
        --expected-config-sha256 SHA256_FROM_PLAN

The installed unit bind-mounts an individual config file: writes and rollback
MUST retain that inode. SIGUSR1 reload with admin off was verified separately
against the installed Caddy 2.11.4 binary in a disposable loopback fixture.
References: https://caddyserver.com/docs/command-line#signals and
https://caddyserver.com/docs/running . DNS must already reach this host.

Reports/backup are root-private under /var/lib/astra-caddy-activation. A failure
after writing restores the original bytes and signals only the verified Caddy
main process, then checks the original sites. Unrelated concurrent edits are
never overwritten. SIGKILL, machine loss or disk failure cannot be recovered
automatically; the private original.Caddyfile remains the recovery source.
"""

import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import signal
import socket
import ssl
import stat
import subprocess
import sys
import tempfile
import time


CONFIG = Path('/home/astra/.config/astra-chess/Caddyfile')
BINARY = Path('/home/astra/.local/bin/caddy')
AUDIT_ROOT = Path('/var/lib/astra-caddy-activation')
CADDY_UNIT = 'astra-caddy.service'
ASTRA_UNIT = 'astra-chess.service'
HOST = 'arcturus.astraplayschess.com'
APEX = 'astraplayschess.com'
BLOCK = b'\narcturus.astraplayschess.com {\n    reverse_proxy 127.0.0.1:8792\n}\n'
LIMIT = 1024 * 1024


class ActivationError(RuntimeError):
    """A safe, operator-readable failure without command output or secrets."""


def digest(data):
    return hashlib.sha256(data).hexdigest()


def candidate_bytes(original):
    if not original or len(original) > LIMIT or b'\x00' in original:
        raise ActivationError('Original configuration is empty, oversized or invalid.')
    try:
        decoded = original.decode('utf-8')
    except UnicodeError:
        raise ActivationError('Original configuration is not UTF-8.') from None
    if HOST in decoded:
        raise ActivationError('Arcturus already appears in the configuration; review manually.')
    if re.search(r'^\s*import\s', decoded, re.MULTILINE):
        raise ActivationError('Imported configuration requires a separate deployment review.')
    if APEX not in decoded or ('www.' + APEX) not in decoded:
        raise ActivationError('Expected original site names were not found.')
    # Preserve every existing byte, including its original newline convention.
    return original + BLOCK


def run(command, *, cwd=None, env=None):
    try:
        result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, timeout=12)
    except (OSError, subprocess.TimeoutExpired):
        raise ActivationError('A bounded operator subprocess could not complete.') from None
    if result.returncode:
        raise ActivationError('An operator subprocess failed; configuration was not accepted.')
    return result.stdout


def active_pid(unit):
    output = run(['systemctl', 'show', unit, '--property=MainPID',
                  '--property=ActiveState', '--property=SubState']).decode('ascii')
    data = dict(line.split('=', 1) for line in output.splitlines() if '=' in line)
    if data.get('ActiveState') != 'active' or data.get('SubState') != 'running':
        raise ActivationError('A required service is not active and running: ' + unit)
    pid = int(data.get('MainPID', '0'))
    if pid <= 1:
        raise ActivationError('Required service has no valid main process.')
    return pid


def process_stamp(pid):
    # /proc stat field 22; the command field may itself contain spaces or ')'.
    raw = Path('/proc/%d/stat' % pid).read_text()
    return pid, raw.rsplit(')', 1)[1].split()[19]


def caddy_identity(config_stat):
    pid = active_pid(CADDY_UNIT)
    stamp = process_stamp(pid)
    command = Path('/proc/%d/cmdline' % pid).read_bytes().rstrip(b'\0').split(b'\0')
    expected = [os.fsencode(BINARY), b'run', b'--config', os.fsencode(CONFIG),
                b'--adapter', b'caddyfile']
    if command != expected or not os.path.samefile('/proc/%d/exe' % pid, BINARY):
        raise ActivationError('Caddy main process does not match the reviewed command.')
    mounted = Path('/proc/%d/root' % pid) / CONFIG.relative_to('/')
    mounted_stat = mounted.stat()
    if (mounted_stat.st_dev, mounted_stat.st_ino) != (config_stat.st_dev, config_stat.st_ino):
        raise ActivationError('Caddy does not see the same mounted configuration inode.')
    return stamp


def signal_caddy(config_stat, *, expected=None):
    stamp = caddy_identity(config_stat)
    if expected is not None and stamp != expected:
        raise ActivationError('Caddy main process changed before the signal.')
    descriptor = os.pidfd_open(stamp[0])
    try:
        if caddy_identity(config_stat) != stamp:
            raise ActivationError('Caddy process changed while pinning its identity.')
        signal.pidfd_send_signal(descriptor, signal.SIGUSR1)
    finally:
        os.close(descriptor)


class LocalTLSConnection(http.client.HTTPSConnection):
    """Connect to loopback while retaining the actual host for TLS verification."""

    def connect(self):
        raw = socket.create_connection(('127.0.0.1', 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def request(host, path, *, port=None):
    connection = (LocalTLSConnection(host, timeout=2, context=ssl.create_default_context())
                  if port is None else http.client.HTTPConnection('127.0.0.1', port, timeout=2))
    try:
        connection.request('GET', path, headers={'Host': host, 'Connection': 'close',
                                               'X-Forwarded-Proto': 'https'})
        response = connection.getresponse()
        body = response.read(LIMIT + 1)
        if len(body) > LIMIT:
            raise ActivationError('A read-only route returned an oversized response.')
        return response.status, response.getheader('Location'), body
    finally:
        connection.close()


def site_snapshot(host, *, port=None):
    health = request(host, '/health', port=port)
    config = request(host, '/api/config', port=port)
    index = request(host, '/', port=port)
    if health[0] != 200 or json.loads(health[2]) != {'ok': True}:
        raise ActivationError('A required health route did not pass.')
    if config[0] != 200 or not isinstance(json.loads(config[2]), dict):
        raise ActivationError('A required public configuration route did not pass.')
    if index[0] != 200 or b'<html' not in index[2].lower():
        raise ActivationError('A required index route did not pass.')
    return {'config': json.loads(config[2]), 'index_sha256': digest(index[2])}


def original_sites():
    result = site_snapshot(APEX)
    redirect = request('www.' + APEX, '/')
    if redirect[0] not in (301, 308) or redirect[1] != 'https://' + APEX + '/':
        raise ActivationError('The existing www redirect did not pass.')
    result['www_redirect'] = [redirect[0], redirect[1]]
    return result


def private_file(path, data):
    with open(path, 'xb') as output:
        os.chmod(path, 0o600)
        output.write(data)
        output.flush()
        os.fsync(output.fileno())


def read_fd(descriptor):
    os.lseek(descriptor, 0, os.SEEK_SET)
    data = bytearray()
    while chunk := os.read(descriptor, LIMIT + 1 - len(data)):
        data.extend(chunk)
        if len(data) > LIMIT:
            raise ActivationError('Configuration exceeds the bounded read limit.')
    return bytes(data)


def check_file_identity(descriptor, original_stat):
    current = CONFIG.lstat()
    actual = os.fstat(descriptor)
    expected = (original_stat.st_dev, original_stat.st_ino,
                original_stat.st_uid, original_stat.st_gid, original_stat.st_mode)
    for value in (current, actual):
        if (value.st_dev, value.st_ino, value.st_uid, value.st_gid, value.st_mode) != expected:
            raise ActivationError('Configuration inode, ownership or permissions changed.')


def rewrite(descriptor, data):
    os.lseek(descriptor, 0, os.SEEK_SET)
    view = memoryview(data)
    while view:
        count = os.write(descriptor, view)
        if count <= 0:
            raise ActivationError('Configuration write could not progress.')
        view = view[count:]
    os.ftruncate(descriptor, len(data))
    os.fsync(descriptor)
    if read_fd(descriptor) != data:
        raise ActivationError('Configuration write did not verify.')


def await_routes(check, *, seconds=35):
    deadline = time.monotonic() + seconds
    while True:
        try:
            check()
            return
        except (OSError, ValueError, http.client.HTTPException, ActivationError):
            if time.monotonic() >= deadline:
                raise ActivationError('Route verification did not pass within the reload window.') from None
            time.sleep(.5)


def activate(descriptor, original_stat, original, candidate, caddy_before,
             astra_before, baseline, experimental, report):
    check_file_identity(descriptor, original_stat)
    if read_fd(descriptor) != original or caddy_identity(original_stat) != caddy_before:
        raise ActivationError('Configuration or Caddy changed after preflight.')
    if process_stamp(active_pid(ASTRA_UNIT)) != astra_before:
        raise ActivationError('Astra application process changed after preflight.')
    writing_started = False
    write_finished = False
    try:
        writing_started = True
        rewrite(descriptor, candidate)
        write_finished = True
        signal_caddy(original_stat, expected=caddy_before)

        def check():
            check_file_identity(descriptor, original_stat)
            if read_fd(descriptor) != candidate:
                raise ActivationError('Configuration changed during route verification.')
            if caddy_identity(original_stat) != caddy_before:
                raise ActivationError('Caddy restarted during activation.')
            if process_stamp(active_pid(ASTRA_UNIT)) != astra_before:
                raise ActivationError('Astra application process changed during activation.')
            if original_sites() != baseline or site_snapshot(HOST) != experimental:
                raise ActivationError('Existing or experimental routes differ from preflight.')

        await_routes(check)
        report.update(applied=True, caddy_pid_stable=True, astra_pid_stable=True,
                      routes_verified=True, same_config_inode=True)
    except BaseException:
        if writing_started:
            try:
                # A partial write from this transaction also needs recovery. An
                # unknown external edit must not be overwritten by rollback.
                check_file_identity(descriptor, original_stat)
                current = read_fd(descriptor)
                if current not in (candidate, original):
                    if (write_finished or len(current) < len(original)
                            or not candidate.startswith(current)):
                        raise ActivationError('Unexpected concurrent bytes require manual recovery.')
                rewrite(descriptor, original)
                signal_caddy(original_stat)

                def recovered():
                    if original_sites() != baseline:
                        raise ActivationError('Original routes have not recovered.')
                    check_file_identity(descriptor, original_stat)
                    if read_fd(descriptor) != original:
                        raise ActivationError('Rollback bytes changed during verification.')

                await_routes(recovered, seconds=20)
                report['rollback'] = 'original bytes restored, signal sent, original routes verified'
            except BaseException as error:
                report['rollback'] = 'manual recovery required from private original.Caddyfile'
                report['rollback_error_type'] = type(error).__name__
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--expected-config-sha256')
    args = parser.parse_args()
    if args.apply and not re.fullmatch(r'[0-9a-f]{64}', args.expected_config_sha256 or ''):
        parser.error('--apply requires the exact original SHA-256 from the reviewed plan')
    if sys.platform != 'linux' or os.geteuid() != 0:
        parser.error('Run on the reviewed Linux host as root; no local changes were made')
    if not hasattr(os, 'pidfd_open') or not hasattr(signal, 'pidfd_send_signal'):
        parser.error('Linux Python with pidfd signal support is required')
    import fcntl

    os.umask(0o077)
    def interrupted(signum, frame):
        raise InterruptedError('Operator process interrupted.')
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGHUP, interrupted)
    AUDIT_ROOT.mkdir(mode=0o700, exist_ok=True)
    root_stat = AUDIT_ROOT.lstat()
    if not stat.S_ISDIR(root_stat.st_mode) or root_stat.st_uid != 0 or root_stat.st_mode & 0o077:
        raise ActivationError('Audit directory must be a private root-owned directory.')
    audit = Path(tempfile.mkdtemp(prefix='activation-', dir=AUDIT_ROOT))
    report = {'mode': 'apply' if args.apply else 'plan', 'success': False,
              'audit_directory': str(audit), 'hostname': HOST}
    descriptor = None
    try:
        descriptor = os.open(CONFIG, (os.O_RDWR if args.apply else os.O_RDONLY) | os.O_NOFOLLOW)
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        original_stat = os.fstat(descriptor)
        if not stat.S_ISREG(original_stat.st_mode):
            raise ActivationError('Configuration must be an existing regular file.')
        check_file_identity(descriptor, original_stat)
        original = read_fd(descriptor)
        candidate = candidate_bytes(original)
        report.update(original_sha256=digest(original), candidate_sha256=digest(candidate))
        if args.apply and args.expected_config_sha256 != digest(original):
            raise ActivationError('Current configuration differs from the reviewed plan hash.')
        private_file(audit / 'original.Caddyfile', original)
        private_file(audit / 'candidate.Caddyfile', candidate)
        directory_fd = os.open(audit, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        environment = {'PATH': '/usr/bin:/bin', 'HOME': str(audit),
                       'XDG_DATA_HOME': str(audit / 'data'),
                       'XDG_CONFIG_HOME': str(audit / 'config')}
        version = run([str(BINARY), 'version'], env=environment).decode().strip()
        if not version.startswith('v2.11.4 '):
            raise ActivationError('This activation was reviewed for Caddy v2.11.4 only.')
        report['caddy_version'] = version
        validation = run([str(BINARY), 'validate', '--config', str(audit / 'candidate.Caddyfile'),
                          '--adapter', 'caddyfile'], cwd=CONFIG.parent, env=environment)
        private_file(audit / 'validation.stdout', validation)
        caddy_before = caddy_identity(original_stat)
        astra_before = process_stamp(active_pid(ASTRA_UNIT))
        baseline = original_sites()
        # TrustedHostMiddleware requires this host, even on the loopback port.
        experimental = site_snapshot(HOST, port=8792)
        identity = experimental['config']
        if (identity.get('player_name') != 'Arcturus' or identity.get('persona_id') != 'arcturus'
                or identity.get('model') != 'z-ai/glm-5.3-flash:nitro'):
            raise ActivationError('Experimental loopback service has an unexpected identity.')
        report.update(candidate_validated=True, loopback_verified=True,
                      original_routes_verified=True, caddy_pid=caddy_before[0],
                      astra_pid=astra_before[0], original_bytes_preserved=True)
        if args.apply:
            activate(descriptor, original_stat, original, candidate, caddy_before,
                     astra_before, baseline, experimental, report)
        report['success'] = True
    except BaseException as error:
        report['error_type'] = type(error).__name__
        if isinstance(error, ActivationError):
            report['error'] = str(error)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        private_file(audit / 'report.json', (json.dumps(report, indent=2) + '\n').encode())
        print(json.dumps(report, indent=2))
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
