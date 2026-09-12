"""Notification monitor behavior with fake transports; no mail or model calls."""
from contextlib import closing, redirect_stdout
from datetime import datetime, timezone
from email import message_from_bytes
from email.policy import default
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from tools.ops import notify_new_games as monitor


class NewGameMonitorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source, self.state = self.root / 'source', self.root / 'monitor-state'
        self.source.mkdir()
        with closing(sqlite3.connect(self.source / 'astra.sqlite3')) as db:
            db.execute('CREATE TABLE games(id TEXT PRIMARY KEY,state TEXT)')
            db.commit()
        self.config = dict(recipient='owner@example.com', from_address='notify@example.com', timezone='UTC',
                           transport=dict(type='smtp', host='smtp.example.com', port=587, security='starttls',
                                          username='SMTP USER', password='PRIVATE SMTP PASSWORD'))
        self.config_path = self.root / 'monitor.json'
        self.write_config()
        self.now = datetime(2026, 9, 12, 15, 0, tzinfo=timezone.utc)
        protection = patch.object(monitor, 'protect_credentials')
        self.protect = protection.start()
        self.addCleanup(protection.stop)
        self.sent = []

    def write_config(self):
        self.config_path.write_text(json.dumps(self.config), encoding='utf-8')
        self.config_path.chmod(0o600)

    def game(self, number, *, name='Player', created=1000.0, **changes):
        game_id = f'{number:032x}'
        state = dict(id=game_id, name=name, created_at=created, human_side='white', status='active',
                     moves=[{'san': 'e4'}], messages=[{'text': 'PRIVATE CHAT'}], user_id='PRIVATE ACCOUNT',
                     thread_id='PRIVATE CODEX THREAD', email='PLAYER ADDRESS', auth_token='PRIVATE TOKEN')
        state.update(changes)
        with closing(sqlite3.connect(self.source / 'astra.sqlite3')) as db:
            db.execute('INSERT OR REPLACE INTO games VALUES(?,?)', (game_id, json.dumps(state)))
            db.commit()
        return game_id

    def initialize(self):
        return monitor.run(self.source, self.state, initialize=True, now=self.now)

    def send(self, encoded, config):
        self.sent.append(encoded)

    def run_monitor(self, **options):
        return monitor.run(self.source, self.state, config_path=self.config_path, now=self.now,
                           sender=options.pop('sender', self.send), **options)

    def saved(self):
        return json.loads((self.state / 'state.json').read_text())

    def test_initialize_without_mail_config_baselines_existing_ids_and_quiet_run(self):
        ids = [self.game(1), self.game(2)]
        self.assertEqual(self.initialize(), {'initialized': True, 'baseline_games': 2})
        self.protect.assert_called_once()
        before = (self.state / 'state.json').read_bytes()
        self.assertEqual(self.saved()['reported_ids'], ids)
        self.assertEqual(self.run_monitor(), {'sent': False, 'new_games': 0})
        self.assertEqual(self.sent, [])
        self.assertEqual((self.state / 'state.json').read_bytes(), before)
        with self.assertRaisesRegex(monitor.MonitorError, 'already initialized'):
            self.initialize()
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(monitor.main(['--data-dir', str(self.source), '--state-dir', str(self.state),
                                          '--config', str(self.config_path)]), 0)
        self.assertEqual(output.getvalue(), '')

    def test_new_ids_with_same_timestamp_are_reported_once_and_existing_updates_ignored(self):
        original = self.game(1, created=1000)
        self.initialize()
        second, third = self.game(2, created=1000), self.game(3, created=1000, human_side='black')
        self.game(1, created=1000, status='finished')
        result = self.run_monitor()
        self.assertEqual(result, {'sent': True, 'new_games': 2, 'overflow': 0})
        message = message_from_bytes(self.sent[0], policy=default)
        body = message.get_content()
        self.assertIn(second, body)
        self.assertIn(third, body)
        self.assertNotIn(original, body)
        self.assertIn('playing black', body)
        self.assertEqual(set(self.saved()['reported_ids']), {original, second, third})
        self.assertFalse(self.run_monitor()['sent'])
        self.assertEqual(len(self.sent), 1)

    def test_failure_retry_freezes_message_id_and_batch_then_reports_later_games(self):
        self.initialize()
        first = self.game(1)
        attempted = []
        def failing(encoded, config):
            attempted.append(encoded)
            raise RuntimeError('PRIVATE SMTP PASSWORD')
        with self.assertRaisesRegex(monitor.MonitorError, 'pending digest is retained') as failure:
            self.run_monitor(sender=failing)
        self.assertNotIn('PRIVATE SMTP PASSWORD', str(failure.exception))
        pending = self.saved()['pending']
        self.assertEqual(self.saved()['reported_ids'], [])
        later = self.game(2)
        # A later invocation restores its durable queue; no in-process cursor is needed.
        self.assertEqual(self.run_monitor()['new_games'], 1)
        self.assertEqual(self.sent[0], attempted[0])
        self.assertIn(pending['message_id'].encode(), self.sent[0])
        self.assertEqual(self.saved()['reported_ids'], [first])
        self.assertEqual(self.run_monitor()['new_games'], 1)
        self.assertIn(later.encode(), self.sent[1])

    def test_dry_run_does_not_create_lock_or_change_state_or_send_mail(self):
        self.initialize()
        self.game(1)
        lock = self.state / 'monitor.lock'
        lock.unlink()
        before = (self.state / 'state.json').read_bytes()
        preview = self.run_monitor(dry_run=True)
        self.assertTrue(preview['dry_run'])
        self.assertEqual(preview['games'], 1)
        self.assertIn('Player', preview['preview'])
        self.assertFalse(lock.exists())
        self.assertEqual((self.state / 'state.json').read_bytes(), before)
        self.assertEqual(self.sent, [])

    def test_digest_has_bounded_plain_text_and_no_private_game_or_config_details(self):
        self.initialize()
        self.game(1, name='Guest\r\nBcc: victim@example.com <script>' + 'X' * 1000,
                  status='active\nInjected status', moves=[{'san': 'e4\nInjected SAN'}])
        self.run_monitor()
        encoded = self.sent[0]
        message = message_from_bytes(encoded, policy=default)
        self.assertEqual(message.get_content_type(), 'text/plain')
        self.assertEqual(message['To'], 'owner@example.com')
        self.assertIsNone(message['Bcc'])
        self.assertEqual(len(message.get_all('From')), 1)
        for secret in ('PRIVATE CHAT', 'PRIVATE ACCOUNT', 'PRIVATE CODEX THREAD', 'PRIVATE TOKEN',
                       'PLAYER ADDRESS', 'PRIVATE SMTP PASSWORD', 'SMTP USER'):
            self.assertNotIn(secret, message.get_content())
            self.assertNotIn(secret, (self.state / 'state.json').read_text())
        self.assertLess(len(encoded), monitor.MAX_MESSAGE_BYTES)
        self.assertNotIn('\nInjected', message.get_content())

    def test_header_injection_multiple_addresses_and_plain_smtp_are_rejected(self):
        for key, bad in (('recipient', 'one@example.com,two@example.com'),
                         ('recipient', 'Name <one@example.com>'),
                         ('from_address', 'one@example.com\r\nBcc: two@example.com'),
                         ('subject_prefix', 'Chess\nBcc: bad')):
            with self.subTest(key=key, bad=bad):
                saved = self.config.get(key)
                self.config[key] = bad
                self.write_config()
                with self.assertRaises(monitor.MonitorError):
                    monitor.load_config(self.config_path)
                if saved is None:
                    self.config.pop(key)
                else:
                    self.config[key] = saved
        self.config['transport']['security'] = 'none'
        self.write_config()
        with self.assertRaisesRegex(monitor.MonitorError, 'plaintext'):
            monitor.load_config(self.config_path)

    def test_large_unicode_backlog_is_split_by_actual_mime_size_without_losing_ids(self):
        self.initialize()
        expected = {self.game(n, name='😀' * 80) for n in range(1, 106)}
        batches = []
        while len(self.saved()['reported_ids']) < len(expected):
            result = self.run_monitor()
            batches.append(result)
            self.assertLessEqual(len(self.sent[-1]), monitor.MAX_MESSAGE_BYTES)
            self.assertLessEqual(result['new_games'], monitor.MAX_BATCH_GAMES)
        self.assertGreater(len(batches), 1)
        self.assertEqual(batches[0]['overflow'], 105 - batches[0]['new_games'])
        self.assertEqual(sum(item['new_games'] for item in batches), 105)
        self.assertEqual(set(self.saved()['reported_ids']), expected)
        self.assertFalse(self.run_monitor()['sent'])

    def test_lock_prevents_overlapping_sends_and_state_must_be_outside_service_data(self):
        self.initialize()
        self.game(1)
        with monitor.execution_lock(self.state):
            with self.assertRaisesRegex(monitor.MonitorError, 'already active'):
                self.run_monitor()
        self.assertEqual(self.sent, [])
        self.assertEqual(self.saved()['reported_ids'], [])
        with self.assertRaisesRegex(monitor.MonitorError, 'separate monitor'):
            monitor.run(self.source, self.source / 'monitor', initialize=True)

    def test_success_followed_by_checkpoint_failure_can_duplicate_same_pending_message(self):
        self.initialize()
        self.game(1)
        actual = monitor._write_state
        def fail_after_handoff(directory, state):
            if state.get('last_success_at'):
                raise OSError('simulated checkpoint failure')
            return actual(directory, state)
        with patch.object(monitor, '_write_state', side_effect=fail_after_handoff):
            with self.assertRaisesRegex(monitor.MonitorError, 'same Message-ID'):
                self.run_monitor()
        self.assertEqual(self.saved()['reported_ids'], [])
        self.assertEqual(self.run_monitor()['new_games'], 1)
        self.assertEqual(self.sent[0], self.sent[1])

    def test_recipient_change_does_not_silently_reroute_an_existing_queue(self):
        self.initialize()
        self.game(1)
        with self.assertRaises(monitor.MonitorError):
            self.run_monitor(sender=lambda *_: (_ for _ in ()).throw(RuntimeError('retry')))
        self.config['recipient'] = 'different@example.com'
        self.write_config()
        with self.assertRaisesRegex(monitor.MonitorError, 'differs from current'):
            self.run_monitor()
        self.assertEqual(self.sent, [])


