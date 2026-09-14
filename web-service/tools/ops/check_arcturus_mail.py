"""Explicit operator-only SMTP check against disposable app and monitor data.

Requires --live and an explicit recipient; sends three real test messages.
Reads the selected mail configuration and writes only a fresh private fixture
and receipt. It does not change either running chess application's settings.
"""
import argparse
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
from urllib.parse import parse_qs, urlsplit

ORIGIN = 'https://arcturuschess.com'
AUDIT = Path('/var/lib/arcturus-mail-check')
SOURCE_CONFIG = Path('/home/or-chess/.config/or-chess-monitor/config.json')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', type=Path, required=True)
    parser.add_argument('--recipient', required=True, help='Authorized recipient of the three real test emails.')
    parser.add_argument('--source-config', type=Path, default=SOURCE_CONFIG,
                        help='Private notification configuration supplying SMTP credentials.')
    parser.add_argument('--audit-dir', type=Path, default=AUDIT,
                        help='Private root-owned parent for disposable fixtures and receipts.')
    parser.add_argument('--live', action='store_true', help='Explicitly send the three test emails.')
    args = parser.parse_args()
    if not args.live:
        parser.error('--live is required because this check sends real emails')
    if sys.platform != 'linux' or os.geteuid() != 0:
        parser.error('this operator check requires Linux and root')
    assert args.stage.resolve().is_relative_to(Path('/home/or-chess/mail-staging'))
    os.umask(0o077)
    sys.path.insert(0, str(args.stage / 'web-service'))
    from astra_web.app import create_app
    from astra_web.config import Config, is_bare_email
    from fastapi.testclient import TestClient
    from tools.ops import notify_new_games as monitor
    monitor.protect_credentials()
    if not is_bare_email(args.recipient):
        parser.error('--recipient must be one bare email address')
    old_settings = json.loads(args.source_config.read_text())
    assert old_settings['recipient'] == args.recipient
    transport = old_settings['transport']
    assert (transport['type'], transport['host'], transport['port'], transport['security']) == (
        'smtp', 'email-smtp.us-west-2.amazonaws.com', 587, 'starttls')
    audit = args.audit_dir
    assert not audit.is_symlink()
    audit.mkdir(mode=0o700, parents=False, exist_ok=True)
    assert audit.is_dir() and audit.stat().st_uid == 0 and audit.stat().st_mode & 0o077 == 0
    report = dict(checkpoint_utc=datetime.now(timezone.utc).isoformat(timespec='seconds'),
        origin=ORIGIN, isolated_operator_fixture=True, paid_model_calls=0,
        smtp_accepted_messages=0, live_service_configuration_changed=False,
        real_player_data_opened=False, inbox_delivery_confirmed=False)
    name = 'Arcturus mail TEST - no action needed'
    password, new_password = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    try:
        with tempfile.TemporaryDirectory(prefix='fixture-', dir=audit) as directory:
            root = Path(directory)
            data, monitor_state = root / 'data', root / 'monitor-state'
            cfg = Config(data_dir=data, origin=ORIGIN, additional_origins=(),
                model_profile='openrouter-glm', persona='arcturus', player_mode='disabled',
                secure_cookies=True, smtp_host=transport['host'], smtp_port=transport['port'],
                smtp_from='accounts@arcturuschess.com', smtp_feedback_address=args.recipient,
                smtp_user=transport['username'], smtp_password=transport['password'])
            app = create_app(cfg)
            identity = app.state.identity
            delivered = {}
            real_send = identity._send_email
            def send(recipient, url, *, verification=False, name=None):
                assert recipient == args.recipient and urlsplit(url).scheme + '://' + urlsplit(url).netloc == ORIGIN
                kind = 'verify-email' if verification else 'reset'
                assert urlsplit(url).path == '/' and kind in parse_qs(urlsplit(url).fragment)
                try:
                    real_send(recipient, url, verification=verification, name=name)
                except Exception as error:
                    report['smtp_error_type'] = type(error).__name__
                    report['smtp_error_code'] = getattr(error, 'smtp_code', None)
                    raise
                delivered[kind] = url
                report['smtp_accepted_messages'] += 1
            identity._send_email = send
            monitor_config = dict(recipient=args.recipient, from_address='notifications@arcturuschess.com',
                feedback_address=args.recipient, site_name='Arcturus chess',
                subject_prefix='Arcturus chess delivery TEST', timezone='America/Chicago', transport=transport)
            config_path = root / 'monitor.json'
            config_path.write_text(json.dumps(monitor_config))
            with TestClient(app, base_url=ORIGIN) as client:
                def post(path, data, expected=200, csrf=None):
                    headers = {'Origin': ORIGIN}
                    if csrf:
                        headers['X-CSRF-Token'] = csrf
                    response = client.post(path, json=data, headers=headers)
                    assert response.status_code == expected, 'Unexpected disposable HTTP status at ' + path
                    return response
                registered = post('/api/auth/register', {'name':name, 'password':password, 'email':args.recipient}).json()
                started = time.monotonic()
                assert 'verify-email' in delivered, 'SES did not accept verification email'
                print(json.dumps({'progress':'Verification email accepted; exercising its disposable account token.'}), flush=True)
                verify_token = parse_qs(urlsplit(delivered['verify-email']).fragment)['verify-email'][0]
                assert not client.get('/api/auth/recovery').json()['verified']
                post('/api/auth/verify-email', {'token':verify_token})
                post('/api/auth/verify-email', {'token':verify_token}, expected=400)
                assert client.get('/api/auth/recovery').json()['verified']
                report['verification_http_lifecycle_passed'] = True
                initialized = monitor.run(data, monitor_state, initialize=True)
                assert initialized['baseline_games'] == 0
                post('/api/games', {'side':'white'}, expected=201, csrf=registered['csrf_token'])
                def monitor_send(encoded, config):
                    message = BytesParser(policy=policy.default).parsebytes(encoded)
                    assert str(message['From']) == 'notifications@arcturuschess.com'
                    assert str(message['To']) == args.recipient and str(message['Return-Path']) == args.recipient
                    assert '@arcturuschess.com>' in str(message['Message-ID'])
                    assert 'TEST' in str(message['Subject']) and 'New Arcturus chess games' in message.get_content()
                    monitor.handoff(encoded, config)
                    report['smtp_accepted_messages'] += 1
                # Respect SES's one-message-per-second sandbox quota.
                time.sleep(2)
                sent = monitor.run(data, monitor_state, config_path=config_path, sender=monitor_send)
                assert sent['sent'] and sent['new_games'] == 1
                quiet = monitor.run(data, monitor_state, config_path=config_path, sender=monitor_send)
                assert quiet == dict(sent=False, new_games=0)
                report['notification_delivery_and_no_news_passed'] = True
                print(json.dumps({'progress':'Synthetic game-monitor email accepted; waiting for the real recovery cooldown.'}), flush=True)
                while time.monotonic() - started < 63:
                    time.sleep(min(10, 63 - (time.monotonic() - started)))
                post('/api/auth/forgot', {'name':name})
                assert 'reset' in delivered, 'SES did not accept reset email'
                reset_token = parse_qs(urlsplit(delivered['reset']).fragment)['reset'][0]
                old_session = client.cookies.get('astra_session')
                post('/api/auth/reset', {'token':reset_token, 'password':new_password})
                assert identity.user_for_token(old_session) is None
                post('/api/auth/reset', {'token':reset_token, 'password':password}, expected=400)
                post('/api/auth/login', {'name':name, 'password':password}, expected=401)
                signed_in = post('/api/auth/login', {'name':name, 'password':new_password}).json()
                assert signed_in['user']['id'] == registered['user']['id']
                assert len(client.get('/api/games').json()['games']) == 1
                report['reset_http_lifecycle_passed'] = True
                report['saved_fixture_game_preserved'] = True
            report['canonical_links_verified'] = all(value.startswith(ORIGIN + '/#') for value in delivered.values())
        report['disposable_credentials_accounts_tokens_cleaned'] = True
        report['success'] = True
    except Exception as error:
        report['success'] = False
        report['error_type'] = type(error).__name__
    receipt = audit / ('receipt-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '.json')
    receipt.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2), flush=True)
    return 0 if report['success'] else 1

if __name__ == '__main__':
    raise SystemExit(main())
