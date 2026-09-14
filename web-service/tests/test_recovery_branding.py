"""Recovery mail uses the deployment persona and canonical origin; no sends."""
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import urlsplit

from astra_web.config import Config
from astra_web.identity import Identity


class RecoveryBrandingTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)

    def test_smtp_messages_use_persona_branding_with_sender_feedback_and_canonical_message_id(self):
        for model, persona, display, origin in (
                ('astra', None, 'Astra', 'https://astraplayschess.com'),
                ('openrouter-glm', None, 'Arcturus', 'https://arcturuschess.com'),
                ('openrouter-glm', 'astra', 'Astra', 'https://arcturuschess.com')):
            for verification in (False, True):
                with self.subTest(model=model, persona=persona, verification=verification):
                    config = Config(data_dir=self.folder, model_profile=model, persona=persona,
                        origin=origin, smtp_host='smtp.example.org', smtp_from='accounts@example.org',
                        smtp_user='fixture-smtp-user', smtp_password='fixture-smtp-password',
                        smtp_feedback_address='feedback@example.org')
                    # Sending itself does not need a database or account mutation.
                    identity = object.__new__(Identity)
                    identity.config = config
                    transport = MagicMock()
                    smtp = transport.__enter__.return_value
                    tls_context = object()
                    fragment = '#verify-email=' if verification else '#reset='
                    url = origin + '/' + fragment + 'fixture-token'
                    with patch('astra_web.identity.smtplib.SMTP', return_value=transport), \
                            patch('astra_web.identity.ssl.create_default_context', return_value=tls_context):
                        identity._send_email('recipient@example.org', url,
                                             verification=verification, name='Fixture account')
                    message = smtp.send_message.call_args.args[0]
                    self.assertEqual(message['Subject'],
                        f'Verify your {display} chess recovery email' if verification else
                        f'Reset your {display} chess password')
                    self.assertIn(f'your {display} chess account', message.get_content())
                    self.assertIn(url, message.get_content())
                    self.assertEqual(message['From'], 'accounts@example.org')
                    self.assertEqual(message['To'], 'recipient@example.org')
                    self.assertEqual(message['Return-Path'], 'feedback@example.org')
                    self.assertTrue(str(message['Message-ID']).endswith('@' + urlsplit(origin).hostname + '>'))
                    self.assertNotIn('Fixture account', str(message['Subject']))
                    self.assertNotIn('fixture-token', str(message['Subject']))
                    methods = [call[0] for call in smtp.method_calls]
                    smtp.starttls.assert_called_once_with(context=tls_context)
                    self.assertLess(methods.index('starttls'), methods.index('login'))
                    self.assertLess(methods.index('login'), methods.index('send_message'))

    def test_confirmation_and_reset_links_use_canonical_domain_with_alias_configured(self):
        origin = 'https://arcturuschess.com'
        config = Config(data_dir=self.folder, model_profile='openrouter-glm', origin=origin,
            additional_origins=('https://arcturus.astraplayschess.com',), smtp_host='', smtp_from='')
        sent = []
        identity = Identity(config, verification_sender=lambda address, url: sent.append(('verify', url)),
                            email_sender=lambda address, url: sent.append(('reset', url)))
        now = time.time()
        with patch('astra_web.identity.time.time', return_value=now):
            identity.register('Canonical fixture', 'fixture password long enough', 'recipient@example.org')
        self.assertEqual(sent[0][0], 'verify')
        self.assertTrue(sent[0][1].startswith(origin + '/#verify-email='))
        token = sent[0][1].partition('#verify-email=')[2]
        identity.verify_email(token)
        with patch('astra_web.identity.time.time', return_value=now + 61):
            identity.forgot('Canonical fixture')
        self.assertEqual(sent[1][0], 'reset')
        self.assertTrue(sent[1][1].startswith(origin + '/#reset='))
        self.assertFalse(any('astraplayschess.com' in url for _, url in sent))


if __name__ == '__main__':
    unittest.main()
