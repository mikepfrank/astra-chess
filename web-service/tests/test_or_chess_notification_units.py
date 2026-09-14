"""Notification deployment boundaries; no systemd, SMTP, or model calls."""
from collections import defaultdict
from pathlib import Path, PurePosixPath
import shlex
import tempfile
import unittest
from unittest.mock import patch

from tools.ops import notify_new_games as monitor


DEPLOY = Path(__file__).resolve().parents[1] / 'deploy'
HOME = PurePosixPath('/home/or-chess')
DATA = HOME / '.local/share/or-chess'
STATE = HOME / '.local/state/or-chess-monitor'
CONFIG = HOME / '.config/or-chess-monitor/config.json'


def read_unit(name):
    sections = defaultdict(lambda: defaultdict(list))
    section = None
    for raw in (DEPLOY / name).read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith(('#', ';')):
            continue
        if line.startswith('[') and line.endswith(']'):
            section = line[1:-1]
        else:
            key, value = line.split('=', 1)
            sections[section][key].append(value)
    return sections


class NotificationUnitTests(unittest.TestCase):
    def setUp(self):
        self.unit = read_unit('or-chess-game-notify.service')
        self.service = self.unit['Service']

    def test_separate_operator_identity_paths_and_no_model_credentials(self):
        self.assertEqual(self.service['User'], ['or-chess'])
        self.assertEqual(self.service['Group'], ['or-chess'])
        self.assertEqual(self.service['Type'], ['oneshot'])
        self.assertNotIn('EnvironmentFile', self.service)
        denied = set(' '.join(self.service['UnsetEnvironment']).split())
        self.assertTrue({'OPENAI_API_KEY', 'CODEX_API_KEY', 'OPENROUTER_API_KEY',
                         'CHESS_GATEWAY_TOKEN'} <= denied)
        environment = dict(value.split('=', 1) for value in self.service['Environment'])
        self.assertFalse(set(environment) & denied)
        self.assertEqual(environment['HOME'], str(STATE))
        command = shlex.split(self.service['ExecStart'][0])
        self.assertEqual(command[:2], [str(HOME / 'astra-chess/web-service/.venv/bin/python'),
                                      'tools/ops/notify_new_games.py'])
        options = dict(zip(command[2::2], command[3::2]))
        self.assertEqual(options, {'--data-dir': str(DATA), '--state-dir': str(STATE),
                                   '--config': str(CONFIG)})
        self.assertNotIn('--initialize', command, 'Scheduled sends must never reset the baseline')
        self.assertFalse(STATE.is_relative_to(DATA))
        self.assertFalse(CONFIG.is_relative_to(DATA))

    def test_namespace_exposes_mail_config_and_read_only_database_without_player_secrets(self):
        self.assertEqual(self.service['ProtectHome'], ['tmpfs'])
        self.assertEqual(self.service['ProtectSystem'], ['strict'])
        self.assertEqual(self.service['ReadOnlyPaths'], [str(DATA / 'astra.sqlite3')])
        self.assertEqual(set(self.service['ReadWritePaths']), {str(DATA), str(STATE)})
        self.assertEqual(set(self.service['BindPaths']), {str(DATA), str(STATE)})
        self.assertIn(str(CONFIG), self.service['BindReadOnlyPaths'])
        hidden = {value.removeprefix('-') for value in self.service['InaccessiblePaths']}
        for child in ('players', 'games', 'operator-checks', 'replay-archives', 'public-replays',
                      'openrouter-budget.json', 'openrouter-budget.json.lock'):
            self.assertIn(str(DATA / child), hidden)
        self.assertIn(str(HOME / '.config/or-chess/service.env'), hidden)
        for key in ('BindPaths', 'BindReadOnlyPaths', 'ReadOnlyPaths', 'ReadWritePaths'):
            self.assertTrue(all(PurePosixPath(path).is_relative_to(HOME)
                                for path in self.service[key]), 'No other account may be mounted')
        self.assertEqual(self.service['LimitCORE'], ['0'])
        self.assertEqual(self.service['UMask'], ['0077'])
        self.assertEqual(self.service['NoNewPrivileges'], ['true'])
        self.assertEqual(self.service['ProtectProc'], ['invisible'])
        self.assertEqual(self.service['TimeoutStartSec'], ['120'])

    def test_hourly_timer_is_independent_and_offset_from_original_astra(self):
        timer = read_unit('or-chess-game-notify.timer')
        self.assertEqual(timer['Timer']['Unit'], ['or-chess-game-notify.service'])
        self.assertEqual(timer['Timer']['OnCalendar'], ['*-*-* *:05:00'])
        self.assertEqual(timer['Timer']['RandomizedDelaySec'], ['60'])
        self.assertEqual(timer['Timer']['Persistent'], ['true'])
        self.assertEqual(timer['Install']['WantedBy'], ['timers.target'])
        for unit in (timer, self.unit):
            self.assertFalse({'Requires', 'PartOf', 'BindsTo'} & unit['Unit'].keys())
        original = read_unit('astra-game-notify.timer')
        self.assertEqual(original['Timer']['OnCalendar'], ['hourly'])
        self.assertEqual(original['Timer']['Unit'], ['astra-game-notify.service'])

    def test_example_configuration_loads_with_arcturus_sender_and_placeholder_transport(self):
        example = DEPLOY / 'or-chess-notification-config.example.json'
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory) / 'config.json'
            private.write_bytes(example.read_bytes())
            private.chmod(0o600)
            # IANA timezone availability is checked in the Linux namespace;
            # the Windows test runtime need not carry its optional tzdata.
            with patch.object(monitor, 'protect_credentials'), \
                    patch.object(monitor, '_zone') as zone_check:
                config = monitor.load_config(private)
            zone_check.assert_called_once_with('America/Chicago')
        self.assertEqual(config['site_name'], 'Arcturus chess')
        self.assertEqual(config['subject_prefix'], 'Arcturus chess')
        self.assertEqual(config['from_address'], 'notifications@arcturuschess.com')
        self.assertEqual(config['recipient'], config['feedback_address'])
        self.assertEqual(config['recipient'], 'operator@example.net')
        self.assertEqual(config['transport']['security'], 'starttls')
        self.assertEqual(config['transport']['host'], 'email-smtp.us-west-2.amazonaws.com')
        self.assertTrue(config['transport']['password'].startswith('REPLACE_'))


if __name__ == '__main__':
    unittest.main()
