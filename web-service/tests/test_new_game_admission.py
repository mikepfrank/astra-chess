"""Check the narrow cost gate using fake host boundaries; never contact production."""
from contextlib import nullcontext
import json
from pathlib import Path
import re
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call, patch

from tools.ops import astra_service as lifecycle
from tools.ops import new_game_admission as admission


NORMAL = 'astraplayschess.com {\n    encode gzip\n    reverse_proxy 127.0.0.1:8788\n}\n'
OTHER = ('arcturuschess.com {\n    reverse_proxy 127.0.0.1:8792\n}\n'
         'gpt2-chat.com {\n    reverse_proxy 127.0.0.1:8795\n}\n')


class AdmissionFragmentTests(unittest.TestCase):
    def test_matchers_only_block_new_game_posts_and_publish_get_policy(self):
        text = admission.fragment().decode()
        matchers = dict(re.findall(r'@(\w+) \{\n(.*?)\n\}', text, re.DOTALL))
        self.assertEqual(matchers, {
            'astra_new_games_paused': '    method POST\n    path /api/games /api/games/',
            'astra_new_game_policy': '    method GET\n    path /api/new-game-policy',
        })
        # List/read/resume/action routes do not match these exact paths/methods.
        self.assertNotIn('/api/games/*', text)
        self.assertNotIn('reverse_proxy', text)

    def test_responses_preserve_json_cost_message_and_self_hosting_url(self):
        responses = {}
        for line in admission.fragment().decode().splitlines():
            if line.startswith('respond '):
                _, matcher, remainder = line.split(' ', 2)
                quoted_json, status = remainder.rsplit(' ', 1)
                responses[matcher] = (int(status), json.loads(json.loads(quoted_json)))
        self.assertEqual(responses['@astra_new_games_paused'], (503, {
            'detail': admission.MESSAGE, 'code': 'new_games_paused',
            'deployment_url': admission.URL,
        }))
        self.assertEqual(responses['@astra_new_game_policy'], (200, admission.policy()))
        for matcher in responses:
            self.assertIn('header ' + matcher + ' Cache-Control no-store\n', admission.fragment().decode())
            self.assertIn('header ' + matcher + ' Content-Type application/json\n', admission.fragment().decode())

    def test_pause_open_roundtrip_is_idempotent_and_rejects_duplicate_import(self):
        paused = admission.desired_block(NORMAL, True)
        lifecycle.normal_block(paused)
        self.assertEqual(admission.desired_block(paused, True), paused)
        self.assertEqual(admission.desired_block(paused, False), NORMAL)
        self.assertEqual(admission.desired_block(NORMAL, False), NORMAL)
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            admission.desired_block(paused.replace(admission.IMPORT, admission.IMPORT * 2), True)

    def test_sandbox_dropin_exposes_only_the_optional_read_only_fragment(self):
        self.assertEqual(admission.DROPIN_CONTENT,
                         b'[Service]\nBindReadOnlyPaths=-/home/astra/.config/astra-chess/new-games.caddy\n')
        self.assertEqual(admission.IMPORT,
                         '    import /home/astra/.config/astra-chess/new-games.caddy\n')


class AdmissionHostTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.config = self.root / 'Caddyfile'
        self.config.write_bytes((NORMAL + OTHER).encode())
        self.fragment = self.root / 'new-games.caddy'
        self.dropin = self.root / 'systemd' / '30-new-game-admission.conf'
        self.data = self.root / 'data'
        self.data.mkdir()
        self.flag = self.data / 'new-games-paused'
        self.ops = SimpleNamespace(
            DATA=self.data, CONFIG_LOCK=self.root / 'config.lock',
            STATE_FILE=self.root / 'maintenance.json', STATE_DIR=self.root / 'ops',
            CADDYFILE=self.config, PROXY=lifecycle.PROXY, SYSTEMCTL=lifecycle.SYSTEMCTL,
            lock=Mock(side_effect=lambda path: nullcontext()),
            site_block=lifecycle.site_block, normal_block=lifecycle.normal_block,
            replace_site=lifecycle.replace_site,
            atomic_write=Mock(side_effect=lambda path, data, **kwargs: Path(path).write_bytes(data)),
            validate_config=Mock(), control=Mock(), command=Mock(),
        )
        self.verify = Mock()
        for target, name, value in (
            (admission, 'load_ops', Mock(return_value=self.ops)),
            (admission, 'FRAGMENT', self.fragment),
            (admission, 'DROPIN', self.dropin),
            (admission, 'verify', self.verify),
        ):
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch('builtins.print')
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_action(self, action):
        with patch('sys.argv', ['new_game_admission.py', action]):
            admission.main()

    def prepare_paused(self):
        self.config.write_bytes((admission.desired_block(NORMAL, True) + OTHER).encode())
        self.fragment.write_bytes(admission.fragment())
        self.flag.touch()

    def test_pause_preserves_other_sites_and_only_restarts_the_proxy(self):
        self.run_action('pause')
        self.assertEqual(self.config.read_text(), admission.desired_block(NORMAL, True) + OTHER)
        self.assertTrue(self.flag.exists())
        self.assertEqual(self.fragment.read_bytes(), admission.fragment())
        self.assertEqual(self.dropin.read_bytes(), admission.DROPIN_CONTENT)
        self.ops.command.assert_called_once_with([lifecycle.SYSTEMCTL, 'daemon-reload'])
        self.ops.control.assert_called_once_with('restart', lifecycle.PROXY)
        self.verify.assert_called_once_with(self.ops, True)
        self.assertEqual(len(list(self.ops.STATE_DIR.glob('admission-*.backup'))), 1)

    def test_open_removes_only_admission_gate_and_keeps_optional_mount(self):
        self.prepare_paused()
        self.run_action('open')
        self.assertEqual(self.config.read_text(), NORMAL + OTHER)
        self.assertFalse(self.flag.exists())
        self.assertEqual(self.dropin.read_bytes(), admission.DROPIN_CONTENT)
        self.ops.control.assert_called_once_with('restart', lifecycle.PROXY)
        self.verify.assert_called_once_with(self.ops, False)

    def test_failed_pause_restores_original_admission_and_preserves_later_other_site_edit(self):
        def fail_first_verify(ops, paused):
            if self.verify.call_count == 1:
                self.config.write_bytes(self.config.read_bytes().replace(b'8792', b'8793'))
                raise RuntimeError('Public gate did not become ready')
        self.verify.side_effect = fail_first_verify
        with self.assertRaisesRegex(RuntimeError, 'did not become ready'):
            self.run_action('pause')
        self.assertEqual(self.config.read_text(), NORMAL + OTHER.replace('8792', '8793'))
        self.assertFalse(self.flag.exists())
        self.assertFalse(self.fragment.exists())
        self.assertEqual(self.ops.control.call_args_list, [call('restart', lifecycle.PROXY)] * 2)
        self.assertEqual(self.verify.call_args_list, [call(self.ops, True), call(self.ops, False)])

    def test_failed_open_restores_pause_marker_and_import(self):
        self.prepare_paused()
        before = self.config.read_bytes()
        self.verify.side_effect = [RuntimeError('Reopen probe failed'), None]
        with self.assertRaisesRegex(RuntimeError, 'Reopen probe failed'):
            self.run_action('open')
        self.assertEqual(self.config.read_bytes(), before)
        self.assertTrue(self.flag.exists())
        self.assertEqual(self.fragment.read_bytes(), admission.fragment())
        self.assertEqual(self.ops.control.call_args_list, [call('restart', lifecycle.PROXY)] * 2)
        self.assertEqual(self.verify.call_args_list, [call(self.ops, False), call(self.ops, True)])

    def test_invalid_candidate_does_not_restart_or_change_admission(self):
        self.ops.validate_config.side_effect = lifecycle.SafetyError('Invalid candidate')
        with self.assertRaisesRegex(lifecycle.SafetyError, 'Invalid candidate'):
            self.run_action('pause')
        self.assertEqual(self.config.read_text(), NORMAL + OTHER)
        self.assertFalse(self.flag.exists())
        self.assertFalse(self.fragment.exists())
        self.ops.control.assert_not_called()
        self.ops.command.assert_not_called()

    def test_independent_dropin_is_not_overwritten(self):
        self.dropin.parent.mkdir()
        self.dropin.write_bytes(b'[Service]\nEnvironment=OPERATOR_SETTING=1\n')
        before = self.dropin.read_bytes()
        with self.assertRaisesRegex(RuntimeError, 'sandbox drop-in differs'):
            self.run_action('pause')
        self.assertEqual(self.dropin.read_bytes(), before)
        self.ops.atomic_write.assert_not_called()
        self.ops.control.assert_not_called()

    def test_maintenance_checkpoint_prevents_conflicting_operation(self):
        self.ops.STATE_FILE.touch()
        with self.assertRaisesRegex(RuntimeError, 'maintenance checkpoint exists'):
            self.run_action('pause')
        self.ops.atomic_write.assert_not_called()
        self.ops.control.assert_not_called()


if __name__ == '__main__':
    unittest.main()
