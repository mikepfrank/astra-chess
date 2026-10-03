#!/usr/bin/env python3
"""Drain/stop and restart this Lightsail Astra installation; never force a turn.

Run as root through ec2-user's existing sudo. Uses only the standard library;
application inventory and Caddy execute as astra, not root. See SERVICE-LIFECYCLE.md.
"""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import uuid


APP = 'astra-chess.service'
PROXY = 'astra-caddy.service'
TIMER = 'astra-game-notify.timer'
NOTIFIER = 'astra-game-notify.service'
DOMAIN = 'astraplayschess.com'
REPO = Path('/home/astra/astra-chess/web-service')
DATA = Path('/home/astra/.local/share/astra-chess')
CADDYFILE = Path('/home/astra/.config/astra-chess/Caddyfile')
CADDY = '/home/astra/.local/bin/caddy'
STATE_DIR = Path('/var/lib/astra-chess-ops')
STATE_FILE = STATE_DIR / 'maintenance.json'
CGROUP = Path('/sys/fs/cgroup')
CONFIG_LOCK = Path('/run/lock/astra-caddy-config.lock')
SYSTEMCTL = '/usr/bin/systemctl'
RUNUSER = '/usr/sbin/runuser'
CURL = '/usr/bin/curl'
STABLE_SECONDS = 30
POLL_SECONDS = 5
PROXY_READY_SECONDS = 30
PROXY_POLL_SECONDS = 0.5


class SafetyError(RuntimeError):
    pass


def log(message):
    print(message, flush=True)


def command(args, *, astra=False, timeout=60):
    if astra:
        args = [RUNUSER, '-u', 'astra', '--', *map(str, args)]
    result = subprocess.run(list(map(str, args)), capture_output=True, text=True,
                            timeout=timeout, check=False)
    if result.returncode:
        # Do not echo arbitrary tool output (Caddy config may contain secrets).
        detail = ' (could not connect to the HTTP/HTTPS listener)' if str(args[0]) == CURL and result.returncode == 7 else ''
        raise SafetyError('Command failed (exit %s): %s%s' % (result.returncode, args[0], detail))
    return result.stdout


def unit(name):
    keys = ('LoadState', 'ActiveState', 'SubState', 'MainPID', 'ControlGroup',
            'ExecMainStartTimestampMonotonic', 'UnitFileState', 'Result')
    text = command([SYSTEMCTL, 'show', name, '--no-pager',
                    '--property=' + ','.join(keys)])
    result = dict(line.split('=', 1) for line in text.splitlines() if '=' in line)
    if result.get('LoadState') != 'loaded':
        raise SafetyError('Missing/unloaded unit: ' + name)
    return result


def control(action, name):
    if action not in {'start', 'stop', 'restart', 'enable', 'disable'} or name not in {APP, PROXY, TIMER}:
        raise SafetyError('Unsupported service operation.')
    log('%s %s' % (action, name))
    command([SYSTEMCTL, action, name], timeout=120)


def identity(info):
    return (info['MainPID'], info['ExecMainStartTimestampMonotonic'])


def cgroup_pids(info):
    group = info.get('ControlGroup')
    if not group:
        if info['ActiveState'] == 'inactive' and info['MainPID'] == '0':
            return set()
        raise SafetyError('Unable to locate application cgroup.')
    path = (CGROUP / group.lstrip('/')).resolve()
    if CGROUP.resolve() not in path.parents:
        raise SafetyError('Unexpected application cgroup path.')
    if not path.exists():
        if info['ActiveState'] == 'inactive' and info['MainPID'] == '0':
            return set()
        raise SafetyError('Application cgroup disappeared.')
    if not (path / 'cgroup.procs').is_file():
        raise SafetyError('This helper requires cgroup v2 (as on this Lightsail host).')
    pids = set()
    for filename in path.rglob('cgroup.procs'):
        try:
            pids.update(int(value) for value in filename.read_text().split())
        except FileNotFoundError:
            # A nested worker cgroup can disappear while being enumerated.
            continue
    return pids


