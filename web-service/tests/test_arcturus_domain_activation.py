"""Domain activation checks without network access, processes or service signals."""

import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import call, patch


SOURCE = Path(__file__).resolve().parents[1] / 'tools' / 'ops' / 'activate_arcturus_domain.py'
SPEC = importlib.util.spec_from_file_location('arcturus_domain_activation', SOURCE)
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)
common = helper.common
ORIGINAL = (b'{\r\n    admin off\r\n}\r\nastraplayschess.com {\r\n'
            b'    reverse_proxy 127.0.0.1:8788\r\n}\r\n'
            b'www.astraplayschess.com {\r\n'
            b'    redir https://astraplayschess.com{uri} permanent\r\n}\r\n'
            b'arcturus.astraplayschess.com {\r\n'
            b'    reverse_proxy 127.0.0.1:8792\r\n}')
ARCTURUS = {'config': {'player_name': 'Arcturus', 'persona_id': 'arcturus',
                       'model': 'z-ai/glm-5.3-flash:nitro',
                       'canonical_origin': 'https://arcturuschess.com'},
             'index_sha256': 'saved-index-hash'}
BASELINE = {'astra': {'config': {'model': 'astra'}, 'index_sha256': 'original'},
            'arcturus': ARCTURUS}
STAMPS = {common.ASTRA_UNIT: (222, 'start-222'), helper.ARCTURUS_UNIT: (333, 'start-333')}


class CandidateAndRouteTests(unittest.TestCase):
    def test_candidate_preserves_original_bytes_and_old_proxy(self):
        candidate = helper.candidate_bytes(ORIGINAL)
        self.assertEqual(candidate[:len(ORIGINAL)], ORIGINAL)
        self.assertEqual(candidate[len(ORIGINAL):], helper.BLOCK)
        self.assertIn(b'}\narcturuschess.com {', candidate)
        self.assertEqual(candidate.count(b'arcturus.astraplayschess.com'), 1)
        self.assertEqual(candidate.count(b'reverse_proxy 127.0.0.1:8792'), 2)
        self.assertIn(b'redir https://arcturuschess.com{uri} 308', candidate)

    def test_refuses_duplicate_import_missing_old_host_and_oversize(self):
        cases = (ORIGINAL + helper.BLOCK, b'import other.conf\n' + ORIGINAL,
                 ORIGINAL.replace(b'www.astraplayschess.com', b'other.example'),
                 ORIGINAL.replace(b'arcturus.astraplayschess.com', b'other.example'),
                 ORIGINAL + b' ' * common.LIMIT, b'', ORIGINAL + b'\xff')
        for number, original in enumerate(cases):
            with self.subTest(case=number), self.assertRaises(helper.ActivationError):
                helper.candidate_bytes(original)

    def test_preflight_requires_new_host_loopback_and_existing_site_equivalence(self):
        with patch.object(helper, 'existing_sites', return_value=BASELINE), \
                patch.object(common, 'site_snapshot', return_value=ARCTURUS) as snapshot:
            self.assertEqual(helper.preflight_routes(), (BASELINE, ARCTURUS))
            snapshot.assert_called_once_with(helper.HOST, port=8792)
            snapshot.return_value = dict(ARCTURUS, index_sha256='different')
            with self.assertRaisesRegex(helper.ActivationError, 'differs'):
                helper.preflight_routes()

    def test_wrong_identity_refused_even_if_hosts_match(self):
        for field, value in (('player_name', 'Astra'), ('persona_id', 'astra'), ('model', 'other')):
            wrong = dict(ARCTURUS, config=dict(ARCTURUS['config'], **{field: value}))
            with self.subTest(field=field), \
                    patch.object(helper, 'existing_sites', return_value=dict(BASELINE, arcturus=wrong)), \
                    patch.object(common, 'site_snapshot', return_value=wrong), \
                    self.assertRaisesRegex(helper.ActivationError, 'unexpected identity'):
                helper.preflight_routes()

    def test_www_requires_308_and_preserves_path_and_query(self):
        with patch.object(common, 'site_snapshot', return_value=ARCTURUS), \
                patch.object(common, 'request', side_effect=lambda host, path:
                             (308, 'https://' + helper.HOST + path, b'')) as request:
            helper.canonical_site(ARCTURUS)
            self.assertEqual(request.call_args_list, [call(helper.WWW, '/'),
                             call(helper.WWW, '/games/route-check.html?check=domain&value=two')])
            for response in ((301, 'https://' + helper.HOST + '/', b''),
                             (308, 'https://' + helper.OLD_HOST + '/', b''),
                             (308, 'https://' + helper.HOST + '/', b'')):
                request.side_effect = None
                request.return_value = response
                with self.subTest(response=response), self.assertRaises(helper.ActivationError):
                    helper.canonical_site(ARCTURUS)


class TransactionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.config = Path(temporary.name) / 'Caddyfile'
        self.config.write_bytes(ORIGINAL)
        self.descriptor = os.open(self.config, os.O_RDWR | getattr(os, 'O_BINARY', 0))
        self.addCleanup(os.close, self.descriptor)
        self.original_stat = os.fstat(self.descriptor)
        self.candidate = helper.candidate_bytes(ORIGINAL)
        self.report = {}
        self.start_patch(common, 'CONFIG', self.config)
        self.caddy = self.start_patch(common, 'caddy_identity', return_value=(111, 'caddy-start'))
        self.pids = self.start_patch(common, 'active_pid', side_effect=lambda unit:
                                    {common.ASTRA_UNIT: 222, helper.ARCTURUS_UNIT: 333}[unit])
        self.start_patch(common, 'process_stamp', side_effect=lambda pid: (pid, 'start-%d' % pid))
        self.signal = self.start_patch(common, 'signal_caddy')
        self.existing = self.start_patch(helper, 'existing_sites', return_value=BASELINE)
        self.canonical = self.start_patch(helper, 'canonical_site')
        self.start_patch(helper, 'await_verified_routes', side_effect=lambda check, **kwargs: check())

    def start_patch(self, target, name, *args, **kwargs):
        patcher = patch.object(target, name, *args, **kwargs)
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def activate(self):
        helper.activate(self.descriptor, self.original_stat, ORIGINAL, self.candidate,
                        (111, 'caddy-start'), STAMPS, BASELINE, ARCTURUS, self.report)

    def test_success_preserves_inode_and_all_processes(self):
        self.activate()
        self.assertEqual(self.config.read_bytes(), self.candidate)
        self.assertEqual(self.config.stat().st_ino, self.original_stat.st_ino)
        self.signal.assert_called_once_with(self.original_stat, expected=(111, 'caddy-start'))
        self.canonical.assert_called_once_with(ARCTURUS)
        for flag in ('caddy_pid_stable', 'astra_pid_stable', 'arcturus_pid_stable',
                     'old_arcturus_preserved', 'www_redirect_verified'):
            self.assertTrue(self.report[flag])

    def test_failed_new_site_or_redirect_restores_original_bytes_and_routes(self):
        self.canonical.side_effect = helper.ActivationError('Canonical route failed')
        with self.assertRaises(helper.ActivationError):
            self.activate()
        self.assertEqual(self.config.read_bytes(), ORIGINAL)
        self.assertEqual(self.config.stat().st_ino, self.original_stat.st_ino)
        self.assertEqual(self.signal.call_args_list,
                         [call(self.original_stat, expected=(111, 'caddy-start'))] * 2)
        self.assertIn('original routes verified', self.report['rollback'])
        self.assertEqual(self.existing.call_count, 3)

    def test_changed_old_arcturus_route_rolls_back(self):
        self.existing.side_effect = [BASELINE, dict(BASELINE, arcturus={'changed': True}), BASELINE]
        with self.assertRaises(helper.ActivationError):
            self.activate()
        self.assertEqual(self.config.read_bytes(), ORIGINAL)
        self.assertIn('original routes verified', self.report['rollback'])

    def test_stale_config_or_process_or_original_route_prevents_writes(self):
        for case in ('bytes', 'caddy', 'astra', 'arcturus', 'route'):
            with self.subTest(case=case):
                self.config.write_bytes(ORIGINAL)
                self.caddy.return_value = (111, 'caddy-start')
                self.pids.side_effect = lambda unit: STAMPS[unit][0]
                self.existing.return_value = BASELINE
                if case == 'bytes':
                    self.config.write_bytes(ORIGINAL + b'\n# operator update')
                elif case == 'caddy':
                    self.caddy.return_value = (444, 'new-caddy')
                elif case in ('astra', 'arcturus'):
                    changed_unit = common.ASTRA_UNIT if case == 'astra' else helper.ARCTURUS_UNIT
                    self.pids.side_effect = lambda unit: 444 if unit == changed_unit else STAMPS[unit][0]
                else:
                    self.existing.return_value = {'changed': True}
                before = self.config.read_bytes()
                with self.assertRaises(helper.ActivationError):
                    self.activate()
                self.assertEqual(self.config.read_bytes(), before)
                self.signal.assert_not_called()

    def test_concurrent_append_after_write_is_preserved_for_manual_recovery(self):
        changed = self.candidate + b'\n# external update'
        self.signal.side_effect = lambda *args, **kwargs: self.config.write_bytes(changed)
        with self.assertRaises(helper.ActivationError):
            self.activate()
        self.assertEqual(self.config.read_bytes(), changed)
        self.assertEqual(self.signal.call_count, 1)
        self.assertIn('manual recovery required', self.report['rollback'])

    def test_own_partial_write_is_restored_but_external_truncation_is_preserved(self):
        real_rewrite = common.rewrite
        for own_write in (True, False):
            with self.subTest(own_write=own_write):
                self.config.write_bytes(ORIGINAL)
                self.signal.reset_mock()
                changed = self.candidate[:-8] if own_write else ORIGINAL[:-8]
                calls = []
                def fail_once(descriptor, data):
                    calls.append(data)
                    real_rewrite(descriptor, changed if len(calls) == 1 else data)
                    if len(calls) == 1:
                        raise OSError('Write interrupted')
                with patch.object(common, 'rewrite', side_effect=fail_once), self.assertRaises(OSError):
                    self.activate()
                self.assertEqual(self.config.read_bytes(), ORIGINAL if own_write else changed)
                self.assertEqual(self.signal.call_count, 1 if own_write else 0)
                self.assertIn('original routes verified' if own_write else 'manual recovery required',
                              self.report['rollback'])

    def test_changed_application_process_after_reload_is_not_reported_as_success(self):
        self.signal.side_effect = lambda *args, **kwargs: setattr(self.pids, 'side_effect',
                                        lambda unit: 444 if unit == helper.ARCTURUS_UNIT else 222)
        with self.assertRaises(helper.ActivationError):
            self.activate()
        self.assertEqual(self.config.read_bytes(), ORIGINAL)
        self.assertNotIn('applied', self.report)
        self.assertIn('manual recovery required', self.report['rollback'])


class RouteWaitTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.sleeps = []
        def sleep(seconds):
            self.sleeps.append(seconds)
            self.now += seconds
        monotonic = patch.object(helper.time, 'monotonic', side_effect=lambda: self.now)
        sleeping = patch.object(helper.time, 'sleep', side_effect=sleep)
        monotonic.start()
        sleeping.start()
        self.addCleanup(monotonic.stop)
        self.addCleanup(sleeping.stop)

    def test_retries_at_two_second_intervals_and_returns_after_success(self):
        with patch.object(helper, 'canonical_site', side_effect=[OSError('Certificate pending'), None]) as check:
            helper.await_verified_routes(check)
        self.assertEqual(check.call_count, 2)
        self.assertEqual(self.sleeps, [2])

    def test_default_window_allows_certificate_delay_beyond_old_35_seconds(self):
        calls = []
        def check():
            calls.append(self.now)
            if self.now < 40:
                raise helper.ActivationError('Certificate pending')
        helper.await_verified_routes(check)
        self.assertEqual(calls[-1], 40)
        self.assertEqual(self.sleeps, [2] * 20)

    def test_timeout_is_bounded_and_does_not_start_a_request_at_deadline(self):
        for seconds in (5, 20, 180):
            with self.subTest(seconds=seconds):
                self.now = 0
                self.sleeps.clear()
                with patch.object(helper, 'canonical_site', side_effect=OSError('Still pending')) as check:
                    with self.assertRaisesRegex(helper.ActivationError, 'reload window'):
                        helper.await_verified_routes(check, seconds=seconds)
                self.assertEqual(self.now, seconds)
                self.assertEqual(check.call_count, (seconds + 1) // 2)
                self.assertTrue(all(0 < delay <= 2 for delay in self.sleeps))

    def test_unexpected_error_is_not_retried(self):
        with patch.object(helper, 'canonical_site', side_effect=RuntimeError('Unexpected')) as check:
            with self.assertRaises(RuntimeError):
                helper.await_verified_routes(check)
        self.assertEqual(check.call_count, 1)
        self.assertEqual(self.sleeps, [])


if __name__ == '__main__':
    unittest.main()
