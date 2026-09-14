"""Audit the installed Arcturus notifier's Linux namespace using private fixtures.

Creates a bounded transient unit, reads the live game inventory, and checks
that application processes and notification baselines remain unchanged. No
email is sent unless --send-test-email and an explicit --recipient are supplied.
Never run this as part of ordinary unit-test discovery.
"""
import argparse
import collections
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
import time


APP = Path('/home/or-chess/astra-chess/web-service')
DATA = Path('/home/or-chess/.local/share/or-chess')
STATE = Path('/home/or-chess/.local/state/or-chess-monitor')
CONFIG = Path('/home/or-chess/.config/or-chess-monitor/config.json')
UNIT_FILE = Path('/etc/systemd/system/or-chess-game-notify.service')
UNIT = None
PYTHON = str(APP / '.venv/bin/python')
CHECK = None


def services():
    return subprocess.run(['systemctl', 'show', 'or-chess.service', 'astra-chess.service',
        'astra-caddy.service', '--property=Id,MainPID,ActiveState'],
        check=True, text=True, capture_output=True).stdout


def properties():
    result = collections.defaultdict(list)
    in_service = False
    for raw in UNIT_FILE.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith(('#', ';')):
            continue
        if line.startswith('['):
            in_service = line == '[Service]'
        elif in_service:
            key, value = line.split('=', 1)
            if key not in ('Type', 'ExecStart', 'Restart'):
                result[key].append(value)
    assert result['User'] == result['Group'] == ['or-chess']
    assert not result.get('EnvironmentFile')
    assert result['WorkingDirectory'] == [str(APP)]
    assert result['MemoryMax'] == ['128M'] and result['CPUQuota'] == ['10%']
    assert result['TasksMax'] == ['16'] and result['TimeoutStartSec'] == ['120']
    result['RuntimeMaxSec'] = ['120']
    result['TimeoutStopSec'] = ['10']
    return result


