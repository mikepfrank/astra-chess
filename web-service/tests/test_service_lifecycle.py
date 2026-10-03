"""Exercise maintenance safety using a fake host; never invoke systemctl or SSH."""
from contextlib import ExitStack, nullcontext
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.ops import astra_service as lifecycle


NORMAL = 'astraplayschess.com {\n    encode gzip\n    reverse_proxy 127.0.0.1:8788\n}\n'
OTHER = ('www.astraplayschess.com {\n    redir https://astraplayschess.com{uri} permanent\n}\n'
         'arcturuschess.com {\n    reverse_proxy 127.0.0.1:8792\n}\n')
IDLE = dict(active_responses=0, building_replays=0, reserved_tokens=0, idle_snapshot=True)


class ProxySafetyTests(unittest.TestCase):
    def test_astra_replacement_preserves_other_sites_and_later_edits(self):
        original = '{\n    admin off\n}\n' + NORMAL + OTHER
        gated = lifecycle.maintenance_block('a' * 32)
        closed = lifecycle.replace_site(original, NORMAL, gated)
        concurrent = closed.replace('127.0.0.1:8792', '127.0.0.1:8793')
        reopened = lifecycle.replace_site(concurrent, gated, NORMAL)
        self.assertEqual(reopened, original.replace('127.0.0.1:8792', '127.0.0.1:8793'))

    def test_complex_duplicate_missing_or_independently_changed_astra_is_rejected(self):
        for text in (OTHER, NORMAL + NORMAL + OTHER,
                     NORMAL.replace('    encode gzip\n', '    handle {\n        respond ok\n    }\n'),
                     NORMAL.replace('astraplayschess.com {', 'astraplayschess.com, elsewhere.example {')):
            with self.subTest(text=text), self.assertRaises(lifecycle.SafetyError):
                lifecycle.site_block(text)
        with self.assertRaises(lifecycle.SafetyError):
            lifecycle.replace_site(NORMAL, NORMAL.replace('gzip', 'zstd'), 'replacement')
        with self.assertRaises(lifecycle.SafetyError):
            lifecycle.normal_block(NORMAL.replace('8788', '8792'))

    def test_adapted_alternate_astra_routes_prevent_gate(self):
        def adapt(*args, **kwargs):
            return json.dumps({'apps': {'http': {'routes': [
                {'upstreams': [{'dial': '127.0.0.1:8792'}]},
                {'upstreams': [{'dial': 'localhost:8788'}]},
            ]}}})
        with patch.object(lifecycle, 'command', side_effect=adapt) as command:
            with self.assertRaisesRegex(lifecycle.SafetyError, 'alternate Astra upstream'):
                lifecycle.validate_config(Path('candidate'), gated=True)
            self.assertEqual(command.call_count, 1)

    def test_bad_activity_schema_cannot_be_mistaken_for_idle(self):
        for bad in ({}, dict(IDLE, active_responses=False), dict(IDLE, reserved_tokens=-1),
                    dict(IDLE, building_replays='0'), dict(IDLE, idle_snapshot=False)):
            with self.subTest(activity=bad), patch.object(lifecycle, 'command', return_value=json.dumps({'activity': bad})):
                with self.assertRaises(lifecycle.SafetyError):
                    lifecycle.activity()

    def test_cgroup_descendants_are_included_and_outside_paths_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = root / 'system.slice' / lifecycle.APP
            child = service / 'worker'
            child.mkdir(parents=True)
            (service / 'cgroup.procs').write_text('100\n')
            (child / 'cgroup.procs').write_text('101\n102\n')
            info = dict(ActiveState='active', MainPID='100', ControlGroup='/system.slice/' + lifecycle.APP)
            with patch.object(lifecycle, 'CGROUP', root):
                self.assertEqual(lifecycle.cgroup_pids(info), {100, 101, 102})
                with self.assertRaises(lifecycle.SafetyError):
                    lifecycle.cgroup_pids(dict(info, ControlGroup='/../../elsewhere'))

    def test_failed_open_restores_gate_but_keeps_concurrent_arcturus_change(self):
        state = dict(marker='b' * 32, original_block=NORMAL)
        maintenance = lifecycle.maintenance_block(state['marker'])
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            config = Path(folder) / 'Caddyfile'
            config.write_bytes((maintenance + OTHER).encode())
            stack.enter_context(patch.object(lifecycle, 'CADDYFILE', config))
            stack.enter_context(patch.object(lifecycle, 'atomic_write', side_effect=lambda path, value, **kw: Path(path).write_bytes(value)))
            stack.enter_context(patch.object(lifecycle, 'validate_config'))
            stack.enter_context(patch.object(lifecycle, 'unit', return_value={'ActiveState': 'active'}))
            restart = stack.enter_context(patch.object(lifecycle, 'control'))
            def failed_health(**kwargs):
                config.write_bytes(config.read_bytes().replace(b'8792', b'8793'))
                raise lifecycle.SafetyError('Public health failed')
            stack.enter_context(patch.object(lifecycle, 'health', side_effect=failed_health))
            with self.assertRaisesRegex(lifecycle.SafetyError, 'Public health failed'):
                lifecycle.change_proxy(state, gated=False)
            self.assertEqual(config.read_text(), maintenance + OTHER.replace('8792', '8793'))
            self.assertEqual(restart.call_count, 2)

    def test_config_changed_during_validation_is_not_overwritten_or_restarted(self):
        state = dict(marker='c' * 32, original_block=NORMAL)
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            config = Path(folder) / 'Caddyfile'
            config.write_bytes((NORMAL + OTHER).encode())
            stack.enter_context(patch.object(lifecycle, 'CADDYFILE', config))
            stack.enter_context(patch.object(lifecycle, 'atomic_write', side_effect=lambda path, value, **kw: Path(path).write_bytes(value)))
            def concurrent_edit(*args, **kwargs):
                config.write_bytes(config.read_bytes().replace(b'8792', b'8793'))
            stack.enter_context(patch.object(lifecycle, 'validate_config', side_effect=concurrent_edit))
            restart = stack.enter_context(patch.object(lifecycle, 'control'))
            with self.assertRaisesRegex(lifecycle.SafetyError, 'changed during validation'):
                lifecycle.change_proxy(state, gated=True)
            self.assertEqual(config.read_text(), NORMAL + OTHER.replace('8792', '8793'))
            restart.assert_not_called()

    def test_validation_error_does_not_restart_even_if_already_in_desired_state(self):
        state = dict(marker='d' * 32, original_block=NORMAL)
        maintenance = lifecycle.maintenance_block(state['marker'])
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            config = Path(folder) / 'Caddyfile'
            config.write_bytes((maintenance + OTHER).encode())
            stack.enter_context(patch.object(lifecycle, 'CADDYFILE', config))
            stack.enter_context(patch.object(lifecycle, 'atomic_write', side_effect=lambda path, value, **kw: Path(path).write_bytes(value)))
            stack.enter_context(patch.object(lifecycle, 'validate_config', side_effect=lifecycle.SafetyError('Invalid configuration')))
            restart = stack.enter_context(patch.object(lifecycle, 'control'))
            with self.assertRaisesRegex(lifecycle.SafetyError, 'Invalid configuration'):
                lifecycle.change_proxy(state, gated=True)
            self.assertEqual(config.read_text(), maintenance + OTHER)
            restart.assert_not_called()


