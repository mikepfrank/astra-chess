"""Plan and activate the canonical Arcturus domain on the reviewed Linux host.

Default mode saves a private backup, candidate and report, validates Caddy,
and checks the existing sites plus the new Host on Arcturus's loopback port.
Deploy the application's dual-host support before running this tool.

    sudo python3 tools/ops/activate_arcturus_domain.py
    sudo python3 tools/ops/activate_arcturus_domain.py --apply \\
        --expected-config-sha256 SHA256_FROM_PLAN

Apply only appends the apex proxy and HTTPS www redirect. The old Arcturus
hostname remains a working proxy so its host-only sessions remain usable.
Every original configuration byte and its bind-mounted inode are preserved.
Only the verified Caddy main process receives SIGUSR1; no service is restarted.
Both applications' process identities and the original routes must stay stable.

Backup and reports are root-private under /var/lib/arcturus-domain-activation.
Recoverable failures restore the original bytes and verify the original routes.
Unknown concurrent edits are never overwritten. SIGKILL, machine loss or disk
failure may require manual recovery from the saved original.Caddyfile.
"""

import argparse
import http.client
import json
import os
from pathlib import Path
import re
import signal
import stat
import sys
import tempfile
import time


APP_ROOT = Path(__file__).resolve().parents[2]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))
from tools.ops import activate_arcturus_caddy as common


ActivationError = common.ActivationError
HOST = 'arcturuschess.com'
WWW = 'www.' + HOST
OLD_HOST = common.HOST
ARCTURUS_UNIT = 'or-chess.service'
AUDIT_ROOT = Path('/var/lib/arcturus-domain-activation')
BLOCK = (b'\narcturuschess.com {\n    reverse_proxy 127.0.0.1:8792\n}\n'
         b'\nwww.arcturuschess.com {\n    redir https://arcturuschess.com{uri} 308\n}\n')


def candidate_bytes(original):
    if not original or len(original) + len(BLOCK) > common.LIMIT or b'\0' in original:
        raise ActivationError('Original configuration is empty, oversized or invalid.')
    try:
        decoded = original.decode('utf-8')
    except UnicodeError:
        raise ActivationError('Original configuration is not UTF-8.') from None
    if HOST in decoded:
        raise ActivationError('The new domain already appears; review its configuration manually.')
    if re.search(r'^\s*import\s', decoded, re.MULTILINE):
        raise ActivationError('Imported configuration requires a separate deployment review.')
    if any(name not in decoded for name in (common.APEX, 'www.' + common.APEX, OLD_HOST)):
        raise ActivationError('Expected original Astra and Arcturus site names were not found.')
    return original + BLOCK


def existing_sites():
    return {'astra': common.original_sites(), 'arcturus': common.site_snapshot(OLD_HOST)}


def preflight_routes():
    baseline = existing_sites()
    experimental = common.site_snapshot(HOST, port=8792)
    identity = experimental['config']
    if (identity.get('player_name') != 'Arcturus' or identity.get('persona_id') != 'arcturus'
            or identity.get('model') != 'z-ai/glm-5.3-flash:nitro'):
        raise ActivationError('The new Host loopback service has an unexpected identity.')
    if experimental != baseline['arcturus']:
        raise ActivationError('The new Host loopback content differs from the existing Arcturus site.')
    return baseline, experimental


def canonical_site(experimental):
    if common.site_snapshot(HOST) != experimental:
        raise ActivationError('The canonical HTTPS site differs from its loopback preflight.')
    for path in ('/', '/games/route-check.html?check=domain&value=two'):
        status, location, _ = common.request(WWW, path)
        if status != 308 or location != 'https://' + HOST + path:
            raise ActivationError('The HTTPS www redirect did not preserve the canonical URI.')


def application_stamps():
    return {unit: common.process_stamp(common.active_pid(unit))
            for unit in (common.ASTRA_UNIT, ARCTURUS_UNIT)}


def stable_processes(original_stat, caddy_before, applications_before):
    if common.caddy_identity(original_stat) != caddy_before:
        raise ActivationError('Caddy main process changed during activation.')
    if application_stamps() != applications_before:
        raise ActivationError('An application process changed during activation.')


def await_verified_routes(check, *, seconds=180):
    """Allow initial certificate issuance without flooding application routes."""
    deadline = time.monotonic() + seconds
    while True:
        try:
            check()
            return
        except (OSError, ValueError, http.client.HTTPException, ActivationError):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ActivationError('Route verification did not pass within the reload window.') from None
            time.sleep(min(2, remaining))
            if time.monotonic() >= deadline:
                raise ActivationError('Route verification did not pass within the reload window.') from None


