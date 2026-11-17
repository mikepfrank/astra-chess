#!/usr/bin/env python3
"""Bounded chess protocol/live and notifier dry-run checks behind maintenance.

Run beside the reviewed Python sandbox helper. Production applications remain
stopped. Paid modes require --live and use fresh operator-only data directories.
Notifier previews stay private; only counts and state-preservation booleans print.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
import subprocess
import sys
import types

HELPER_SHA = 'b6136ec42c71bca7d9ebc2b2fd80efbe39bcc3d72684f6aa6bdd1ae71dabf4a6'
MODES = ('astra-protocol', 'astra-live', 'astra-notifier', 'arcturus-notifier')


def require(value, message):
    if not value:
        raise RuntimeError(message)


def helper():
    p = Path(__file__).resolve().with_name('check_promoted_python_sandboxes.py')
    source = p.read_bytes()
    require(hashlib.sha256(source).hexdigest() == HELPER_SHA, 'Sandbox helper identity differs')
    module = types.ModuleType('reviewed_sandbox')
    module.__file__ = str(p)
    exec(compile(source, str(p), 'exec'), module.__dict__)
    return module


def notifier_payload(owner):
    name = 'astra-chess' if owner == 'astra' else 'or-chess'
    source = f'''import runpy,json,hashlib
from pathlib import Path
root=Path('/home/{owner}')
data=root/'.local/share/{name}'
state=root/'.local/state/{name}-monitor'
config=root/'.config/{name}-monitor/config.json'
before=hashlib.sha256((state/'state.json').read_bytes()).hexdigest()
m=runpy.run_path(str(root/'astra-chess/web-service/tools/ops/notify_new_games.py'),run_name='inspection')
r=m['run'](data,state,config_path=config,dry_run=True)
assert r['dry_run'] is True
assert hashlib.sha256((state/'state.json').read_bytes()).hexdigest()==before
print('CHECK_JSON '+json.dumps({{'dry_run':True,'queued_games':r['games'],'state_unchanged':True,'email_sent':False}}))
'''
    return "import base64;exec(base64.b64decode('" + base64.b64encode(source.encode()).decode() + "'))"


def build(helper_module, mode, check_id):
    if mode.endswith('notifier'):
        owner = 'astra' if mode == 'astra-notifier' else 'or-chess'
        name = 'astra-game-notify.service' if owner == 'astra' else 'or-chess-game-notify.service'
        p = Path('/etc/systemd/system') / name
        props = helper_module.properties(name, 'FragmentPath', 'DropInPaths', 'ActiveState', 'MainPID')
        require(props['FragmentPath'] == str(p) and not props['DropInPaths']
                and props['ActiveState'] == 'inactive' and props['MainPID'] == '0', 'Notifier unit changed or is active')
        info = p.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022, 'Notifier unit ownership differs')
        lines = helper_module.service_lines(p.read_text())
        require([v for v in lines if v.startswith('User=')] == ['User=' + owner], 'Notifier account differs')
        command = f'/home/{owner}/astra-chess/web-service/.venv/bin/python -I -B -c "{notifier_payload(owner)}"'
        timeout = 120
    else:
        lines = helper_module.read_unit('astra')
        app = '/home/astra/astra-chess/web-service'
        audit = '/home/astra/.local/share/astra-chess/operator-checks/security-20261117-' + check_id
        if mode == 'astra-protocol':
            command = f'{app}/.venv/bin/python -I -B {app}/tests/audit_codex_protocol.py --audit-dir {audit}'
            timeout = 120
        else:
            codex = '/home/astra/.codex/packages/standalone/releases/0.154.0-x86_64-unknown-linux-musl/bin/codex'
            command = f'{app}/.venv/bin/python -I -B {app}/tests/live_codex_check.py --live --turns 2 --codex-bin {codex} --data-dir {audit}'
            timeout = 900
    kept = [line for line in lines if not line.split('=', 1)[0].startswith('Exec')
            and line.split('=', 1)[0] not in helper_module.LIFECYCLE]
    kept += ['Type=oneshot', 'Restart=no', f'TimeoutStartSec={timeout}', 'TimeoutStopSec=15',
             f'RuntimeMaxSec={timeout}', 'StandardOutput=journal', 'StandardError=journal', 'ExecStart=' + command]
    return '[Unit]\nDescription=Disposable chess security regression\n[Service]\n' + '\n'.join(kept) + '\n', timeout


def parse(output, mode):
    if mode.endswith('notifier'):
        records = [json.loads(line.removeprefix('CHECK_JSON ')) for line in output.splitlines() if line.startswith('CHECK_JSON ')]
        require(len(records) == 1 and records[0].get('state_unchanged') is True
                and records[0].get('email_sent') is False, 'Notifier dry-run did not verify preservation')
        return records[0]
    if mode == 'astra-live':
        turns = []
        for line in output.splitlines():
            if line.startswith('{'):
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if 'ply' in record and 'thread_saved' in record:
                    turns.append(record)
        require(len(turns) == 2 and [v['ply'] for v in turns] == [1, 3]
                and all(v['thread_saved'] for v in turns)
                and 'Live move and conversation checks passed.' in output, 'Two-turn live check did not complete')
        return {'turns': turns, 'paid_provider_actions': 2, 'disposable_game_only': True}
    decoder = json.JSONDecoder()
    for pos, ch in enumerate(output):
        if ch == '{':
            try:
                record, _ = decoder.raw_decode(output[pos:])
            except ValueError:
                continue
            if isinstance(record, dict) and record.get('strict_config_verified') is True and record.get('thread_start_verified') is True:
                return record
    raise RuntimeError('Protocol check did not complete')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=MODES)
    parser.add_argument('--live', action='store_true', help='Authorize two paid actions in disposable state')
    args = parser.parse_args()
    require(args.mode != 'astra-live' or args.live, 'Paid mode requires --live')
    require(os.geteuid() == 0, 'Run as root on the reviewed host')
    h = helper()
    h.stopped_guard()
    check_id = secrets.token_hex(7)
    name = 'chess-security-' + args.mode + '-' + check_id + '.service'
    text, timeout = build(h, args.mode, check_id)
    path = Path('/run/systemd/system') / name
    os.umask(0o077)
    print(json.dumps({'starting': args.mode, 'diagnostic_unit': name}), flush=True)
    try:
        with path.open('x') as f:
            f.write(text)
        h.command(['systemctl', 'daemon-reload'])
        h.command(['systemctl', 'start', name], timeout=timeout + 20)
        state = h.properties(name, 'Result', 'ExecMainStatus', 'MainPID')
        require(state == {'Result': 'success', 'ExecMainStatus': '0', 'MainPID': '0'}, 'Regression unit failed; inspect private journal')
        output = h.command(['journalctl', '-u', name, '--no-pager', '-o', 'cat', '-n', '1000'])
        report = parse(output, args.mode)
        h.stopped_guard()
        print(json.dumps({'mode': args.mode, 'passed': True, 'result': report}, indent=2))
    finally:
        subprocess.run(['systemctl', 'stop', name], capture_output=True, timeout=30)
        subprocess.run(['systemctl', 'reset-failed', name], capture_output=True, timeout=15)
        path.unlink(missing_ok=True)
        subprocess.run(['systemctl', 'daemon-reload'], capture_output=True, timeout=30)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({'passed': False, 'error': str(exc) if type(exc) is RuntimeError else type(exc).__name__}))
        sys.exit(1)