class FakeHostTests(unittest.TestCase):
    """Run the real down/up orchestration, replacing only host boundary functions."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.config = self.root / 'Caddyfile'
        self.config.write_text(NORMAL + OTHER, encoding='utf-8')
        self.state_file = self.root / 'maintenance.json'
        data = self.root / 'data'
        data.mkdir()
        (data / 'astra.sqlite3').touch()
        self.events = []
        self.now = 0
        self.children = set()
        self.counts = IDLE.copy()
        self.units = {}
        for name in (lifecycle.APP, lifecycle.PROXY, lifecycle.TIMER, lifecycle.NOTIFIER):
            active = name != lifecycle.NOTIFIER
            self.units[name] = dict(LoadState='loaded', ActiveState='active' if active else 'inactive',
                                   SubState='running' if active else 'dead', MainPID='100' if name == lifecycle.APP else '0',
                                   ControlGroup='/system.slice/' + name, ExecMainStartTimestampMonotonic='1000',
                                   UnitFileState='enabled', Result='success')

        def install(name, **kwargs):
            patcher = patch.object(lifecycle, name, **kwargs)
            mock = patcher.start()
            self.addCleanup(patcher.stop)
            return mock

        install('CADDYFILE', new=self.config)
        install('DATA', new=data)
        install('STATE_DIR', new=self.root)
        install('STATE_FILE', new=self.state_file)
        install('STABLE_SECONDS', new=2)
        install('POLL_SECONDS', new=1)
        install('lock', side_effect=lambda *args: nullcontext())
        install('log')
        install('atomic_write', side_effect=lambda path, value, **kwargs: Path(path).write_bytes(value))
        self.unit = install('unit', side_effect=lambda name: self.units[name].copy())
        self.control = install('control', side_effect=self.fake_control)
        self.report = install('activity', side_effect=lambda: self.counts.copy())
        self.pids = install('cgroup_pids', side_effect=lambda info: self.children | ({int(info['MainPID'])} if info['MainPID'] != '0' else set()))
        self.health = install('health', side_effect=self.fake_health)
        self.gate = install('verify_gate', side_effect=self.fake_verify_gate)
        self.change_proxy = install('change_proxy', side_effect=self.fake_change_proxy)
        install('validate_config')
        install('command', side_effect=AssertionError('Unexpected external command in unit test'))
        for name, effect in (('monotonic', lambda: self.now), ('sleep', self.fake_sleep)):
            patcher = patch.object(lifecycle.time, name, side_effect=effect)
            patcher.start()
            self.addCleanup(patcher.stop)

    def fake_sleep(self, seconds):
        self.now += seconds

    def fake_control(self, action, name):
        self.events.append((action, name))
        if action in ('enable', 'disable'):
            self.units[name]['UnitFileState'] = 'enabled' if action == 'enable' else 'disabled'
        elif action == 'stop':
            self.units[name].update(ActiveState='inactive', MainPID='0')
        elif action == 'start':
            self.units[name].update(ActiveState='active')
            if name == lifecycle.APP:
                self.units[name].update(MainPID='200', ExecMainStartTimestampMonotonic='2000')

    def fake_health(self, *, proxy):
        self.events.append(('health', 'proxy' if proxy else 'direct'))
        if self.units[lifecycle.APP]['ActiveState'] != 'active':
            raise lifecycle.SafetyError('Fixture app is not healthy')
        if proxy and lifecycle.site_block(self.config.read_text()) != NORMAL:
            raise lifecycle.SafetyError('Fixture proxy is gated')

    def fake_verify_gate(self, state):
        self.events.append(('verify', 'gate'))
        self.assertEqual(lifecycle.site_block(self.config.read_text()), lifecycle.maintenance_block(state['marker']))

    def fake_change_proxy(self, state, *, gated):
        self.events.append(('proxy', 'closed' if gated else 'open'))
        current = self.config.read_text()
        replacement = lifecycle.maintenance_block(state['marker']) if gated else state['original_block']
        self.config.write_text(lifecycle.replace_site(current, lifecycle.site_block(current), replacement))
        if gated:
            lifecycle.verify_gate(state)
        else:
            lifecycle.health(proxy=True)

    def assert_app_not_stopped(self):
        self.assertNotIn(('stop', lifecycle.APP), self.events)
        self.assertEqual(self.units[lifecycle.APP]['ActiveState'], 'active')

    def test_busy_each_kind_times_out_without_stopping_and_leaves_recoverable_gate(self):
        for key in ('active_responses', 'building_replays', 'reserved_tokens'):
            with self.subTest(key=key):
                self.counts = dict(IDLE, **{key: 1, 'idle_snapshot': False})
                with self.assertRaisesRegex(lifecycle.SafetyError, 'Drain timed out'):
                    lifecycle.down(3)
                self.assert_app_not_stopped()
                state = lifecycle.load()
                self.assertEqual(state['phase'], 'draining')
                self.fake_verify_gate(state)
                self.assertEqual(self.units[lifecycle.APP]['UnitFileState'], 'disabled')

    def test_activity_error_after_gate_never_stops_app(self):
        self.report.side_effect = [IDLE.copy(), lifecycle.SafetyError('Unreadable inventory')]
        with self.assertRaisesRegex(lifecycle.SafetyError, 'Unreadable inventory'):
            lifecycle.down(3)
        self.assert_app_not_stopped()
        self.fake_verify_gate(lifecycle.load())

    def test_worker_children_block_stop_even_if_database_reports_idle(self):
        self.children = {101}
        with self.assertRaisesRegex(lifecycle.SafetyError, 'Drain timed out'):
            lifecycle.down(3)
        self.assert_app_not_stopped()

    def test_missing_main_pid_in_cgroup_cannot_be_mistaken_for_idle(self):
        self.pids.side_effect = lambda info: set()
        with self.assertRaisesRegex(lifecycle.SafetyError, 'PID is absent'):
            lifecycle.down(3)
        self.assert_app_not_stopped()

    def test_interrupt_during_drain_does_not_stop_app_or_remove_checkpoint(self):
        self.counts = dict(IDLE, active_responses=1, idle_snapshot=False)
        with patch.object(lifecycle.time, 'sleep', side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            lifecycle.down(3)
        self.assert_app_not_stopped()
        self.fake_verify_gate(lifecycle.load())

    def test_changed_process_identity_during_drain_prevents_stop(self):
        def restarted_proxy(state, *, gated):
            self.fake_change_proxy(state, gated=gated)
            self.units[lifecycle.APP]['ExecMainStartTimestampMonotonic'] = '3000'
        self.change_proxy.side_effect = restarted_proxy
        with self.assertRaisesRegex(lifecycle.SafetyError, 'exited/restarted'):
            lifecycle.down(3)
        self.assert_app_not_stopped()

    def test_work_appearing_at_final_check_prevents_stop(self):
        self.report.side_effect = [IDLE.copy(), dict(IDLE, active_responses=1, idle_snapshot=False)]
        with patch.object(lifecycle, 'wait_idle'), self.assertRaisesRegex(lifecycle.SafetyError, 'Work appeared'):
            lifecycle.down(3)
        self.assert_app_not_stopped()

    def test_notifier_must_finish_before_stop_and_backup(self):
        self.units[lifecycle.NOTIFIER].update(ActiveState='active', MainPID='999')
        with self.assertRaisesRegex(lifecycle.SafetyError, 'Drain timed out'):
            lifecycle.down(3)
        self.assert_app_not_stopped()
        self.units[lifecycle.NOTIFIER].update(ActiveState='inactive', MainPID='0')
        lifecycle.down(3)
        self.assertEqual(lifecycle.load()['phase'], 'stopped')

    def test_down_waits_stable_then_stops_is_idempotent_and_preserves_other_sites(self):
        lifecycle.down(3)
        self.assertGreaterEqual(self.now, 2)
        self.assertEqual(lifecycle.load()['phase'], 'stopped')
        self.assertIn(OTHER, self.config.read_text())
        self.assertLess(self.events.index(('proxy', 'closed')), self.events.index(('stop', lifecycle.APP)))
        before = self.events.copy()
        lifecycle.down(3)
        self.assertEqual(self.events.count(('stop', lifecycle.APP)), before.count(('stop', lifecycle.APP)))
        self.assertEqual(self.events.count(('proxy', 'closed')), before.count(('proxy', 'closed')))

    def test_preexisting_stopped_app_without_checkpoint_is_not_assumed_safe(self):
        self.units[lifecycle.APP].update(ActiveState='inactive', MainPID='0')
        with self.assertRaisesRegex(lifecycle.SafetyError, 'without a maintenance checkpoint'):
            lifecycle.down(3)
        self.control.assert_not_called()
        self.assertFalse(self.state_file.exists())

    def test_up_checks_private_health_before_opening_and_restores_boot_and_timer(self):
        lifecycle.down(3)
        # Another operator's independent Arcturus change must survive up.
        self.config.write_text(self.config.read_text().replace('8792', '8793'))
        self.events.clear()
        lifecycle.up(3)
        self.assertLess(self.events.index(('start', lifecycle.APP)), self.events.index(('health', 'direct')))
        self.assertLess(self.events.index(('health', 'direct')), self.events.index(('proxy', 'open')))
        self.assertLess(self.events.index(('proxy', 'open')), self.events.index(('start', lifecycle.TIMER)))
        self.assertIn(OTHER.replace('8792', '8793'), self.config.read_text())
        self.assertEqual(self.units[lifecycle.APP]['UnitFileState'], 'enabled')
        self.assertEqual(self.units[lifecycle.TIMER]['UnitFileState'], 'enabled')
        self.assertFalse(self.state_file.exists())
        self.assertEqual(len(list(self.root.glob('completed-*.json'))), 1)
        self.events.clear()
        lifecycle.up(3)
        self.assertEqual(self.events, [('health', 'proxy')])

    def test_up_preserves_initial_disabled_boot_and_inactive_timer(self):
        self.units[lifecycle.APP]['UnitFileState'] = 'disabled'
        self.units[lifecycle.TIMER].update(UnitFileState='disabled', ActiveState='inactive')
        lifecycle.down(3)
        self.events.clear()
        lifecycle.up(3)
        self.assertEqual(self.units[lifecycle.APP]['UnitFileState'], 'disabled')
        self.assertEqual(self.units[lifecycle.TIMER]['UnitFileState'], 'disabled')
        self.assertNotIn(('start', lifecycle.TIMER), self.events)

    def test_failed_private_health_retains_gate_and_checkpoint(self):
        lifecycle.down(3)
        self.events.clear()
        self.health.side_effect = lifecycle.SafetyError('Fixture health failure')
        with self.assertRaisesRegex(lifecycle.SafetyError, 'Startup health timed out'):
            lifecycle.up(3)
        self.assertNotIn(('proxy', 'open'), self.events)
        self.assertNotIn(('start', lifecycle.TIMER), self.events)
        self.assertEqual(lifecycle.load()['phase'], 'starting')
        self.fake_verify_gate(lifecycle.load())

    def test_retry_after_timer_failure_does_not_restart_app_or_regate_public_site(self):
        lifecycle.down(3)
        def fail_timer(action, name):
            if action == 'start' and name == lifecycle.TIMER:
                raise lifecycle.SafetyError('Fixture timer failure')
            self.fake_control(action, name)
        self.control.side_effect = fail_timer
        with self.assertRaisesRegex(lifecycle.SafetyError, 'Fixture timer failure'):
            lifecycle.up(3)
        self.assertEqual(lifecycle.load()['phase'], 'opening')
        self.control.side_effect = self.fake_control
        self.events.clear()
        lifecycle.up(3)
        self.assertNotIn(('proxy', 'closed'), self.events)
        self.assertNotIn(('start', lifecycle.APP), self.events)
        self.assertIn(('start', lifecycle.TIMER), self.events)
        self.assertFalse(self.state_file.exists())

    def test_opening_checkpoint_with_failed_app_reestablishes_gate_before_restart(self):
        lifecycle.down(3)
        state = lifecycle.load()
        state['phase'] = 'opening'
        lifecycle.save(state)
        self.config.write_text(NORMAL + OTHER)
        self.units[lifecycle.APP].update(ActiveState='failed', MainPID='0', Result='exit-code')
        self.events.clear()
        lifecycle.up(3)
        self.assertLess(self.events.index(('proxy', 'closed')), self.events.index(('start', lifecycle.APP)))
        self.assertLess(self.events.index(('health', 'direct')), self.events.index(('proxy', 'open')))
        self.assertFalse(self.state_file.exists())

    def test_failed_app_without_checkpoint_has_no_automatic_start(self):
        self.units[lifecycle.APP].update(ActiveState='failed', MainPID='0')
        with self.assertRaisesRegex(lifecycle.SafetyError, 'failed or transitioning'):
            lifecycle.up(3)
        self.control.assert_not_called()


if __name__ == '__main__':
    unittest.main()
