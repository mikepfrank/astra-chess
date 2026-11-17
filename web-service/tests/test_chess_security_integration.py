import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

SPEC = importlib.util.spec_from_file_location('integration', Path(__file__).parents[1] / 'tools/ops/run_chess_security_integration.py')
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


class IntegrationGuardTests(unittest.TestCase):
    def test_live_requires_two_completed_turns_and_saved_thread(self):
        records = [dict(ply=p, thread_saved=True) for p in (1, 3)]
        text = '\n'.join(map(json.dumps, records)) + '\nLive move and conversation checks passed.'
        self.assertEqual(m.parse(text, 'astra-live')['paid_provider_actions'], 2)
        for wrong in (text.replace('3', '2'), text.replace('true', 'false'), text.splitlines()[0]):
            with self.assertRaises(RuntimeError):
                m.parse(wrong, 'astra-live')

    def test_notifier_must_preserve_state_and_send_nothing(self):
        record = dict(state_unchanged=True, email_sent=False)
        self.assertEqual(m.parse('CHECK_JSON ' + json.dumps(record), 'astra-notifier'), record)
        for wrong in (dict(state_unchanged=False, email_sent=False), dict(state_unchanged=True, email_sent=True)):
            with self.assertRaises(RuntimeError):
                m.parse('CHECK_JSON ' + json.dumps(wrong), 'astra-notifier')

    def test_protocol_requires_verified_config_and_thread(self):
        good = dict(strict_config_verified=True, thread_start_verified=True)
        self.assertEqual(m.parse(json.dumps(good), 'astra-protocol'), good)
        with self.assertRaises(RuntimeError):
            m.parse(json.dumps(dict(strict_config_verified=True)), 'astra-protocol')

    def test_clone_preserves_separate_environment_files_and_omits_hooks(self):
        lines = ['User=astra', 'EnvironmentFile=/one', 'EnvironmentFile=/two',
                 'ExecStart=/production', 'ExecStopPost=/cleanup', 'Restart=always', 'ProtectHome=tmpfs']
        helper = SimpleNamespace(read_unit=lambda _: lines, LIFECYCLE={'Restart'})
        text, timeout = m.build(helper, 'astra-live', 'fixture')
        self.assertIn('EnvironmentFile=/one\nEnvironmentFile=/two', text)
        self.assertNotIn('/production', text)
        self.assertNotIn('/cleanup', text)
        self.assertIn('ProtectHome=tmpfs', text)
        self.assertIn('--turns 2', text)
        self.assertIn('operator-checks/security-20261117-fixture', text)
        self.assertEqual(timeout, 900)


if __name__ == '__main__':
    unittest.main()
