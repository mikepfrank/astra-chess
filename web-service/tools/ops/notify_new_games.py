"""Send one bounded new-game digest per operator-scheduled run, without models.

Initialize once before enabling a scheduler. The source database is read-only;
the separate private state directory holds reported IDs and a durable pending
message. A successful mail handoff followed by a state-write crash can duplicate
a message on retry: this deliberately does not claim exactly-once delivery.
"""
import argparse
import base64
from contextlib import contextmanager
from datetime import datetime, timezone
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import format_datetime
import json
import math
import os
from pathlib import Path
import re
import smtplib
import sqlite3
import ssl
import subprocess
import sys
import uuid


APP_ROOT = Path(__file__).resolve().parents[2]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))
from tools.ops.report_games import _stamp, _zone, read_database


MAX_BATCH_GAMES = 100
MAX_MESSAGE_BYTES = 64_000
MAX_STATE_BYTES = 64_000_000
TOKEN = re.compile(r'[0-9a-f]{32}')
ADDRESS = re.compile(r'[A-Za-z0-9][A-Za-z0-9._%+\-]*@[A-Za-z0-9](?:[A-Za-z0-9.\-]*[A-Za-z0-9])?')


class MonitorError(ValueError):
    pass


def _address(value):
    if not isinstance(value, str) or len(value) > 254 or ADDRESS.fullmatch(value) is None:
        raise MonitorError('Use one bare ASCII email address for each recipient/sender setting; display names and multiple recipients are not accepted.')
    return value


def _private_file(path):
    if path.is_symlink() or not path.is_file():
        raise MonitorError('Monitor files must be ordinary files, not symbolic links.')
    if os.name == 'posix':
        details = path.stat()
        if details.st_uid != os.getuid() or details.st_mode & 0o077:
            raise MonitorError('Monitor configuration/state files must belong to the current user and be mode 0600 or stricter.')


def protect_credentials():
    """Prevent same-UID /proc memory inspection before loading Linux secrets."""
    if sys.platform == 'linux':
        import ctypes
        try:
            libc = ctypes.CDLL(None, use_errno=True)
            if libc.prctl(4, 0, 0, 0, 0) != 0:  # PR_SET_DUMPABLE = 4
                raise OSError(ctypes.get_errno(), 'prctl failed')
        except (AttributeError, OSError):
            raise MonitorError('Unable to disable process dumps before loading mail credentials.') from None


def load_config(path):
    protect_credentials()
    path = Path(path).expanduser().absolute()
    _private_file(path)
    try:
        if path.stat().st_size > 16_384:
            raise MonitorError('Monitor configuration is too large.')
        config = json.loads(path.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, UnicodeError):
        raise MonitorError('Monitor configuration must be a JSON object.') from None
    if not isinstance(config, dict) or set(config) - {'recipient', 'from_address', 'timezone', 'subject_prefix', 'transport'}:
        raise MonitorError('Unsupported monitor configuration fields.')
    for key in ('recipient', 'from_address'):
        config[key] = _address(config.get(key))
    prefix = config.get('subject_prefix', 'Astra chess')
    if not isinstance(prefix, str) or not 1 <= len(prefix) <= 80 or any(not c.isprintable() for c in prefix):
        raise MonitorError('The subject prefix must be one printable line of at most 80 characters.')
    config['subject_prefix'] = prefix
    config['timezone'] = config.get('timezone', 'UTC')
    if not isinstance(config['timezone'], str):
        raise MonitorError('Configure a timezone name as text.')
    _zone(config['timezone'])
    transport = config.get('transport')
    if not isinstance(transport, dict):
        raise MonitorError('Configure an SMTP or sendmail transport.')
    if transport.get('type') == 'sendmail':
        if set(transport) != {'type', 'path'} or not isinstance(transport['path'], str) or not Path(transport['path']).is_absolute():
            raise MonitorError('The sendmail transport requires one absolute executable path.')
    elif transport.get('type') == 'smtp':
        if set(transport) - {'type', 'host', 'port', 'security', 'username', 'password'}:
            raise MonitorError('Unsupported SMTP settings.')
        host = transport.get('host')
        if not isinstance(host, str) or not host or len(host) > 255 or any(c.isspace() for c in host):
            raise MonitorError('Configure an SMTP hostname without whitespace.')
        if type(transport.get('port')) is not int or not 1 <= transport['port'] <= 65535:
            raise MonitorError('Configure an SMTP port between 1 and 65535.')
        if transport.get('security') not in ('tls', 'starttls'):
            raise MonitorError('SMTP requires tls or starttls; plaintext SMTP is not supported.')
        username = transport.get('username')
        if username is not None and (not isinstance(username, str) or not username or '\r' in username or '\n' in username):
            raise MonitorError('Configure a valid SMTP username.')
        if username is not None and 'password' not in transport:
            raise MonitorError('The configured SMTP username needs a password setting.')
        if username is None and 'password' in transport:
            raise MonitorError('An SMTP password requires a username.')
        if 'password' in transport and (not isinstance(transport['password'], str) or not transport['password']):
            raise MonitorError('Configure a nonempty SMTP password.')
    else:
        raise MonitorError('Configure an SMTP or sendmail transport.')
    return config


