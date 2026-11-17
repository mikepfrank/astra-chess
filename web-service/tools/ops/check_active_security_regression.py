#!/usr/bin/env python3
"""Read-only checks of the four running apps while maintenance gates remain shut.

Run as root with the reviewed activation and GPT-2 maintenance helpers beside
this file. Does not start/reload services, enable timers, change checkpoints,
create sessions, invoke models, or print private URLs or user records. The only
POSTs are empty-object requests to the publicly gated GPT-2 generation routes;
they must be rejected by Caddy. Runtime subprocesses enter the app's mount
namespace, drop to its account, and use a clean environment with bytecode off.
These verify installed runtime visibility, not inheritance of every app sandbox.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import types


TARGETS = {
    'astra-chess.service': ('astra', '/home/astra/astra-chess/web-service/.venv/bin/python', 'tmpfs', 'yes'),
    'or-chess.service': ('or-chess', '/home/or-chess/astra-chess/web-service/.venv/bin/python', 'tmpfs', 'yes'),
    'gpt2-public.service': ('gpt-2', '/home/gpt-2/.venvs/gpt2-public/bin/python', 'read-only', 'yes'),
    'gpt2-codex.service': ('gpt-2', '/home/gpt-2/.venvs/gpt2-public/bin/python', 'no', 'no'),
}
TIMERS = ('astra-game-notify.timer', 'or-chess-game-notify.timer')
JOBS = ('astra-game-notify.service', 'or-chess-game-notify.service', 'gpt2-preview.service')
CONFIG = Path('/home/astra/.config/astra-chess/Caddyfile')
HELPERS = {
    'activate_proxy_image_security.py': '46a52433d10c1bf6398426ef3242e264bf399affeef693cdb666ebf26249356b',
    'gpt2_maintenance-v2.py': '80018c27bb074cd66782b9313346b5033bce808cc0a1058c543b92585b1f7912',
}


def require(value, message):
    if not value:
        raise RuntimeError(message)


def run(args):
    p = subprocess.run(list(map(str, args)), text=True, capture_output=True, timeout=45)
    require(p.returncode == 0, 'Read-only subprocess failed; private output suppressed')
    return p.stdout


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def helper(name):
    path = Path(__file__).resolve().with_name(name)
    require(sha(path) == HELPERS[name], 'Reviewed helper checksum changed')
    module = types.ModuleType('checked_' + name.replace('.', '_'))
    module.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


def properties(name):
    keys = ('ActiveState', 'MainPID', 'UnitFileState', 'User', 'ControlGroup',
            'NoNewPrivileges', 'PrivateTmp', 'ProtectSystem', 'ProtectHome',
            'FragmentPath', 'DropInPaths')
    return dict(line.split('=', 1) for line in run(['systemctl', 'show', name,
        *(part for key in keys for part in ('-p', key))]).splitlines())


def app_guard():
    result = {}
    for name, (account, _, home, private) in TARGETS.items():
        value = properties(name)
        require(value['ActiveState'] == 'active' and int(value['MainPID']) > 1
                and value['UnitFileState'] == 'disabled' and value['User'] == account,
                'App is not running with boot startup disabled: ' + name)
        expected = {'ProtectHome': home, 'PrivateTmp': private,
                    'NoNewPrivileges': private, 'ProtectSystem': 'no' if private == 'no' else 'strict'}
        require(all(value[key] == want for key, want in expected.items()), 'App sandbox settings changed: ' + name)
        result[name] = value
    for name in (*TIMERS, *JOBS):
        value = properties(name)
        require(value['ActiveState'] == 'inactive' and value.get('MainPID', '0') == '0', 'Background job is active')
        if name in TIMERS:
            require(value['UnitFileState'] == 'disabled', 'Notifier timer is enabled')
    for namespace in ('astra-chess-ops', 'arcturus-chess-ops'):
        require(json.loads(Path('/var/lib', namespace, 'maintenance.json').read_text())['phase'] == 'stopped',
                'Chess diagnostic checkpoint changed')
    return result


def runtime(name, state):
    account, python, _, _ = TARGETS[name]
    pid = int(state['MainPID'])
    require(os.path.samefile('/proc/%d/exe' % pid, '/proc/%d/root%s' % (pid, python)),
            'Running Python does not match the selected runtime')
    openssl = 'OpenSSL 3.5.8 ' if account == 'gpt-2' else 'OpenSSL 3.5.9 '
    code = ("import sys,ssl,certifi,json; assert sys.version_info[:3]==(3,12,16); "
            "assert certifi.__version__=='2026.10.23'; "
            "assert ssl.OPENSSL_VERSION.startswith(" + repr(openssl) + "); "
            "ssl.create_default_context(cafile=certifi.where()); "
            "print(json.dumps({'python':sys.version.split()[0],'openssl':ssl.OPENSSL_VERSION,"
            "'certifi':certifi.__version__,'tls_context':True}))")
    result = json.loads(run(['nsenter', '--target', pid, '--mount', '--',
        '/usr/sbin/runuser', '-u', account, '--', '/usr/bin/env', '-i',
        'PATH=/usr/bin:/bin', 'HOME=/nonexistent', 'PYTHONDONTWRITEBYTECODE=1',
        python, '-I', '-B', '-c', code]))
    result['running_executable_matches'] = True
    return result


def chess_get(port, host, path):
    result = run(['curl', '--silent', '--show-error', '--noproxy', '*', '--max-time', '10',
        '--header', 'Host: ' + host, '--write-out', '\n%{http_code}',
        'http://127.0.0.1:' + str(port) + path])
    body, status = result.rsplit('\n', 1)
    return int(status), body


def chess_routes(port, host):
    checked = {}
    for path, expected in [('/', 200), ('/health', 200), ('/api/config', 200),
                           ('/monitor/', 200), ('/api/operator/games', 401),
                           ('/api/games', 401), ('/games/', 200), ('/api/public-replays', 200)]:
        status, body = chess_get(port, host, path)
        require(status == expected, 'Direct chess route status differs: ' + host + path)
        if path == '/health':
            require(json.loads(body) == {'ok': True}, 'Chess health content differs')
        if path == '/api/public-replays':
            entries = json.loads(body)
        checked[path] = status
    games = entries['games']
    if games:
        url = games[0]['public_url']
        require(isinstance(url, str) and re.fullmatch(r'/games/[A-Za-z0-9_-]+\.html', url),
                'Unexpected public replay route')
        status, body = chess_get(port, host, url)
        require(status == 200 and '<html' in body.lower(), 'Published replay failed')
    return {'routes': checked, 'published_replay_checked': bool(games)}


def main():
    require(os.name == 'posix' and os.geteuid() == 0, 'Run as root on the reviewed host')
    before = app_guard()
    paths = [CONFIG, CONFIG.with_name('new-games.caddy'),
             Path('/home/astra/.local/share/astra-chess/new-games-paused'),
             Path('/usr/local/libexec/gpt2-codex-sandbox'),
             Path('/usr/local/libexec/gpt2-codex-seccomp.json'),
             Path('/etc/gpt2-codex.env')]
    for value in before.values():
        paths.extend(Path(path) for path in [value['FragmentPath'], *value['DropInPaths'].split()])
    paths += [Path('/var/lib', name, 'maintenance.json') for name in
              ('astra-chess-ops', 'arcturus-chess-ops', 'gpt2-maintenance-ops')]
    hashes = {str(path): sha(path) for path in paths}
    activation = helper('activate_proxy_image_security.py')
    maintenance = helper('gpt2_maintenance-v2.py')
    state = maintenance.load()
    require(all(value['phase'] == 'started' for value in state['services'].values()),
            'GPT-2 diagnostic checkpoints are not started')
    proxy_pid = activation.proxy_identity(activation.NEW_CADDY)
    activation.gates(maintenance)
    require(sha(activation.LAUNCHER) == activation.NEW_LAUNCHER, 'GPT-2 launcher changed')
    require(run(['docker', 'image', 'inspect', '--format', '{{.Id}}', activation.NEW_TAG]).strip()
            == activation.NEW_IMAGE, 'Selected candidate image changed')
    network = json.loads(run(['docker', 'network', 'inspect', 'gpt2-codex-isolated']))[0]
    require(network['Internal'] is True and [row['Subnet'] for row in network['IPAM']['Config']]
            == ['172.30.97.0/24'], 'Private sandbox network changed')
    result = {'runtime': {name: runtime(name, value) for name, value in before.items()},
              'chess': {'astra': chess_routes(8788, 'astraplayschess.com'),
                        'arcturus': chess_routes(8792, 'arcturuschess.com')}}
    public = maintenance.health(maintenance.PUBLIC)
    require(public.get('queue') == {'waiting': 0, 'running': False}, 'Public GPT-2 queue is busy')
    maintenance.health(maintenance.LAB)
    activity = maintenance.lab_activity()
    require(activity['idle'], 'Private lab is not idle')
    # The Nov 17 drain retained six pending inputs in 18 idle sessions.
    # Pending text is durable user data, not evidence of an active action.
    require(activity['sessions'] == 18 and activity['pending_human'] == 6,
            'Private lab session/pending-input counts differ from the drain baseline')
    result['gpt2'] = {'public_ready': True, 'public_queue': public['queue'],
                      'private_ready': True, 'private_activity': activity,
                      'sandbox_network_internal': True}
    activation.gates(maintenance)
    require(activation.proxy_identity(activation.NEW_CADDY) == proxy_pid, 'Proxy restarted during checks')
    after = app_guard()
    require(before == after, 'App identity or settings changed during checks')
    require(all(sha(path) == value for path, value in hashes.items()), 'Preserved configuration changed')
    result.update(passed=True, maintenance_gates=True, configuration_unchanged=True,
                  process_identities_unchanged=True, notifier_timers_disabled=True,
                  apps_boot_disabled=True, provider_requests=0, sessions_created=0)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'passed': False, 'error': str(error) if type(error) is RuntimeError
                          else 'Read-only check failed: ' + type(error).__name__}))
        raise SystemExit(1)