def activate(descriptor, original_stat, original, candidate, caddy_before,
             applications_before, baseline, experimental, report):
    common.check_file_identity(descriptor, original_stat)
    if common.read_fd(descriptor) != original:
        raise ActivationError('Configuration changed after preflight.')
    stable_processes(original_stat, caddy_before, applications_before)
    # Refresh route evidence immediately before the first write as well.
    if existing_sites() != baseline:
        raise ActivationError('An existing site changed after preflight.')
    writing_started = False
    write_finished = False
    try:
        writing_started = True
        common.rewrite(descriptor, candidate)
        write_finished = True
        common.signal_caddy(original_stat, expected=caddy_before)

        def check():
            common.check_file_identity(descriptor, original_stat)
            if common.read_fd(descriptor) != candidate:
                raise ActivationError('Configuration changed during route verification.')
            stable_processes(original_stat, caddy_before, applications_before)
            if existing_sites() != baseline:
                raise ActivationError('An existing Astra or Arcturus route changed.')
            canonical_site(experimental)

        await_verified_routes(check)
        report.update(applied=True, caddy_pid_stable=True, astra_pid_stable=True,
                      arcturus_pid_stable=True, routes_verified=True,
                      old_arcturus_preserved=True, www_redirect_verified=True,
                      same_config_inode=True)
    except BaseException:
        if writing_started:
            try:
                common.check_file_identity(descriptor, original_stat)
                current = common.read_fd(descriptor)
                if current not in (candidate, original):
                    if (write_finished or len(current) < len(original)
                            or not candidate.startswith(current)):
                        raise ActivationError('Unexpected concurrent bytes require manual recovery.')
                common.rewrite(descriptor, original)
                common.signal_caddy(original_stat, expected=caddy_before)

                def recovered():
                    common.check_file_identity(descriptor, original_stat)
                    if common.read_fd(descriptor) != original:
                        raise ActivationError('Rollback bytes changed during verification.')
                    stable_processes(original_stat, caddy_before, applications_before)
                    if existing_sites() != baseline:
                        raise ActivationError('Original Astra and Arcturus routes have not recovered.')

                await_verified_routes(recovered, seconds=20)
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
              'audit_directory': str(audit), 'hostname': HOST, 'retained_hostname': OLD_HOST}
    descriptor = None
    try:
        descriptor = os.open(common.CONFIG, (os.O_RDWR if args.apply else os.O_RDONLY) | os.O_NOFOLLOW)
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        original_stat = os.fstat(descriptor)
        if not stat.S_ISREG(original_stat.st_mode):
            raise ActivationError('Configuration must be an existing regular file.')
        common.check_file_identity(descriptor, original_stat)
        original = common.read_fd(descriptor)
        candidate = candidate_bytes(original)
        original_sha256 = common.digest(original)
        report.update(original_sha256=original_sha256, candidate_sha256=common.digest(candidate))
        if args.apply and args.expected_config_sha256 != original_sha256:
            raise ActivationError('Current configuration differs from the reviewed plan hash.')
        common.private_file(audit / 'original.Caddyfile', original)
        common.private_file(audit / 'candidate.Caddyfile', candidate)
        directory_fd = os.open(audit, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        environment = {'PATH': '/usr/bin:/bin', 'HOME': str(audit),
                       'XDG_DATA_HOME': str(audit / 'data'),
                       'XDG_CONFIG_HOME': str(audit / 'config')}
        version = common.run([str(common.BINARY), 'version'], env=environment).decode().strip()
        if not version.startswith('v2.11.4 '):
            raise ActivationError('This activation was reviewed for Caddy v2.11.4 only.')
        report['caddy_version'] = version
        validation = common.run([str(common.BINARY), 'validate', '--config',
                                 str(audit / 'candidate.Caddyfile'), '--adapter', 'caddyfile'],
                                cwd=common.CONFIG.parent, env=environment)
        common.private_file(audit / 'validation.stdout', validation)
        caddy_before = common.caddy_identity(original_stat)
        applications_before = application_stamps()
        baseline, experimental = preflight_routes()
        stable_processes(original_stat, caddy_before, applications_before)
        common.check_file_identity(descriptor, original_stat)
        if common.read_fd(descriptor) != original:
            raise ActivationError('Configuration changed during preflight.')
        report.update(candidate_validated=True, loopback_verified=True,
                      original_routes_verified=True, caddy_pid=caddy_before[0],
                      astra_pid=applications_before[common.ASTRA_UNIT][0],
                      arcturus_pid=applications_before[ARCTURUS_UNIT][0],
                      original_bytes_preserved=True, new_host_matches_old_arcturus=True)
        if args.apply:
            activate(descriptor, original_stat, original, candidate, caddy_before,
                     applications_before, baseline, experimental, report)
        report['success'] = True
    except BaseException as error:
        report['error_type'] = type(error).__name__
        if isinstance(error, ActivationError):
            report['error'] = str(error)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        common.private_file(audit / 'report.json', (json.dumps(report, indent=2) + '\n').encode())
        print(json.dumps(report, indent=2))
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