def _state_directory(data_dir, state_dir, *, initialize):
    source = Path(data_dir).expanduser().resolve(strict=True)
    requested = Path(state_dir).expanduser().absolute()
    if requested.is_symlink() or getattr(requested, 'is_junction', lambda: False)():
        raise MonitorError('The monitor state directory must not be a symbolic link or junction.')
    directory = requested.resolve()
    if directory == source or directory.is_relative_to(source) or source.is_relative_to(directory):
        raise MonitorError('Use a separate monitor state directory outside the service data directory and its ancestors.')
    if not directory.exists():
        if not initialize:
            raise MonitorError('Initialize this monitor before enabling notifications.')
        directory.mkdir(mode=0o700, parents=False)
    if not directory.is_dir():
        raise MonitorError('Monitor state must be a directory.')
    if os.name == 'posix':
        details = directory.stat()
        if details.st_uid != os.getuid() or details.st_mode & 0o077:
            raise MonitorError('The monitor state directory must belong to the current user and be mode 0700 or stricter.')
    return source, directory


@contextmanager
def execution_lock(directory):
    path = directory / 'monitor.lock'
    if path.is_symlink():
        raise MonitorError('The monitor lock must not be a symbolic link.')
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    stream = os.fdopen(descriptor, 'r+b', buffering=0)
    acquired = False
    try:
        if os.name == 'nt':
            import msvcrt
            if path.stat().st_size == 0:
                stream.write(b'0')
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise MonitorError('Another notification run is already active.') from None
        elif os.name == 'posix':
            import fcntl
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise MonitorError('Another notification run is already active.') from None
        else:
            raise MonitorError('This platform does not provide a supported monitor lock.')
        acquired = True
        yield
    finally:
        if acquired:
            if os.name == 'nt':
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            elif os.name == 'posix':
                fcntl.flock(stream, fcntl.LOCK_UN)
        stream.close()


