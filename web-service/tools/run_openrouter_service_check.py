"""Run an experimental deployment check with the installed unit's restrictions.

Invoke through sudo. PID1 reads the protected credential file; this launcher
never reads it. Only the explicit live mode makes paid model requests.
"""
import argparse
from collections import defaultdict
import os
from pathlib import Path, PurePosixPath
import secrets
import subprocess


UNIT = Path('/etc/systemd/system/or-chess.service')
APP = PurePosixPath('/home/or-chess/astra-chess/web-service')


def service_properties(text):
    """Preserve the installed [Service] properties except process lifecycle."""
    props = defaultdict(list)
    in_service = False
    ignored = {'Type', 'ExecStart', 'Restart', 'RestartSec', 'TimeoutStopSec'}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(('#', ';')):
            continue
        if line.endswith('\\'):
            raise ValueError('Unit line continuations require an updated check launcher.')
        if line.startswith('['):
            in_service = line == '[Service]'
        elif in_service:
            key, value = line.split('=', 1)
            if key not in ignored:
                props[key].append(value)
    required = {
        'User': ['or-chess'], 'Group': ['or-chess'],
        'WorkingDirectory': [str(APP)],
        'EnvironmentFile': ['/home/or-chess/.config/or-chess/service.env'],
    }
    if any(props.get(key) != value for key, value in required.items()):
        raise ValueError('Installed unit must use the isolated or-chess account and paths.')
    return props


def check_command(props, mode, check_id, *, live=False):
    if mode not in {'preflight', 'wire', 'live'} or (mode == 'live' and not live):
        raise ValueError('A live check requires explicit --live authorization.')
    command = ['systemd-run', '--quiet', '--collect', '--wait', '--pipe',
               '--service-type=exec', f'--unit=or-chess-check-{mode}-{check_id}']
    for key, values in props.items():
        command.append('--property=' + key + '=' + ' '.join(values))
    command.extend([str(APP / '.venv/bin/python'),
                    str(APP / 'tools/check_openrouter_service.py'), mode])
    if mode == 'live':
        command.append('--live')
    return command


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('preflight', 'wire', 'live'))
    parser.add_argument('--live', action='store_true', help='Authorize two paid model actions')
    args = parser.parse_args()
    if args.mode == 'live' and not args.live:
        parser.error('The live check requires --live.')
    if not hasattr(os, 'geteuid') or os.geteuid() != 0:
        parser.error('Run via sudo; the check executes as or-chess.')
    # Reading only the main file would miss changes made by a systemd drop-in.
    dropins = subprocess.run(['systemctl', 'show', 'or-chess.service',
                              '--property=DropInPaths', '--value'],
                             check=True, text=True, capture_output=True)
    if dropins.stdout.strip():
        parser.error('Unit drop-ins require reconciliation before copying service properties.')
    if args.mode == 'live' and subprocess.run(
            ['systemctl', 'is-active', '--quiet', 'or-chess.service'], check=False).returncode == 0:
        parser.error('Stop or-chess.service before the disposable paid check to avoid concurrent players.')
    try:
        props = service_properties(UNIT.read_text())
        command = check_command(props, args.mode, secrets.token_hex(5), live=args.live)
    except (OSError, ValueError):
        parser.error('Installed experimental unit could not be safely reused.')
    print(f'Starting {args.mode} check with installed or-chess service properties.', flush=True)
    return subprocess.run(command, check=False).returncode


if __name__ == '__main__':
    raise SystemExit(main())
