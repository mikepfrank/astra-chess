"""Temporary Arcturus-only admission gate for a root-run Linux deployment.

This file has no executable main. Enter before the final idle check and leave
only after the experimental app has restarted (including rollback). Existing
requests must still drain after entry; the gate prevents new HTTP admission.
SIGTERM/SIGHUP raise through the caller's cleanup before this context restores
Caddy. SIGKILL/host loss still require the private original.Caddyfile backup.
"""
from contextlib import contextmanager
import importlib.util
import json
import os
from pathlib import Path
import signal
import stat
import sys
import tempfile


HOSTS = ('arcturuschess.com', 'arcturus.astraplayschess.com')
BODY = b'Brief Arcturus maintenance. Please retry shortly.'
RETRY_AFTER = '30'
AUDIT_ROOT = Path('/var/lib/arcturus-maintenance-gate')


def candidate_bytes(original):
    """Accept only the two inspected, separate, plain reverse-proxy blocks."""
    if not original or len(original) > 1024 * 1024 or b'\x00' in original:
        raise ValueError('Unexpected Caddy configuration size or encoding.')
    original.decode('utf-8')
    candidate = original
    for host in HOSTS:
        block = (host + ' {\n    reverse_proxy 127.0.0.1:8792\n}\n').encode()
        if candidate.count(block) != 1:
            raise ValueError('Expected separate Arcturus proxy block was not found exactly once.')
        gated = (host + ' {\n    header Retry-After "' + RETRY_AFTER + '"\n'
                 '    respond "' + BODY.decode() + '" 503\n}\n').encode()
        candidate = candidate.replace(block, gated, 1)
    return candidate


