"""Safety regressions for the GPT-2 maintenance operator helper; no host calls."""
import importlib.util
from contextlib import nullcontext
from pathlib import Path
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("gpt2_maintenance", Path(__file__).parents[1] / "tools/ops/gpt2_maintenance.py")
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)

PUBLIC = ("gpt2-chat.com {\n    rewrite * ?\n    encode gzip\n"
          "    reverse_proxy 127.0.0.1:8899 {\n        header_up Host {http.request.hostport}\n    }\n}\n")
LAB = ("codex-test.gpt2-chat.com {\n    @beta path /example-private /example-private/*\n"
       "    handle @beta {\n        reverse_proxy 127.0.0.1:8900 {\n            flush_interval -1\n        }\n"
       "    }\n    handle {\n        respond \"Not found\" 404\n    }\n}\n")
OTHER = "astraplayschess.com {\n    import new-games.caddy\n    reverse_proxy 127.0.0.1:8791\n}\n"
MARKER = "a" * 32


def health(waiting=0, running=False, ttl=600):
    return {"queue": {"waiting": waiting, "running": running}, "limits": {"result_ttl_seconds": ttl}}


def state():
    return {"marker": MARKER, "services": {m.PUBLIC: {"original": PUBLIC, "phase": "prepared", "enabled": "enabled", "identity": ["10", "20"]},
                                          m.LAB: {"original": LAB, "phase": "prepared", "enabled": "disabled", "identity": ["11", "21"]}}}


class Clock:
    now = 0
    def clock(self):
        return self.now
    def sleep(self, seconds):
        self.now += seconds


class ConfigTests(unittest.TestCase):
    def test_only_public_generation_posts_are_gated(self):
        gate = m.gated_block(m.PUBLIC, PUBLIC, MARKER)
        self.assertIn("method POST", gate)
        self.assertIn("path /api/message /api/regenerate", gate)
        self.assertNotIn("/api/result", gate)
        self.assertIn("reverse_proxy 127.0.0.1:8899", gate)

    def test_private_gate_stays_inside_capability_handle(self):
        gate = m.gated_block(m.LAB, LAB, MARKER)
        self.assertIn("handle @beta {\n        header Content-Type", gate)
        self.assertTrue(gate.endswith('    handle {\n        respond "Not found" 404\n    }\n}\n'))
        self.assertIn("@beta path /example-private /example-private/*", gate)

    def test_roundtrip_preserves_other_sites_and_new_edits(self):
        text = OTHER + PUBLIC + LAB
        gated = m.gated_block(m.PUBLIC, PUBLIC, MARKER)
        text = m.replace_block(text, m.PUBLIC, PUBLIC, gated)
        text = text.replace("8791", "9999")
        restored = m.replace_block(text, m.PUBLIC, gated, PUBLIC)
        self.assertEqual(restored, OTHER.replace("8791", "9999") + PUBLIC + LAB)

    def test_independently_edited_site_refused(self):
        with self.assertRaises(m.SafetyError):
            m.replace_block(PUBLIC.replace("encode gzip", "encode zstd gzip"), m.PUBLIC, PUBLIC, "wrong")

    def test_duplicate_header_refused(self):
        with self.assertRaises(m.SafetyError):
            m.site_block(PUBLIC + PUBLIC, m.HOSTS[m.PUBLIC])

    def test_unsupported_route_refused(self):
        with self.assertRaises(m.SafetyError):
            m.gated_block(m.LAB, LAB.replace("handle @beta", "handle @other"), MARKER)

    def test_duplicate_proxy_refused(self):
        with self.assertRaises(m.SafetyError):
            m.normal_block(m.PUBLIC, PUBLIC.replace("    encode gzip", "    reverse_proxy 127.0.0.1:8899"))

    def test_bad_marker_refused(self):
        with self.assertRaises(m.SafetyError):
            m.gated_block(m.PUBLIC, PUBLIC, '"\nmalicious')


class RetentionTests(unittest.TestCase):
    def run_policy(self, observe=None, connections=None, timeout=1200):
        clock = Clock()
        calls = []
        result = m.retain_public(lambda: observe(clock.now) if observe else health(),
                                 lambda: connections(clock.now) if connections else True,
                                 timeout=timeout, clock=clock.clock, sleep=clock.sleep, emit=calls.append)
        return result, clock.now, calls

    def test_full_ttl_even_when_initially_idle(self):
        ttl, elapsed, _ = self.run_policy()
        self.assertEqual((ttl, elapsed), (600, 600))

    def test_connection_settlement_precedes_retention(self):
        _, elapsed, _ = self.run_policy(connections=lambda t: t >= 100)
        self.assertEqual(elapsed, 700)

    def test_work_reappearance_resets_timer(self):
        _, elapsed, calls = self.run_policy(observe=lambda t: health(1) if 300 <= t < 400 else health())
        self.assertEqual(elapsed, 1000)
        self.assertEqual(len(calls), 2)

    def test_service_larger_ttl_is_honored(self):
        ttl, elapsed, _ = self.run_policy(observe=lambda t: health(ttl=900))
        self.assertEqual((ttl, elapsed), (900, 900))

    def test_shorter_ttl_cannot_lower_600_floor(self):
        ttl, elapsed, _ = self.run_policy(observe=lambda t: health(ttl=10))
        self.assertEqual((ttl, elapsed), (600, 600))

    def test_busy_queue_times_out_without_success(self):
        with self.assertRaises(m.SafetyError):
            self.run_policy(observe=lambda t: health(running=True), timeout=600)

    def test_invalid_observation_fails_closed(self):
        with self.assertRaises(m.SafetyError):
            self.run_policy(observe=lambda t: health(waiting="0"))

    def test_boundary_race_fails_closed(self):
        clock = Clock()
        calls_at_end = 0
        def observe():
            nonlocal calls_at_end
            if clock.now >= 600:
                calls_at_end += 1
            return health(1) if calls_at_end == 2 else health()
        with self.assertRaises(m.SafetyError):
            m.retain_public(observe, lambda: True, clock=clock.clock, sleep=clock.sleep, emit=lambda _: None)