class MonitorTransportTests(unittest.TestCase):
    def test_starttls_precedes_auth_and_mail_handoff_uses_only_configured_recipient(self):
        smtp = MagicMock()
        smtp.__enter__.return_value = smtp
        smtp.sendmail.return_value = {}
        config = dict(from_address='from@example.com', recipient='to@example.com',
                      transport=dict(type='smtp', host='smtp.example.com', port=587, security='starttls',
                                     username='user', password='secret'))
        with patch.object(monitor.smtplib, 'SMTP', return_value=smtp):
            monitor.handoff(b'test message', config)
        names = [call[0] for call in smtp.mock_calls]
        self.assertLess(names.index('starttls'), names.index('login'))
        smtp.sendmail.assert_called_once_with('from@example.com', ['to@example.com'], b'test message')

    def test_sendmail_uses_fixed_argv_without_shell(self):
        config = dict(from_address='from@example.com', recipient='to@example.com',
                      transport=dict(type='sendmail', path='/usr/sbin/sendmail'))
        with patch.object(monitor.subprocess, 'run') as command:
            monitor.handoff(b'test message', config)
        self.assertEqual(command.call_args.args[0], ['/usr/sbin/sendmail', '-i', '--', 'to@example.com'])
        self.assertNotIn('shell', command.call_args.kwargs)
        self.assertEqual(command.call_args.kwargs['input'], b'test message')

    def test_linux_dump_protection_fails_closed(self):
        import ctypes
        libc = MagicMock()
        libc.prctl.return_value = -1
        with patch.object(monitor.sys, 'platform', 'linux'), patch.object(ctypes, 'CDLL', return_value=libc):
            with self.assertRaisesRegex(monitor.MonitorError, 'disable process dumps'):
                monitor.protect_credentials()
        libc.prctl.assert_called_once_with(4, 0, 0, 0, 0)


if __name__ == '__main__':
    unittest.main()
