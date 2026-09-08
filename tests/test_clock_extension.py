"""Approved pauses preserve prior thinking and settle correctly after resumption."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from astra_engine import clock


class ExtensionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "clock.jsonl"
        self.stamp = datetime(2026, 9, 8, tzinfo=timezone.utc)
        self.mono = 10000.0
        mock = patch.object(clock, "_sample", lambda: (self.stamp, self.mono))
        mock.start()
        self.addCleanup(mock.stop)
        clock.create_game_clock(self.path, charge_to_submission=True)
        clock.observe_turn(self.path, 1)

    def advance(self, seconds):
        self.stamp += timedelta(seconds=seconds)
        self.mono += seconds

    def resume(self, paused, **kwargs):
        return clock.resume_with_extension(self.path, paused_utc=paused,
            resumed_utc=self.stamp, extra_seconds=900, reason="User approved extra time",
            adjustment_id="extension-1", **kwargs)

    def test_append_only_resumption_keeps_overrun_and_shares_new_query_allocation(self):
        self.advance(3690)
        paused = self.stamp
        before = self.path.read_bytes()
        self.advance(1800)
        status = self.resume(paused)
        self.assertTrue(self.path.read_bytes().startswith(before))
        self.assertEqual(status["game_seconds_used"], 3690)
        self.assertEqual(status["total_seconds"], 4500)
        self.assertEqual(status["game_remaining_seconds"], 810)
        self.assertEqual(status["elapsed_seconds"], 3690)
        self.assertEqual(status["remaining_seconds"], 120)
        self.assertEqual(status["query_available_seconds"], 80)
        self.assertEqual(status["refunded_seconds"], 0)
        self.assertEqual(status["excluded_pause_seconds"], 1800)
        self.advance(5)
        with clock.query_clock(self.path, 10) as ticket:
            self.advance(8)
        self.assertEqual(ticket["allotted_seconds"], 10)
        status = clock.clock_status(self.path)
        self.assertEqual(status["game_seconds_used"], 3703)
        self.assertEqual(status["query_available_seconds"], 67)

    def test_verified_submission_excludes_pause_and_bot_time_then_fixed_next_turn(self):
        self.advance(110)
        paused = self.stamp
        self.advance(300)
        self.resume(paused)
        self.advance(20)
        submitted = self.stamp
        self.advance(10)
        verified = self.stamp
        self.advance(5)
        done = clock.verify_submission(self.path, 1, "e7e5", submitted_utc=submitted,
                                       verified_utc=verified)
        self.assertEqual(done["game_seconds_used"], 130)
        self.assertEqual(done["excluded_verification_seconds"], 10)
        self.assertEqual(done["excluded_pause_seconds"], 300)
        self.advance(100)
        next_turn = clock.observe_turn(self.path, 3)
        self.assertEqual(next_turn["allocation_seconds"], 120)
        self.assertEqual(next_turn["query_available_seconds"], 80)
        self.assertEqual(next_turn["elapsed_seconds"], 0)
        self.assertEqual(next_turn["game_seconds_used"], 130)

    def test_finish_without_submission_preserves_pre_pause_time(self):
        self.advance(140)
        paused = self.stamp
        self.advance(400)
        self.resume(paused)
        self.advance(125)
        done = clock.finish_game_clock(self.path, "0-1")
        self.assertEqual(done["game_seconds_used"], 265)
        self.assertEqual(done["verified_turn_overruns"], [{"ply": 1, "seconds": 5}])

    def test_backdated_settlement_cannot_precede_resumption(self):
        self.advance(10)
        paused = self.stamp
        self.advance(100)
        self.resume(paused)
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "resumption"):
            clock.verify_submission(self.path, 1, "e7e5", submitted_utc=paused)
        with self.assertRaisesRegex(ValueError, "resumption"):
            clock.record_event(self.path, "submission", move="e7e5", submitted_utc=paused)
        self.assertEqual(self.path.read_bytes(), before)

    def test_duplicate_id_and_pausing_over_recorded_analysis_are_rejected(self):
        self.advance(10)
        paused = self.stamp
        self.advance(1)
        clock.record_event(self.path, "decision", move="e7e5")
        self.advance(100)
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "recorded analysis"):
            self.resume(paused)
        self.assertEqual(self.path.read_bytes(), before)
        paused = self.stamp
        self.advance(20)
        self.resume(paused)
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "already been applied"):
            self.resume(paused)
        self.assertEqual(self.path.read_bytes(), before)

    def test_documented_boundary_balance_retains_small_sampling_difference(self):
        self.advance(100.009)
        paused = self.stamp
        clock.record_event(self.path, "note", paused_utc=paused.isoformat(), own_seconds_at_pause=100)
        self.advance(500)
        status = self.resume(paused)
        self.assertEqual(status["game_seconds_used"], 100)
        extension = status["time_extensions"][0]
        self.assertAlmostEqual(extension["boundary_sample_difference_seconds"], -.009)
        self.assertIsNotNone(extension["boundary_note_seq"])

    def test_remaining_total_still_bounds_fixed_turn_target(self):
        self.advance(4490)
        paused = self.stamp
        self.advance(100)
        status = self.resume(paused)
        self.assertEqual(status["remaining_seconds"], 10)
        self.assertEqual(status["query_available_seconds"], 0)
        self.advance(11)
        status = clock.clock_status(self.path)
        self.assertEqual(status["game_overrun_seconds"], 1)

    def test_missing_reason_bad_window_and_bad_reserve_do_not_mutate(self):
        before = self.path.read_bytes()
        for options in ({"paused_utc": self.stamp+timedelta(seconds=1)},
                        {"reason": ""}, {"turn_seconds": 40}, {"extra_seconds": 0}):
            values = dict(paused_utc=self.stamp, resumed_utc=self.stamp, extra_seconds=900,
                          reason="User approved", adjustment_id="x")
            values.update(options)
            with self.subTest(options=options), self.assertRaises(ValueError):
                clock.resume_with_extension(self.path, **values)
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