class LifecycleTests(unittest.TestCase):
    def test_lab_confirmation_does_not_skip_actual_quiet_checks(self):
        s = state()
        with patch.object(m, "unit", return_value={"MainPID": "11", "ExecMainStartTimestampMonotonic": "21"}), \
             patch.object(m, "quiet_lab", side_effect=m.SafetyError("busy")) as quiet, \
             patch.object(m, "change_proxy") as change:
            with self.assertRaises(m.SafetyError):
                m.gate(s, m.LAB, True)
            quiet.assert_called_once()
            change.assert_not_called()

    def test_lab_confirmation_required_before_checks_or_gate(self):
        with patch.object(m, "unit", return_value={"MainPID": "11", "ExecMainStartTimestampMonotonic": "21"}), \
             patch.object(m, "quiet_lab") as quiet:
            with self.assertRaises(m.SafetyError):
                m.gate(state(), m.LAB, False)
            quiet.assert_not_called()

    def test_lab_60_seconds_presence_expiry_wait(self):
        clock = Clock()
        with patch.object(m, "unit", return_value={"MainPID": "11", "ExecMainStartTimestampMonotonic": "21"}), \
             patch.object(m, "lab_activity", return_value={"idle": True, "pending_human": 6}), \
             patch.object(m, "settled", return_value=True):
            m.quiet_lab(state(), clock=clock.clock, sleep=clock.sleep)
        self.assertEqual(clock.now, 60)

    def test_lab_containers_or_pending_worker_prevent_stop(self):
        s = state()
        s["services"][m.LAB]["phase"] = "gated"
        with patch.object(m, "unit", return_value={"ActiveState": "active", "MainPID": "11", "ExecMainStartTimestampMonotonic": "21"}), \
             patch.object(m, "lab_activity", return_value={"idle": False}), \
             patch.object(m, "control") as control:
            with self.assertRaises(m.SafetyError):
                m.stop(s, m.LAB, 1200)
            control.assert_not_called()

    def test_public_stop_requires_gate(self):
        with patch.object(m, "control") as control:
            with self.assertRaises(m.SafetyError):
                m.stop(state(), m.PUBLIC, 1200)
            control.assert_not_called()

    def test_public_final_work_race_does_not_stop(self):
        s = state()
        s["services"][m.PUBLIC]["phase"] = "gated"
        config = m.gated_block(m.PUBLIC, PUBLIC, MARKER)
        with patch.object(m, "unit", return_value={"ActiveState": "active", "MainPID": "10", "ExecMainStartTimestampMonotonic": "20"}), \
             patch.object(m, "verify_gate"), patch.object(m, "retain_public"), \
             patch.object(m, "lock", return_value=nullcontext()), \
             patch.object(m, "CONFIG") as fake_config, \
             patch.object(m, "health", return_value=health(waiting=1)), \
             patch.object(m, "control") as control:
            fake_config.read_text.return_value = config
            with self.assertRaises(m.SafetyError):
                m.stop(s, m.PUBLIC, 1200)
            control.assert_not_called()

    def test_private_final_work_race_does_not_stop(self):
        s = state()
        s["services"][m.LAB]["phase"] = "gated"
        config = m.gated_block(m.LAB, LAB, MARKER)
        with patch.object(m, "unit", return_value={"ActiveState": "active", "MainPID": "11", "ExecMainStartTimestampMonotonic": "21"}), \
             patch.object(m, "verify_gate"), patch.object(m, "settled", return_value=True), \
             patch.object(m, "lock", return_value=nullcontext()), \
             patch.object(m, "CONFIG") as fake_config, \
             patch.object(m, "lab_activity", side_effect=[{"idle": True}, {"idle": False}]), \
             patch.object(m, "control") as control:
            fake_config.read_text.return_value = config
            with self.assertRaises(m.SafetyError):
                m.stop(s, m.LAB, 1200)
            control.assert_not_called()

    def test_reopening_requires_explicit_completed_validation(self):
        with patch.object(m, "change_proxy") as change:
            with self.assertRaises(m.SafetyError):
                m.reopen(state(), False)
            change.assert_not_called()

    def test_lab_start_requires_public_first(self):
        s = state()
        s["services"][m.LAB]["phase"] = "stopped"
        with patch.object(m, "control") as control:
            with self.assertRaises(m.SafetyError):
                m.start(s, m.LAB)
            control.assert_not_called()


if __name__ == "__main__":
    unittest.main()