def _primitives():
    path = Path(__file__).resolve().with_name('activate_arcturus_caddy.py')
    spec = importlib.util.spec_from_file_location('reviewed_caddy_activation', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextmanager
def arcturus_maintenance_gate():
    """Yield an audit receipt; restore exact bytes/inode/PIDs before returning."""
    if sys.platform != 'linux' or os.geteuid() != 0:
        raise RuntimeError('The maintenance gate requires the reviewed Linux host and root.')
    if not hasattr(os, 'pidfd_open') or not hasattr(signal, 'pidfd_send_signal'):
        raise RuntimeError('Pidfd signal support is required.')
    import fcntl
    caddy = _primitives()
    AUDIT_ROOT.mkdir(mode=0o700, exist_ok=True)
    audit_stat = AUDIT_ROOT.lstat()
    if not stat.S_ISDIR(audit_stat.st_mode) or audit_stat.st_uid != 0 or audit_stat.st_mode & 0o077:
        raise RuntimeError('Gate audit directory must be private and root-owned.')
    audit = Path(tempfile.mkdtemp(prefix='gate-', dir=AUDIT_ROOT))
    report = {'audit_directory': str(audit), 'entered': False, 'restored': False}
    descriptor = None
    writing_started = write_finished = False
    handlers = {}
    try:
        descriptor = os.open(caddy.CONFIG, os.O_RDWR | os.O_NOFOLLOW)
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        original_stat = os.fstat(descriptor)
        if not stat.S_ISREG(original_stat.st_mode):
            raise RuntimeError('Caddy configuration is not a regular file.')
        caddy.check_file_identity(descriptor, original_stat)
        original = caddy.read_fd(descriptor)
        candidate = candidate_bytes(original)
        caddy.private_file(audit / 'original.Caddyfile', original)
        caddy.private_file(audit / 'candidate.Caddyfile', candidate)
        directory = os.open(audit, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        environment = {'PATH': '/usr/bin:/bin', 'HOME': str(audit),
                       'XDG_DATA_HOME': str(audit / 'data'),
                       'XDG_CONFIG_HOME': str(audit / 'config')}
        version = caddy.run([str(caddy.BINARY), 'version'], env=environment).decode().strip()
        if not version.startswith('v2.11.4 '):
            raise RuntimeError('Gate requires the reviewed Caddy v2.11.4 binary.')
        validation = caddy.run([str(caddy.BINARY), 'validate', '--config',
            str(audit / 'candidate.Caddyfile'), '--adapter', 'caddyfile'],
            cwd=caddy.CONFIG.parent, env=environment)
        caddy.private_file(audit / 'validation.stdout', validation)
        caddy_before = caddy.caddy_identity(original_stat)
        astra_before = caddy.process_stamp(caddy.active_pid(caddy.ASTRA_UNIT))
        original_sites = caddy.original_sites()

        def verify_identity(expected_bytes):
            caddy.check_file_identity(descriptor, original_stat)
            if caddy.read_fd(descriptor) != expected_bytes:
                raise caddy.ActivationError('Caddy configuration bytes changed unexpectedly.')
            if caddy.caddy_identity(original_stat) != caddy_before:
                raise caddy.ActivationError('Caddy process changed during maintenance.')
            if caddy.process_stamp(caddy.active_pid(caddy.ASTRA_UNIT)) != astra_before:
                raise caddy.ActivationError('Original Astra process changed during maintenance.')
            if caddy.original_sites() != original_sites:
                raise caddy.ActivationError('Original Astra routes changed during maintenance.')

        def verify_arcturus_health():
            for host in HOSTS:
                status, _, body = caddy.request(host, '/health')
                if status != 200 or json.loads(body) != {'ok': True}:
                    raise caddy.ActivationError('Arcturus health route is not ready.')

        verify_arcturus_health()
        verify_identity(original)
        report.update(original_sha256=caddy.digest(original),
            candidate_sha256=caddy.digest(candidate), caddy_pid=caddy_before[0],
            original_astra_pid=astra_before[0], original_config_inode=original_stat.st_ino)

        def interrupted(signum, frame):
            raise InterruptedError('Maintenance gate interrupted; restoring Caddy.')

        for signum in (signal.SIGTERM, signal.SIGHUP):
            handlers[signum] = signal.signal(signum, interrupted)
        writing_started = True
        caddy.rewrite(descriptor, candidate)
        write_finished = True
        caddy.signal_caddy(original_stat, expected=caddy_before)

        def verify_gated():
            verify_identity(candidate)
            for host in HOSTS:
                connection = caddy.LocalTLSConnection(host, timeout=2)
                try:
                    connection.request('GET', '/health', headers={'Host': host, 'Connection': 'close'})
                    response = connection.getresponse()
                    body = response.read(caddy.LIMIT + 1)
                    if (response.status != 503 or response.getheader('Retry-After') != RETRY_AFTER
                            or body != BODY):
                        raise caddy.ActivationError('Arcturus maintenance gate did not verify.')
                finally:
                    connection.close()

        caddy.await_routes(verify_gated)
        report['entered'] = True
        yield report
    finally:
        try:
            if writing_started:
                caddy.check_file_identity(descriptor, original_stat)
                current = caddy.read_fd(descriptor)
                if current not in (candidate, original):
                    if (write_finished or len(current) < len(original)
                            or not candidate.startswith(current)):
                        raise caddy.ActivationError('Concurrent Caddy bytes require manual recovery: ' + str(audit))
                caddy.rewrite(descriptor, original)
                caddy.signal_caddy(original_stat, expected=caddy_before)

                def verify_restored():
                    verify_identity(original)
                    verify_arcturus_health()

                caddy.await_routes(verify_restored, seconds=25)
                report['restored'] = True
        except BaseException as error:
            report['restore_error_type'] = type(error).__name__
            report['manual_recovery_source'] = str(audit / 'original.Caddyfile')
            raise
        finally:
            for signum, handler in handlers.items():
                signal.signal(signum, handler)
            if descriptor is not None:
                os.close(descriptor)
            caddy.private_file(audit / 'report.json', (json.dumps(report, indent=2) + '\n').encode())
