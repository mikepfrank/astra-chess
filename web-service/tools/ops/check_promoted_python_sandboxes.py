#!/usr/bin/env python3
"""Model-free Python probes in temporary replicas of reviewed service units.

Default only plans; --run creates/removes a diagnostic systemd unit. It never
starts a production app. Runtime probes omit environment credentials and app
lifecycle hooks, and do not load models or application stores. Astra-preflight
retains its two distinct EnvironmentFile directives and uses the installed
preflight's disposable files. Production data is not used as a test fixture.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import secrets
import stat
import subprocess
import sys

TARGETS = {
    'astra': ('astra-chess.service', 'astra', '/home/astra/astra-chess/web-service/.venv/bin/python',
              ('/etc/systemd/system/astra-chess.service.d/20-monitor.conf',)),
    'arcturus': ('or-chess.service', 'or-chess', '/home/or-chess/astra-chess/web-service/.venv/bin/python', ()),
    'gpt2-public': ('gpt2-public.service', 'gpt-2', '/home/gpt-2/.venvs/gpt2-public/bin/python',
                    ('/etc/systemd/system/gpt2-public.service.d/90-gpt2-streaming.conf',)),
    'gpt2-lab': ('gpt2-codex.service', 'gpt-2', '/home/gpt-2/.venvs/gpt2-public/bin/python', ()),
}
ALL_STOPPED = tuple(v[0] for v in TARGETS.values()) + ('astra-game-notify.timer', 'or-chess-game-notify.timer')
LIFECYCLE = {'Type', 'Restart', 'RestartSec', 'TimeoutStartSec', 'TimeoutStopSec',
             'TimeoutAbortSec', 'RuntimeMaxSec', 'RemainAfterExit', 'PIDFile', 'BusName',
             'WatchdogSec', 'WatchdogSignal', 'StandardOutput', 'StandardError'}
ENVIRONMENT = {'Environment', 'EnvironmentFile', 'UnsetEnvironment', 'PassEnvironment'}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def command(args, timeout=30):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    require(result.returncode == 0, 'Diagnostic command failed; private details were not printed')
    return result.stdout


def properties(unit, *names):
    return dict(line.split('=', 1) for line in command(
        ['systemctl', 'show', unit, *(part for name in names for part in ('-p', name))]
    ).splitlines() if '=' in line)


def stopped_guard():
    for name in ALL_STOPPED:
        state = properties(name, 'ActiveState', 'MainPID', 'UnitFileState')
        require(state.get('ActiveState') == 'inactive' and state.get('MainPID', '0') == '0'
                and state.get('UnitFileState') == 'disabled', 'A production app or timer is not stopped/disabled')


def service_lines(text):
    result = []
    section = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(('#', ';')):
            continue
        require(not line.endswith('\\'), 'Unit continuation requires review')
        if line.startswith('['):
            section = line
        elif section == '[Service]':
            require('=' in line, 'Malformed service directive')
            result.append(line)
    return result


def read_unit(target):
    name, user, _, dropins = TARGETS[target]
    fields = properties(name, 'FragmentPath', 'DropInPaths')
    paths = (f'/etc/systemd/system/{name}', *dropins)
    require(fields.get('FragmentPath') == paths[0]
            and tuple(fields.get('DropInPaths', '').split()) == dropins, 'Installed unit layout differs from reviewed selection')
    lines = []
    for path in paths:
        file = Path(path)
        info = file.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022,
                'Unsafe source unit ownership or mode')
        lines.extend(service_lines(file.read_text()))
    for field in ('User', 'Group'):
        values = [line.split('=', 1)[1] for line in lines if line.startswith(field + '=')]
        require(values and values[-1] == user, 'Installed service account differs')
    return lines


def payload(target):
    gpt2 = target.startswith('gpt2-')
    source = '''import json,ssl,sys,certifi,sqlite3,pyexpat
assert sys.version_info[:3] == (3,12,16)
assert certifi.__version__ == '2026.10.23'
ssl.create_default_context(cafile=certifi.where())
result={'python':sys.version.split()[0],'openssl':ssl.OPENSSL_VERSION,'certifi':certifi.__version__,'sqlite':sqlite3.sqlite_version,'expat':pyexpat.EXPAT_VERSION,'tls_context':True}
'''
    if gpt2:
        source += '''assert sys.base_prefix == '/usr'
assert ssl.OPENSSL_VERSION.startswith('OpenSSL 3.5.8 ')
import torch
torch.set_num_threads(1)
assert (torch.tensor([1.0,2.0])+torch.tensor([3.0,4.0])).tolist()==[4.0,6.0]
result['torch']=torch.__version__;result['tiny_tensor']=True
'''
    else:
        source += '''assert ssl.OPENSSL_VERSION.startswith('OpenSSL 3.5.9 ')
assert sqlite3.sqlite_version == '3.53.1'
assert pyexpat.EXPAT_VERSION == 'expat_2.10.0'
'''
    source += "print('RUNTIME_VALIDATION_JSON '+json.dumps(result,sort_keys=True))\n"
    encoded = base64.b64encode(source.encode()).decode()
    return "import base64;exec(base64.b64decode('" + encoded + "'))"


def build_unit(lines, target, mode):
    python = TARGETS[target][2]
    require(mode == 'runtime' or (mode == 'astra-preflight' and target == 'astra'), 'Unsupported probe selection')
    kept = []
    for line in lines:
        key = line.split('=', 1)[0]
        if key.startswith('Exec') or key in LIFECYCLE or (mode == 'runtime' and key in ENVIRONMENT):
            continue
        kept.append(line)
    if mode == 'runtime':
        kept += ['Environment=PATH=/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1',
                 f'ExecStart={python} -I -B -c "{payload(target)}"']
    else:
        kept.append(f'ExecStart={python} -I -B /home/astra/astra-chess/web-service/tools/check_linux_service.py')
    kept += ['Type=oneshot', 'Restart=no', 'TimeoutStartSec=120', 'TimeoutStopSec=10',
             'RuntimeMaxSec=120', 'StandardOutput=journal', 'StandardError=journal']
    return '[Unit]\nDescription=Disposable promoted Python validation\n[Service]\n' + '\n'.join(kept) + '\n'


def parse_output(output, mode):
    if mode == 'runtime':
        found = [line.removeprefix('RUNTIME_VALIDATION_JSON ') for line in output.splitlines()
                 if line.startswith('RUNTIME_VALIDATION_JSON ')]
        require(len(found) == 1, 'Missing or duplicate runtime result')
        return json.loads(found[0])
    decoder = json.JSONDecoder()
    found = []
    for pos, char in enumerate(output):
        if char != '{':
            continue
        try:
            value, _ = decoder.raw_decode(output[pos:])
        except ValueError:
            continue
        if isinstance(value, dict) and set(value) == {'checks', 'limits', 'python', 'sqlite', 'codex'}:
            found.append(value)
    require(len(found) == 1 and isinstance(found[0]['checks'], dict)
            and found[0]['checks'] and all(value is True for value in found[0]['checks'].values()),
            'Astra preflight did not report all checks passed')
    return found[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target', choices=TARGETS)
    parser.add_argument('--mode', choices=('runtime', 'astra-preflight'), default='runtime')
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args()
    require(os.geteuid() == 0, 'Run as root on the reviewed host')
    stopped_guard()
    lines = read_unit(args.target)
    text = build_unit(lines, args.target, args.mode)
    if not args.run:
        print(json.dumps({'target': args.target, 'mode': args.mode, 'planned': True,
                          'source_unit': TARGETS[args.target][0], 'source_dropins': TARGETS[args.target][3],
                          'credential_environment_retained': args.mode == 'astra-preflight',
                          'production_apps_started': False}))
        return
    name = 'python-security-probe-' + secrets.token_hex(8) + '.service'
    path = Path('/run/systemd/system') / name
    require(not path.exists(), 'Diagnostic unit name collision')
    os.umask(0o077)
    created = False
    try:
        with path.open('x') as file:
            created = True
            file.write(text)
        command(['systemctl', 'daemon-reload'])
        command(['systemctl', 'start', name], timeout=135)
        state = properties(name, 'Result', 'ExecMainStatus', 'MainPID', 'ActiveState')
        require(state == {'Result': 'success', 'ExecMainStatus': '0', 'MainPID': '0', 'ActiveState': 'inactive'},
                'Diagnostic unit did not exit cleanly')
        output = command(['journalctl', '-u', name, '--no-pager', '-o', 'cat', '-n', '500'])
        result = parse_output(output, args.mode)
        stopped_guard()
        print(json.dumps({'target': args.target, 'mode': args.mode, 'verified': True, 'result': result}, indent=2))
    finally:
        # Never execute any production lifecycle helper or cleanup hook here.
        if created:
            stopped = subprocess.run(['systemctl', 'stop', name], capture_output=True, timeout=25)
            require(stopped.returncode == 0, 'Diagnostic cleanup failed; retained unit ' + name)
            subprocess.run(['systemctl', 'reset-failed', name], capture_output=True, timeout=15)
            path.unlink()
            command(['systemctl', 'daemon-reload'])


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({'verified': False, 'error': str(error) if type(error) is RuntimeError
                          else 'Diagnostic failed; inspect on-host (' + type(error).__name__ + ')'}))
        sys.exit(1)
