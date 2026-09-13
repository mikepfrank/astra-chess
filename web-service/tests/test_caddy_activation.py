"""Bounded local transaction checks: no network, processes or service signals."""

import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / 'tools' / 'ops' / 'activate_arcturus_caddy.py'
SPEC = importlib.util.spec_from_file_location('caddy_activation', SOURCE)
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)
ORIGINAL = (b'{\r\n    admin off\r\n}\r\nastraplayschess.com {\r\n'
            b'    reverse_proxy 127.0.0.1:8788\r\n}\r\n'
            b'www.astraplayschess.com {\r\n'
            b'    redir https://astraplayschess.com{uri} permanent\r\n}')


class CandidateTests(unittest.TestCase):
    def test_preserves_every_original_byte_and_separates_unterminated_line(self):
        candidate = helper.candidate_bytes(ORIGINAL)
        self.assertEqual(candidate[:len(ORIGINAL)], ORIGINAL)
        self.assertEqual(candidate[len(ORIGINAL):], helper.BLOCK)
        self.assertIn(b'}\narcturus.', candidate)

    def test_refuses_duplicate_import_and_unexpected_site_configurations(self):
        for data in (ORIGINAL + helper.BLOCK, b'import other.conf\n' + ORIGINAL,
                     ORIGINAL.replace(b'www.astraplayschess.com', b'other.example'), b''):
            with self.subTest(data=data), self.assertRaises(helper.ActivationError):
                helper.candidate_bytes(data)


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.config = Path(self.temporary.name) / 'Caddyfile'
        self.config.write_bytes(ORIGINAL)
        self.descriptor = os.open(self.config, os.O_RDWR | getattr(os, 'O_BINARY', 0))
        self.addCleanup(os.close, self.descriptor)
        self.original_stat = os.fstat(self.descriptor)
        self.candidate = helper.candidate_bytes(ORIGINAL)
        self.report = {}
        self.baseline = {'config': {'model': 'astra'}, 'index_sha256': 'original'}
        self.experimental = {'config': {'model': 'glm'}, 'index_sha256': 'experimental'}
        self.start_patch('CONFIG', self.config)
        self.start_patch('caddy_identity', return_value=(111, 'caddy-start'))
        self.start_patch('active_pid', return_value=222)
        self.start_patch('process_stamp', return_value=(222, 'astra-start'))
        self.signal = self.start_patch('signal_caddy')
        self.original_sites = self.start_patch('original_sites', return_value=self.baseline)
        self.site_snapshot = self.start_patch('site_snapshot', return_value=self.experimental)
        self.start_patch('await_routes', side_effect=lambda check, **kwargs: check())

    def start_patch(self, name, *args, **kwargs):
        patcher = patch.object(helper, name, *args, **kwargs)
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def activate(self):
        helper.activate(self.descriptor, self.original_stat, ORIGINAL, self.candidate,
                        (111, 'caddy-start'), (222, 'astra-start'), self.baseline,
                        self.experimental, self.report)

    def test_success_preserves_inode_and_only_signals_expected_caddy(self):
        self.activate()
        self.assertEqual(self.config.read_bytes(), self.candidate)
        self.assertEqual(self.config.stat().st_ino, self.original_stat.st_ino)
        self.signal.assert_called_once_with(self.original_stat, expected=(111, 'caddy-start'))
        self.assertTrue(self.report['routes_verified'])

    def test_failed_new_route_restores_bytes_and_signals_rollback(self):
        self.site_snapshot.side_effect = helper.ActivationError('Fixture route failed')
        with self.assertRaises(helper.ActivationError):
            self.activate()
        self.assertEqual(self.config.read_bytes(), ORIGINAL)
        self.assertEqual(self.config.stat().st_ino, self.original_stat.st_ino)
        self.assertEqual(self.signal.call_count, 2)
        self.assertIn('original routes verified', self.report['rollback'])

    def test_config_changed_after_preflight_causes_no_write_or_signal(self):
        changed = ORIGINAL + b'\n# operator update\n'
        self.config.write_bytes(changed)
        with self.assertRaises(helper.ActivationError):
            self.activate()
        self.assertEqual(self.config.read_bytes(), changed)
        self.signal.assert_not_called()

    def test_external_edit_after_write_is_not_overwritten_by_rollback(self):
        changed = self.candidate + b'\n# concurrent operator update\n'
        def mutate(*args, **kwargs):
            self.config.write_bytes(changed)
        self.signal.side_effect = mutate
        with self.assertRaises(helper.ActivationError):
            self.activate()
        self.assertEqual(self.config.read_bytes(), changed)
        self.assertEqual(self.signal.call_count, 1)
        self.assertIn('manual recovery required', self.report['rollback'])

    def test_partial_write_is_rolled_back(self):
        real_rewrite = helper.rewrite
        calls = []
        def fail_once(descriptor, data):
            calls.append(data)
            if len(calls) == 1:
                real_rewrite(descriptor, data[:-8])
                raise OSError('fixture write failure')
            real_rewrite(descriptor, data)
        self.start_patch('rewrite', side_effect=fail_once)
        with self.assertRaises(OSError):
            self.activate()
        self.assertEqual(self.config.read_bytes(), ORIGINAL)
        self.assertIn('original routes verified', self.report['rollback'])

    def test_external_truncation_during_failed_write_is_not_overwritten(self):
        changed = ORIGINAL[:-8]
        def truncate(descriptor, data):
            self.config.write_bytes(changed)
            raise OSError('fixture concurrent truncation')
        self.start_patch('rewrite', side_effect=truncate)
        with self.assertRaises(OSError):
            self.activate()
        self.assertEqual(self.config.read_bytes(), changed)
        self.signal.assert_not_called()
        self.assertIn('manual recovery required', self.report['rollback'])

    def test_failed_recovery_is_explicit_and_preserves_backup_source_bytes(self):
        self.site_snapshot.side_effect = helper.ActivationError('Fixture route failed')
        self.original_sites.side_effect = [self.baseline, helper.ActivationError('Still unhealthy')]
        with self.assertRaises(helper.ActivationError):
            self.activate()
        self.assertEqual(self.config.read_bytes(), ORIGINAL)
        self.assertIn('manual recovery required', self.report['rollback'])


if __name__ == '__main__':
    unittest.main()