def activity():
    text = command([REPO / '.venv/bin/python', '-B', REPO / 'tools/ops/report_games.py',
                    '--data-dir', DATA, '--json'], astra=True)
    values = json.loads(text)['activity']
    counts = ('active_responses', 'building_replays', 'reserved_tokens')
    if any(type(values.get(key)) is not int or values[key] < 0 for key in counts):
        raise SafetyError('Invalid activity report; refusing to stop.')
    idle = all(values[key] == 0 for key in counts)
    if values.get('idle_snapshot') is not idle:
        raise SafetyError('Inconsistent idle report; refusing to stop.')
    return values


def site_span(text):
    """Only edit the known, standalone, flat Astra site; refuse complex layouts.

    A deliberately narrow parser is safer than pretending to parse all Caddyfile
    syntax. The current normal and maintenance blocks have no nested directives.
    Caddy itself subsequently validates the whole candidate configuration.
    """
    matches = list(re.finditer(r'(?m)^' + re.escape(DOMAIN) + r'[ \t]+\{[ \t]*\n', text))
    if len(matches) != 1:
        raise SafetyError('Expected exactly one standalone Astra site block; inspect the Caddyfile.')
    start = matches[0].start()
    end = re.search(r'(?m)^\}[ \t]*(?:\n|$)', text[matches[0].end():])
    if end is None:
        raise SafetyError('Unclosed Astra site block.')
    stop = matches[0].end() + end.end()
    body = text[matches[0].end():matches[0].end() + end.start()]
    if '{' in body or '}' in body:
        raise SafetyError('Nested/templated Astra configuration needs operator review.')
    return start, stop


def site_block(text):
    start, stop = site_span(text)
    return text[start:stop]


def replace_site(text, expected, replacement):
    start, stop = site_span(text)
    if text[start:stop] != expected:
        raise SafetyError('Astra proxy block changed outside this operation; refusing to overwrite it.')
    return text[:start] + replacement + text[stop:]


def normal_block(block):
    lines = [line.strip() for line in block.splitlines()[1:-1]
             if line.strip() and not line.lstrip().startswith('#')]
    if lines not in (['encode gzip', 'reverse_proxy 127.0.0.1:8788'],
                     ['reverse_proxy 127.0.0.1:8788']):
        raise SafetyError('Astra proxy block differs from the supported host profile; review before shutdown.')


def maintenance_block(marker):
    return (DOMAIN + ' {\n'
            '    header Retry-After "600"\n'
            '    header Cache-Control "no-store"\n'
            '    header X-Astra-Maintenance "' + marker + '"\n'
            '    respond "Astra is temporarily offline for maintenance. Your saved game will be available when service returns." 503\n'
            '}\n')


@contextmanager
def lock(path):
    import fcntl
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SafetyError('Another operator is using ' + str(path)) from None
        yield
    finally:
        os.close(fd)


def atomic_write(path, data, *, owner=None, mode=0o600):
    if path.is_symlink():
        raise SafetyError('Refusing symlink: ' + str(path))
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        os.fchmod(fd, mode)
        if owner is not None:
            os.fchown(fd, *owner)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def save(state):
    atomic_write(STATE_FILE, (json.dumps(state, indent=2) + '\n').encode())


def load():
    if not STATE_FILE.exists():
        return None
    state = json.loads(STATE_FILE.read_text())
    if state.get('schema') != 1 or not re.fullmatch('[0-9a-f]{32}', state.get('marker', '')):
        raise SafetyError('Unknown or invalid maintenance checkpoint.')
    normal_block(state['original_block'])
    for name in ('app_enabled', 'timer_enabled'):
        if state.get(name) not in ('enabled', 'disabled'):
            raise SafetyError('Unsupported saved boot state.')
    if type(state.get('timer_active')) is not bool:
        raise SafetyError('Invalid saved timer state.')
    return state


