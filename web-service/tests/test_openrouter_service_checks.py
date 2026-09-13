"""Deployment checks retain isolation, spending continuity and paid opt-in."""
from pathlib import Path
import unittest
from unittest.mock import patch

from tools import check_openrouter_service as check
from tools import run_openrouter_service_check as runner


class OpenRouterServiceCheckTests(unittest.TestCase):
    def setUp(self):
        self.unit = (Path(__file__).resolve().parents[1] / 'deploy/or-chess.service').read_text()

    def test_transient_unit_preserves_security_environment_and_limits(self):
        props = runner.service_properties(self.unit)
        command = runner.check_command(props, 'wire', 'probe')
        for value in (
            '--property=User=or-chess', '--property=Group=or-chess',
            '--property=ProtectHome=tmpfs', '--property=ProtectSystem=strict',
            '--property=NoNewPrivileges=true', '--property=CPUQuota=50%',
            '--property=Nice=10', '--property=MemoryMax=2G', '--property=TasksMax=64',
            '--property=UnsetEnvironment=OPENAI_API_KEY CODEX_API_KEY',
            '--property=EnvironmentFile=/home/or-chess/.config/or-chess/service.env',
        ):
            self.assertIn(value, command)
        environment = next(arg for arg in command if arg.startswith('--property=Environment='))
        self.assertIn('ASTRA_OPENROUTER_BUDGET_PATH=/home/or-chess/.local/share/or-chess/openrouter-budget.json', environment)
        self.assertIn('ASTRA_MODEL_PROFILE=openrouter-glm', environment)
        self.assertIn('ASTRA_PERSONA=arcturus', environment)
        self.assertFalse(any('ExecStart=' in arg for arg in command))
        self.assertNotIn('--live', command)

    def test_other_account_or_environment_file_is_rejected(self):
        for old, new in (('User=or-chess', 'User=astra'),
                         ('Group=or-chess', 'Group=astra'),
                         ('/home/or-chess/.config/or-chess/service.env', '/home/astra/private.env')):
            with self.subTest(new=new), self.assertRaises(ValueError):
                runner.service_properties(self.unit.replace(old, new))

    def test_paid_mode_requires_explicit_authorization(self):
        props = runner.service_properties(self.unit)
        with self.assertRaises(ValueError):
            runner.check_command(props, 'live', 'probe')
        command = runner.check_command(props, 'live', 'probe', live=True)
        self.assertEqual(command[-2:], ['live', '--live'])

    def test_wire_uses_mock_gateway_and_reviewed_linux_version(self):
        command = check.followup_command('wire', 'probe')
        self.assertIn('--through-gateway', command)
        self.assertEqual(command[command.index('--candidate-version') + 1], '0.154.0')
        self.assertNotIn('--live', command)

    def test_live_uses_profile_and_disposable_data_without_new_budget(self):
        command = check.followup_command('live', 'probe')
        self.assertEqual(command[command.index('--profile') + 1], 'openrouter-glm')
        self.assertEqual(command[command.index('--turns') + 1], '2')
        self.assertEqual(Path(command[command.index('--data-dir') + 1]), check.DATA / 'operator-checks/live-probe')
        self.assertFalse(any('budget' in part for part in command))

    def test_failed_preflight_never_launches_followup(self):
        with patch.object(check.sys, 'argv', ['check', 'live', '--live']), \
             patch.object(check.sys, 'platform', 'linux'), \
             patch.object(check, 'preflight', return_value={'checks': {'existing_private_budget': False}}), \
             patch.object(check.subprocess, 'run') as run:
            self.assertEqual(check.main(), 1)
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