INNER = r'''import hashlib, json, os, pathlib, sqlite3, sys
from datetime import datetime, timezone
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import format_datetime, make_msgid
from tools.ops.notify_new_games import handoff, load_config
from tools.ops.report_games import read_database, _zone
root, data, state, config_path = map(pathlib.Path, sys.argv[1:5])
send_test_email = sys.argv[5] == '1'
expected_recipient = sys.argv[6]
baseline_hash = hashlib.sha256(state.read_bytes()).hexdigest()
result = {'checks_passed': False, 'mail_requested': send_test_email, 'mail_accepted': False}
def must_hide(path):
    assert not os.access(path, os.R_OK), 'Unexpected readable private path: ' + str(path)
for path in (data / 'players', data / 'games', data / 'operator-checks',
             data / 'replay-archives', data / 'public-replays',
             data / 'openrouter-budget.json', data / 'openrouter-budget.json.lock',
             pathlib.Path('/home/or-chess/.config/or-chess/service.env')):
    must_hide(path)
assert not set(os.environ) & {'OPENAI_API_KEY', 'CODEX_API_KEY', 'OPENROUTER_API_KEY', 'CHESS_GATEWAY_TOKEN'}
result['private_paths_and_model_credentials_hidden'] = True
for source in (data, root / 'wal-absent', root / 'wal-active'):
    try:
        descriptor = os.open(source / 'astra.sqlite3', os.O_WRONLY)
    except OSError as error:
        assert error.errno in (13, 30), 'Unexpected main DB denial'
    else:
        os.close(descriptor)
        raise AssertionError('Main database is writable in notifier namespace')
    with read_database(source) as db:
        if source == data:
            result['source_game_count'] = db.execute('SELECT COUNT(*) FROM games').fetchone()[0]
        else:
            expected = 101 if source.name == 'wal-absent' else 202
            assert db.execute('SELECT value FROM probe').fetchone()[0] == expected
            try:
                db.execute('UPDATE probe SET value=0')
            except sqlite3.OperationalError:
                pass
            else:
                raise AssertionError('Probe connection unexpectedly accepted a write')
result['source_and_both_wal_modes_readable_with_main_db_readonly'] = True
config = load_config(config_path)
if expected_recipient:
    assert config['recipient'] == expected_recipient
assert config['from_address'] == 'notifications@arcturuschess.com'
assert config['timezone'] == 'America/Chicago'
_zone(config['timezone'])
result['timezone'] = config['timezone']
relative = next(line.split(':', 2)[2] for line in pathlib.Path('/proc/self/cgroup').read_text().splitlines() if line.startswith('0::'))
cgroup = pathlib.Path('/sys/fs/cgroup') / relative.lstrip('/')
limits = {key: (cgroup / key).read_text().strip() for key in ('cpu.max', 'memory.max', 'pids.max')}
assert limits == {'cpu.max': '10000 100000', 'memory.max': '134217728', 'pids.max': '16'}
result.update(limits=limits, checks_passed=True, notifier_uid=os.getuid())
assert hashlib.sha256(state.read_bytes()).hexdigest() == baseline_hash
try:
    if send_test_email:
        assert expected_recipient and config['recipient'] == expected_recipient
        message = EmailMessage(policy=SMTP)
        message['From'] = config['from_address']
        message['To'] = expected_recipient
        message['Subject'] = 'Arcturus monitor activation TEST - no action required'
        message['Date'] = format_datetime(datetime.now(timezone.utc))
        message['Message-ID'] = make_msgid(domain='arcturuschess.com')
        message.set_content('This is one synthetic test of the Arcturus chess new-game notification channel.\n\nNo actual new games are being reported by this test, no game was created, and the existing notification baseline is unchanged.\n\nNo action is required.\n')
        attempt = root / 'test-mail-attempted.json'
        with attempt.open('x', encoding='utf-8') as stream:
            json.dump({'message_id': message['Message-ID'], 'subject': message['Subject'], 'attempted_at': datetime.now(timezone.utc).isoformat()}, stream)
        result['message_id'] = message['Message-ID']
        handoff(message.as_bytes(), config)
        result['mail_accepted'] = True
finally:
    result['baseline_unchanged'] = hashlib.sha256(state.read_bytes()).hexdigest() == baseline_hash
    result['baseline_games'] = len(json.loads(state.read_bytes())['reported_ids'])
    (root / 'namespace-mail-receipt.json').write_text(json.dumps(result, indent=2) + '\n')
assert result['baseline_unchanged']
print(json.dumps(result, indent=2))
'''