def curl(path, *, proxy=True, timeout=10):
    args = [CURL, '--silent', '--show-error', '--noproxy', '*', '--max-time', str(timeout),
            '--dump-header', '-', '--write-out', '\n%{http_code}']
    if proxy:
        args += ['--resolve', DOMAIN + ':443:127.0.0.1', 'https://' + DOMAIN + path]
    else:
        args += ['--header', 'Host: ' + DOMAIN, 'http://127.0.0.1:8788' + path]
    output = command(args, timeout=timeout + 1).replace('\r\n', '\n')
    payload, status = output.rsplit('\n', 1)
    headers, body = payload.split('\n\n', 1)
    return int(status), headers.lower(), body


def probe_timeout(deadline):
    if deadline is None:
        return 10
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise SafetyError('Proxy readiness deadline expired.')
    return min(10, remaining)


def verify_gate(state, *, deadline=None):
    for path in ('/health', '/api/config'):
        status, headers, _ = curl(path, timeout=probe_timeout(deadline))
        if status != 503 or ('x-astra-maintenance: ' + state['marker']) not in headers:
            raise SafetyError('Astra maintenance response is not confirmed. No app stop was attempted.')


def health(*, proxy, deadline=None):
    status, _, body = curl('/health', proxy=proxy, timeout=probe_timeout(deadline))
    if status != 200 or json.loads(body).get('ok') is not True:
        raise SafetyError('Astra health check failed.')


def wait_proxy(state, *, gated, timeout=PROXY_READY_SECONDS):
    """Type=exec means launched, not listening; require the real HTTPS response."""
    deadline = time.monotonic() + timeout
    waiting_logged = False
    while True:
        info = unit(PROXY)
        if info['ActiveState'] in ('failed', 'inactive', 'deactivating'):
            raise SafetyError('Shared Caddy proxy is ' + info['ActiveState'] + '; inspect its journal.')
        try:
            if gated:
                verify_gate(state, deadline=deadline)
            else:
                health(proxy=True, deadline=deadline)
            return
        except (SafetyError, ValueError, subprocess.TimeoutExpired) as error:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SafetyError('Caddy HTTPS readiness timed out after %ss. Last check: %s' %
                                  (timeout, error)) from None
            if not waiting_logged:
                log('Waiting for Caddy HTTPS readiness (up to %ss)...' % timeout)
                waiting_logged = True
            time.sleep(min(PROXY_POLL_SECONDS, remaining))