def _write_state(directory, state):
    path = directory / 'state.json'
    if path.is_symlink():
        raise MonitorError('The monitor state file must not be a symbolic link.')
    temporary = directory / ('.state-' + uuid.uuid4().hex + '.tmp')
    encoded = json.dumps(state, sort_keys=True, separators=(',', ':')).encode()
    if len(encoded) > MAX_STATE_BYTES:
        raise MonitorError('Monitor state is too large; retain it and review its archive policy.')
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name == 'posix':
            descriptor = os.open(directory, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def _read_state(directory):
    path = directory / 'state.json'
    if not path.exists():
        raise MonitorError('Initialize this monitor before enabling notifications.')
    _private_file(path)
    try:
        if path.stat().st_size > MAX_STATE_BYTES:
            raise MonitorError('Monitor state exceeds the supported size.')
        state = json.loads(path.read_text(encoding='utf-8'))
        if (state.get('schema_version') != 1 or not isinstance(state.get('reported_ids'), list)
                or any(not isinstance(value, str) or TOKEN.fullmatch(value) is None for value in state['reported_ids'])
                or state.get('pending') is not None and not isinstance(state['pending'], dict)):
            raise MonitorError('Monitor state is malformed; do not reinitialize it over existing records.')
        return state
    except (json.JSONDecodeError, UnicodeError, AttributeError):
        raise MonitorError('Monitor state is malformed; do not reinitialize it over existing records.') from None


def _text(value, limit):
    if not isinstance(value, str):
        return 'Unknown'
    return ''.join(c if c.isprintable() else ' ' for c in value)[:limit] or 'Unknown'


def _games(data_dir):
    games = []
    with read_database(data_dir) as db:
        for row in db.execute('SELECT id,state FROM games'):
            if not isinstance(row['id'], str) or TOKEN.fullmatch(row['id']) is None:
                raise MonitorError('A game record has an invalid identifier; no notifications were advanced.')
            try:
                state = json.loads(row['state'])
                created = state.get('created_at')
                created = created if type(created) in (int, float) and math.isfinite(created) else None
                moves = state.get('moves', [])
                games.append(dict(id=row['id'], name=_text(state.get('name'), 80),
                                  human_side=state.get('human_side') if state.get('human_side') in ('white', 'black') else 'unknown',
                                  created_at=created, status=_text(state.get('status'), 30),
                                  last_move=(f"{(len(moves) + 1) // 2}{'.' if len(moves) % 2 else '…'} " +
                                             _text(moves[-1].get('san'), 20)) if moves else 'No moves yet'))
            except (ValueError, TypeError, AttributeError, IndexError):
                raise MonitorError('A game record is malformed; no notifications were advanced.') from None
    return sorted(games, key=lambda game: (game['created_at'] or 0, game['id']))


def _queue(games, config, now, *, batch_limit=MAX_BATCH_GAMES):
    selected = games[:batch_limit]
    overflow = len(games) - len(selected)
    zone = _zone(config['timezone'])
    snapshot = now.astimezone(timezone.utc).isoformat(timespec='seconds')
    lines = [f"New Astra chess games — snapshot {snapshot}", '']
    for index, game in enumerate(selected, 1):
        lines.extend([f"{index}. {game['name']} — playing {game['human_side']}",
                      f"   Started: {_stamp(game['created_at'], zone) or 'Unknown'}",
                      f"   Status: {game['status']}; last move: {game['last_move']}",
                      f"   Game ID: {game['id']}", ''])
    if overflow:
        lines.extend([f'{overflow} additional new games remain queued for later scheduled digests; their IDs are not marked reported.', ''])
    lines.append('Game status is the state saved at the snapshot above; it does not establish whether a player is currently online.')
    body = '\n'.join(lines) + '\n'
    message = EmailMessage(policy=SMTP)
    message['From'], message['To'] = config['from_address'], config['recipient']
    message['Subject'] = f"{config['subject_prefix']}: {len(selected)} new game{'s' if len(selected) != 1 else ''}"
    message['Date'] = format_datetime(now.astimezone(timezone.utc))
    message_id = '<' + uuid.uuid4().hex + '@' + config['from_address'].split('@')[1] + '>'
    message['Message-ID'] = message_id
    message.set_content(body)
    encoded = message.as_bytes()
    if len(encoded) > MAX_MESSAGE_BYTES:
        if len(selected) > 1:
            return _queue(games, config, now, batch_limit=len(selected) // 2)
        raise MonitorError('Digest exceeds its size bound; retain the checkpoint and reduce the configured batch size in code.')
    return dict(ids=[game['id'] for game in selected], recipient=config['recipient'], from_address=config['from_address'],
                message_id=message_id, message=base64.b64encode(encoded).decode('ascii'),
                body=body, queued_at=snapshot, overflow=overflow)


def _pending_bytes(pending, config):
    if pending.get('recipient') != config['recipient'] or pending.get('from_address') != config['from_address']:
        raise MonitorError('The queued digest sender/recipient differs from current settings. Restore the intended settings or review the private queue before proceeding.')
    if (not isinstance(pending.get('ids'), list) or not pending['ids'] or len(pending['ids']) > MAX_BATCH_GAMES
            or any(not isinstance(value, str) or TOKEN.fullmatch(value) is None for value in pending['ids'])):
        raise MonitorError('The queued digest has invalid game identifiers; retain the state for review.')
    try:
        encoded = base64.b64decode(pending['message'], validate=True)
    except (KeyError, TypeError, ValueError):
        raise MonitorError('The queued digest bytes are invalid; retain the state for review.') from None
    if len(encoded) > MAX_MESSAGE_BYTES:
        raise MonitorError('The queued digest exceeds its size limit.')
    return encoded


def handoff(encoded, config):
    transport = config['transport']
    if transport['type'] == 'sendmail':
        subprocess.run([transport['path'], '-i', '--', config['recipient']], input=encoded,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=45, check=True)
        return
    context = ssl.create_default_context()
    smtp_class = smtplib.SMTP_SSL if transport['security'] == 'tls' else smtplib.SMTP
    arguments = {'timeout': 45}
    if transport['security'] == 'tls':
        arguments['context'] = context
    with smtp_class(transport['host'], transport['port'], **arguments) as smtp:
        smtp.ehlo()
        if transport['security'] == 'starttls':
            smtp.starttls(context=context)
            smtp.ehlo()
        if transport.get('username'):
            password = transport.get('password')
            if not password:
                raise MonitorError('The configured SMTP password is unavailable.')
            smtp.login(transport['username'], password)
        refused = smtp.sendmail(config['from_address'], [config['recipient']], encoded)
        if refused:
            raise MonitorError('The configured recipient was not accepted by the mail server.')


def run(data_dir, state_dir, *, config_path=None, initialize=False, dry_run=False, sender=None, now=None):
    if initialize and dry_run:
        raise MonitorError('Choose initialization or a dry run, not both.')
    config = load_config(config_path) if config_path is not None else None
    if not initialize and config is None:
        raise MonitorError('A private configuration file is required for delivery or dry runs.')
    if config is None:
        # Baseline initialization also holds a writable private state descriptor.
        protect_credentials()
    source, directory = _state_directory(data_dir, state_dir, initialize=initialize)
    now = now or datetime.now(timezone.utc)
    if dry_run:
        # Atomic state replacement permits a coherent read without creating a
        # lock file or advancing anything. A simultaneous delivery may make this
        # read-only preview obsolete; it never participates in mail delivery.
        state = _read_state(directory)
        reported = set(state['reported_ids'])
        games = [game for game in _games(source) if game['id'] not in reported]
        pending = state.get('pending') or (_queue(games, config, now) if games else None)
        if pending is not None:
            _pending_bytes(pending, config)
        return dict(dry_run=True, games=len(pending['ids']) if pending else 0,
                    preview=pending['body'] if pending else None, overflow=pending['overflow'] if pending else 0)
    with execution_lock(directory):
        if initialize:
            if (directory / 'state.json').exists():
                raise MonitorError('This monitor is already initialized; refusing to overwrite its reporting history.')
            games = _games(source)
            _write_state(directory, dict(schema_version=1, initialized_at=now.isoformat(),
                                        reported_ids=sorted(game['id'] for game in games), pending=None, last_success_at=None))
            return dict(initialized=True, baseline_games=len(games))
        state = _read_state(directory)
        pending = state.get('pending')
        if pending is None:
            reported = set(state['reported_ids'])
            games = [game for game in _games(source) if game['id'] not in reported]
            if not games:
                return dict(sent=False, new_games=0)
            pending = _queue(games, config, now)
            state['pending'] = pending
            _write_state(directory, state)
        encoded = _pending_bytes(pending, config)
        try:
            (sender or handoff)(encoded, config)
        except Exception:
            raise MonitorError('Mail handoff failed; the pending digest is retained for retry.') from None
        state['reported_ids'] = sorted(set(state['reported_ids']) | set(pending['ids']))
        state['pending'], state['last_success_at'] = None, now.isoformat()
        try:
            _write_state(directory, state)
        except Exception:
            raise MonitorError('Mail was handed off, but its state checkpoint failed. A later retry may send the same Message-ID again.') from None
        return dict(sent=True, new_games=len(pending['ids']), overflow=pending['overflow'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--state-dir', type=Path, required=True)
    parser.add_argument('--config', type=Path, help='Private JSON mail settings; not needed for initialization')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--initialize', action='store_true', help='Baseline existing game IDs without sending historical mail')
    modes.add_argument('--dry-run', action='store_true', help='Preview a digest without mail or state writes')
    args = parser.parse_args(argv)
    try:
        result = run(args.data_dir, args.state_dir, config_path=args.config, initialize=args.initialize, dry_run=args.dry_run)
    except (MonitorError, OSError, sqlite3.Error, ValueError) as error:
        parser.exit(1, str(error) + '\n')
    if result.get('sent') is not False:  # Scheduled no-news runs stay quiet.
        print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