def main():
    global APP, DATA, STATE, CONFIG, UNIT_FILE, UNIT, PYTHON, CHECK
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app-dir', type=Path, default=APP)
    parser.add_argument('--data-dir', type=Path, default=DATA)
    parser.add_argument('--state-dir', type=Path, default=STATE)
    parser.add_argument('--config', type=Path, default=CONFIG,
                        help='Private notifier configuration; its baseline remains unchanged.')
    parser.add_argument('--unit-file', type=Path, default=UNIT_FILE,
                        help='Reviewed notifier unit whose service restrictions are reproduced.')
    parser.add_argument('--check-dir', type=Path,
                        help='New private directory under --state-dir; a unique name is the default.')
    parser.add_argument('--send-test-email', action='store_true',
                        help='Explicitly send one synthetic email after namespace checks pass.')
    parser.add_argument('--recipient', help='Authorized recipient; required with --send-test-email.')
    args = parser.parse_args()
    if args.send_test_email and not args.recipient:
        parser.error('--send-test-email requires an explicit --recipient')
    if sys.platform != 'linux' or os.geteuid() != 0:
        parser.error('this namespace audit requires Linux and root')
    import pwd
    APP, DATA, STATE, CONFIG, UNIT_FILE = (
        path.resolve() for path in (args.app_dir, args.data_dir, args.state_dir, args.config, args.unit_file))
    PYTHON = str(APP / '.venv/bin/python')
    suffix = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()) + '-' + secrets.token_hex(4)
    UNIT = 'or-chess-notifier-check-' + suffix.lower()
    CHECK = args.check_dir or STATE / ('namespace-check-' + suffix)
    if CHECK.is_symlink() or CHECK.exists():
        parser.error('--check-dir must be a new directory')
    CHECK = CHECK.resolve()
    if not CHECK.is_relative_to(STATE) or CHECK == STATE:
        parser.error('--check-dir must be a new child of --state-dir')
    os.umask(0o077)
    before = services()
    state_before = hashlib.sha256((STATE / 'state.json').read_bytes()).hexdigest()
    account = pwd.getpwnam('or-chess')
    CHECK.mkdir(mode=0o700, exist_ok=False)
    os.chown(CHECK, account.pw_uid, account.pw_gid)
    active_db = None
    fixture_hashes = {}
    props = properties()
    for name, value in (('wal-absent', 101), ('wal-active', 202)):
        folder = CHECK / name
        folder.mkdir(mode=0o700)
        os.chown(folder, account.pw_uid, account.pw_gid)
        db = sqlite3.connect(folder / 'astra.sqlite3')
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('CREATE TABLE probe(value INTEGER)')
        db.execute('INSERT INTO probe VALUES(?)', (value,))
        db.commit()
        if name == 'wal-absent':
            db.close()
            assert not (folder / 'astra.sqlite3-wal').exists()
        else:
            active_db = db
            assert (folder / 'astra.sqlite3-wal').stat().st_size > 0
        for file in folder.iterdir():
            os.chown(file, account.pw_uid, account.pw_gid)
            file.chmod(0o600)
        fixture_hashes[name] = hashlib.sha256((folder / 'astra.sqlite3').read_bytes()).hexdigest()
        props['ReadOnlyPaths'].append(str(folder / 'astra.sqlite3'))
    live_pid = subprocess.run(['systemctl', 'show', 'or-chess.service', '--property=MainPID', '--value'], check=True, capture_output=True, text=True).stdout.strip()
    namespace_check = "import os; os.setgid(%d); os.setuid(%d); assert not any(os.access(p, os.R_OK) for p in (%r, %r)); print('mail configuration and state hidden from live game namespace')" % (account.pw_gid, account.pw_uid, str(CONFIG), str(STATE))
    visible = subprocess.run(['nsenter', '-t', live_pid, '-m', '--', PYTHON, '-c', namespace_check], check=True, capture_output=True, text=True)
    print(visible.stdout.strip())
    command = ['systemd-run', '--quiet', '--collect', '--wait', '--pipe', '--service-type=oneshot', '--unit=' + UNIT]
    command += ['--property=' + key + '=' + ' '.join(values) for key, values in props.items()]
    command += [PYTHON, '-c', INNER, str(CHECK), str(DATA), str(STATE / 'state.json'),
                str(CONFIG), '1' if args.send_test_email else '0', args.recipient or '']
    result = None
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=150)
        print(result.stdout[-10000:])
        if result.returncode:
            print(result.stderr[-4000:])
    finally:
        subprocess.run(['systemctl', 'stop', UNIT], capture_output=True, text=True, timeout=20, check=False)
        final_state = subprocess.run(['systemctl', 'is-active', UNIT], capture_output=True, text=True).stdout.strip()
        after = services()
        fixture_unchanged = all(hashlib.sha256((CHECK / name / 'astra.sqlite3').read_bytes()).hexdigest() == digest for name, digest in fixture_hashes.items())
        receipt = {'transient_returncode': None if result is None else result.returncode,
            'transient_final_state': final_state, 'source_fixture_db_bytes_unchanged': fixture_unchanged,
            'mail_state_hidden_from_live_game_namespace': True,
            'baseline_unchanged': hashlib.sha256((STATE / 'state.json').read_bytes()).hexdigest() == state_before,
            'services_unchanged': before == after, 'services_before': before, 'services_after': after}
        (CHECK / 'outer-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
        print(json.dumps(receipt, indent=2))
        if active_db:
            active_db.close()
        assert final_state not in ('active', 'activating', 'deactivating')
        assert all(receipt[key] for key in ('source_fixture_db_bytes_unchanged', 'baseline_unchanged', 'services_unchanged'))
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