def validate_config(path, *, gated):
    args = [CADDY, 'adapt', '--config', path, '--adapter', 'caddyfile']
    adapted = json.loads(command(args, astra=True))
    # A second hostname/import pointing to Astra would bypass the gate.
    def dials(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == 'dial' and isinstance(item, str):
                    yield item
                yield from dials(item)
        elif isinstance(value, list):
            for item in value:
                yield from dials(item)
    astra_dials = [value for value in dials(adapted) if re.search(r':8788$', value)]
    if (gated and astra_dials) or (not gated and astra_dials != ['127.0.0.1:8788']):
        raise SafetyError('Unexpected alternate Astra upstream; inspect all proxy routes.')
    command([CADDY, 'validate', '--config', path, '--adapter', 'caddyfile'], astra=True)


def change_proxy(state, *, gated):
    """Caller holds CONFIG_LOCK. Never restore a full historical Caddyfile."""
    before = CADDYFILE.read_bytes()
    text = before.decode('utf-8')
    original = state['original_block']
    maintenance = maintenance_block(state['marker'])
    desired, other = (maintenance, original) if gated else (original, maintenance)
    present = site_block(text)
    if present not in (desired, other):
        raise SafetyError('Astra proxy block was edited independently; checkpoint retained for review.')
    candidate = replace_site(text, present, desired).encode()
    info = CADDYFILE.stat()
    fd, name = tempfile.mkstemp(prefix='.astra-caddy-check-', dir=CADDYFILE.parent)
    os.close(fd)
    path = Path(name)
    installed = False
    try:
        atomic_write(path, candidate, owner=(info.st_uid, info.st_gid))
        validate_config(path, gated=gated)
        if CADDYFILE.read_bytes() != before:
            raise SafetyError('Caddyfile changed during validation; retry after coordinating with the other operator.')
        atomic_write(CADDYFILE, candidate, owner=(info.st_uid, info.st_gid), mode=info.st_mode & 0o777)
        installed = True
        # admin off + bind-mounted Caddyfile means a controlled restart is needed.
        control('restart', PROXY)
        wait_proxy(state, gated=gated)
    except BaseException:
        # Restore only the block we changed; never erase concurrent other-site edits.
        # On opening failure, return to maintenance. On closing failure, return
        # to the previous config so Arcturus need not remain offline as collateral.
        try:
            current = CADDYFILE.read_bytes().decode('utf-8')
            fallback = maintenance if not gated else present
            if installed and site_block(current) == desired:
                reverted = replace_site(current, desired, fallback).encode()
                atomic_write(path, reverted, owner=(info.st_uid, info.st_gid))
                validate_config(path, gated=(fallback == maintenance))
                if CADDYFILE.read_bytes() != current.encode():
                    raise SafetyError('Proxy configuration changed during recovery.')
                atomic_write(CADDYFILE, reverted, owner=(info.st_uid, info.st_gid), mode=info.st_mode & 0o777)
                control('restart', PROXY)
                wait_proxy(state, gated=(fallback == maintenance))
        except BaseException:
            log('Proxy recovery failed. Inspect astra-caddy.service and the Caddyfile before proceeding.')
        raise
    finally:
        path.unlink(missing_ok=True)


def preflight(*, allow_failed=False):
    if not CADDYFILE.is_file() or CADDYFILE.is_symlink() or not (DATA / 'astra.sqlite3').is_file():
        raise SafetyError('Expected host files are missing or symlinked.')
    services = {name: unit(name) for name in (APP, PROXY, TIMER, NOTIFIER)}
    for name in (APP, TIMER):
        if services[name]['UnitFileState'] not in ('enabled', 'disabled'):
            raise SafetyError('Unsupported boot enablement for ' + name)
    if services[PROXY]['ActiveState'] != 'active':
        raise SafetyError('Shared Caddy proxy must already be running.')
    if services[APP]['ActiveState'] not in (('active', 'inactive', 'failed') if allow_failed else ('active', 'inactive')):
        raise SafetyError('Astra is failed or transitioning; inspect its journal first.')
    site_block(CADDYFILE.read_text())
    activity()
    if services[APP]['ActiveState'] != 'failed':
        cgroup_pids(services[APP])
    return services


def wait_idle(state, timeout):
    deadline = time.monotonic() + timeout
    stable_since = None
    while True:
        info = unit(APP)
        if info['ActiveState'] != 'active' or identity(info) != tuple(state['app_identity']):
            raise SafetyError('Astra exited/restarted while draining; inspect its journal. No forced stop performed.')
        values = activity()
        pids = cgroup_pids(info)
        if int(info['MainPID']) not in pids:
            raise SafetyError('Application PID is absent from its cgroup; refusing to infer idle state.')
        children = pids - {int(info['MainPID'])}
        notifier = unit(NOTIFIER)
        notify_idle = notifier['ActiveState'] == 'inactive' and notifier['MainPID'] == '0'
        if notifier['ActiveState'] == 'failed':
            raise SafetyError('Notification job failed; inspect it before taking a migration copy.')
        idle = values['idle_snapshot'] and not children and notify_idle
        now = time.monotonic()
        stable_since = now if idle and stable_since is None else stable_since if idle else None
        elapsed = int(now - stable_since) if stable_since is not None else 0
        log('Responses %d; replays %d; reserved tokens %d; child processes %d; notifier %s; quiet %ds/%ds' % (
            values['active_responses'], values['building_replays'], values['reserved_tokens'],
            len(children), notifier['ActiveState'], elapsed, STABLE_SECONDS))
        if stable_since is not None and now - stable_since >= STABLE_SECONDS:
            return
        if now >= deadline:
            raise SafetyError('Drain timed out. Astra remains running behind maintenance; rerun down to keep waiting or up to reopen.')
        time.sleep(min(POLL_SECONDS, deadline - now))


def assert_stopped():
    info = unit(APP)
    if info['ActiveState'] != 'inactive' or info['MainPID'] != '0' or cgroup_pids(info):
        raise SafetyError('Astra has not stopped cleanly; do not copy its data yet.')
    if info.get('Result') != 'success' or not activity()['idle_snapshot']:
        raise SafetyError('Stopped state is not clean/idle; inspect the journal before migration.')
    notifier = unit(NOTIFIER)
    if notifier['ActiveState'] != 'inactive' or notifier['MainPID'] != '0':
        raise SafetyError('Notification job has not finished; wait before copying its state.')


def down(timeout):
    services = preflight()
    state = load()
    if state is None:
        original = site_block(CADDYFILE.read_text())
        normal_block(original)
        if services[APP]['ActiveState'] != 'active':
            raise SafetyError('Astra is already stopped without a maintenance checkpoint; inspect before proceeding.')
        state = dict(schema=1, marker=uuid.uuid4().hex, phase='preparing',
                     original_block=original, app_identity=identity(services[APP]),
                     app_enabled=services[APP]['UnitFileState'], timer_enabled=services[TIMER]['UnitFileState'],
                     timer_active=services[TIMER]['ActiveState'] == 'active', created_at=time.time())
        save(state)
        atomic_write(STATE_DIR / ('Caddyfile-' + state['marker'] + '.backup'), CADDYFILE.read_bytes())
    with lock(CONFIG_LOCK):
        if site_block(CADDYFILE.read_text()) != maintenance_block(state['marker']):
            change_proxy(state, gated=True)
        else:
            try:
                wait_proxy(state, gated=True)
            except SafetyError:
                change_proxy(state, gated=True)
    control('stop', TIMER)
    control('disable', TIMER)
    control('disable', APP)  # Does not stop running work; survives a reboot while migrating.
    state['phase'] = 'draining'
    save(state)
    if unit(APP)['ActiveState'] == 'inactive':
        assert_stopped()
    else:
        wait_idle(state, timeout)
        with lock(CONFIG_LOCK):
            if site_block(CADDYFILE.read_text()) != maintenance_block(state['marker']):
                raise SafetyError('Maintenance config changed during drain; refusing to stop.')
            verify_gate(state)
            validate_config(CADDYFILE, gated=True)
            info = unit(APP)
            if identity(info) != tuple(state['app_identity']) or info['ActiveState'] != 'active':
                raise SafetyError('Application identity changed before stop.')
            if not activity()['idle_snapshot'] or cgroup_pids(info) != {int(info['MainPID'])}:
                raise SafetyError('Work appeared at the final check. Leave maintenance active and rerun down.')
            state['phase'] = 'stopping'
            save(state)
            control('stop', APP)
        assert_stopped()
    state['phase'] = 'stopped'
    save(state)
    log('Astra is stopped and will stay disabled across reboot. Maintenance is active. It is now safe to take the final backup.')
    log('Preserve the full game data, private configuration, notifier state, and ' + str(STATE_DIR) + ' for migration.')


def up(timeout):
    state = load()
    preflight(allow_failed=state is not None)
    if state is None:
        health(proxy=True)
        if unit(APP)['ActiveState'] != 'active':
            raise SafetyError('Astra is not active and no maintenance checkpoint exists.')
        log('Astra is already available; no maintenance checkpoint or changes.')
        return
    # A previous up may have opened access but failed while restoring the timer.
    # Do not re-gate or restart the app in that recovery case.
    already_open = state['phase'] == 'opening' and site_block(CADDYFILE.read_text()) == state['original_block']
    if already_open:
        try:
            health(proxy=True)
            already_open = unit(APP)['ActiveState'] == 'active'
        except (SafetyError, ValueError, subprocess.TimeoutExpired):
            already_open = False
    if not already_open:
        with lock(CONFIG_LOCK):
            if site_block(CADDYFILE.read_text()) != maintenance_block(state['marker']):
                change_proxy(state, gated=True)
            else:
                wait_proxy(state, gated=True)
        state['phase'] = 'starting'
        save(state)
        control('start', APP)
        deadline = time.monotonic() + timeout
        while True:
            try:
                if unit(APP)['ActiveState'] != 'active':
                    raise SafetyError('Astra has not reached active state.')
                health(proxy=False)
                break
            except (SafetyError, ValueError, subprocess.TimeoutExpired):
                if time.monotonic() >= deadline:
                    raise SafetyError('Startup health timed out. Maintenance remains active; inspect the app journal.') from None
                time.sleep(POLL_SECONDS)
        state['phase'] = 'opening'
        save(state)
        with lock(CONFIG_LOCK):
            change_proxy(state, gated=False)
    control('enable' if state['app_enabled'] == 'enabled' else 'disable', APP)
    control('enable' if state['timer_enabled'] == 'enabled' else 'disable', TIMER)
    if state['timer_active']:
        control('start', TIMER)
        if unit(TIMER)['ActiveState'] != 'active':
            raise SafetyError('Notification timer did not start; rerun up to complete recovery.')
    health(proxy=True)
    # Keep an audit, but remove the active checkpoint only after full success.
    state['phase'] = 'complete'
    state['completed_at'] = time.time()
    atomic_write(STATE_DIR / ('completed-' + state['marker'] + '.json'), (json.dumps(state, indent=2) + '\n').encode())
    STATE_FILE.unlink()
    log('Astra is available again. Previous app/timer boot settings have been restored.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('down', 'up', 'status'))
    parser.add_argument('--check', action='store_true', help='Read-only preflight/status; do not change files or services')
    parser.add_argument('--timeout', type=int, default=1800, help='Maximum drain/health wait in seconds (default 1800); never force a stop')
    args = parser.parse_args(argv)
    if sys.platform != 'linux' or os.geteuid() != 0:
        parser.error('Run on Lightsail using ec2-user and sudo, as documented.')
    if args.timeout < STABLE_SECONDS + POLL_SECONDS:
        parser.error('--timeout must be at least 35 seconds.')
    os.umask(0o077)
    try:
        if args.check or args.action == 'status':
            services = preflight()
            state = load()
            if state is None:
                normal_block(site_block(CADDYFILE.read_text()))
            else:
                log('Maintenance checkpoint: ' + state['phase'])
            log(json.dumps({name: {key: info.get(key) for key in ('ActiveState', 'MainPID', 'UnitFileState')}
                            for name, info in services.items()}, indent=2))
            log(json.dumps(activity()))
            log('Read-only check complete. No files or services changed.')
            return 0
        if STATE_DIR.is_symlink():
            raise SafetyError('Maintenance state directory must not be a symlink.')
        STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        if STATE_DIR.stat().st_uid != 0 or STATE_DIR.stat().st_mode & 0o077:
            raise SafetyError('Maintenance state directory must be root-owned and private (0700).')
        with lock(STATE_DIR / 'operation.lock'):
            (down if args.action == 'down' else up)(args.timeout)
        return 0
    except (SafetyError, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
        log('STOPPED: ' + str(error))
        log('No force-stop fallback. Check the saved maintenance state and service journals; rerun down/up after resolving the issue.')
        return 1
    except KeyboardInterrupt:
        log('Interrupted. Existing AI work was not force-stopped. Maintenance/checkpoint may remain; rerun down or up.')
        return 130


if __name__ == '__main__':
    sys.exit(main())
