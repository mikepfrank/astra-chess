"""Earned classical time controls, with deterministic own-turn timestamps."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from astra_engine import clock


class StagedClockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "clock.jsonl"
        self.stamp = datetime(2026, 9, 8, tzinfo=timezone.utc)
        self.mono = 10000.0
        mock = patch.object(clock, "_sample", lambda: (self.stamp, self.mono))
        mock.start()
        self.addCleanup(mock.stop)

    def advance(self, seconds):
        self.stamp += timedelta(seconds=seconds)
        self.mono += seconds

    def create(self, **kwargs):
        options = dict(total_seconds=5400, charge_to_submission=True,
                       increment_seconds=30, stage_moves=40, stage_seconds=1800,
                       ordinary_seconds=120, critical_seconds=240, reserve_seconds=40)
        options.update(kwargs)
        return clock.create_game_clock(self.path, **options)

    def events(self):
        return [json.loads(line) for line in self.path.read_text().splitlines()]

    def test_first_increment_waits_for_verification_and_excludes_opponent_time(self):
        start = self.create()
        self.assertEqual(start["clock_schema"], 2)
        self.assertEqual(start["total_seconds"], 5400)
        self.assertEqual(start["earned_increment_seconds"], 0)
        self.assertEqual(start["own_moves_to_next_stage"], 40)
        turn = clock.observe_turn(self.path, 0)
        self.assertEqual(turn["allocation_seconds"], 120)
        self.assertEqual(turn["query_available_seconds"], 80)
        self.advance(35)
        clock.record_event(self.path, "submission", move="e2e4")
        self.advance(25)
        pending = clock.clock_status(self.path)
        self.assertEqual(pending["completed_own_moves"], 0)
        self.assertEqual(pending["total_seconds"], 5400)
        self.assertEqual(pending["game_seconds_used"], 60)
        done = clock.verify_submission(self.path, 0, "e2e4")
        self.assertEqual(done["completed_own_moves"], 1)
        self.assertEqual(done["game_seconds_used"], 35)
        self.assertEqual(done["total_seconds"], 5430)
        self.assertEqual(done["earned_increment_seconds"], 30)
        self.assertEqual(done["game_remaining_seconds"], 5395)
        self.assertEqual(done["excluded_verification_seconds"], 25)
        self.advance(100)
        next_turn = clock.observe_turn(self.path, 2)
        self.assertEqual(next_turn["game_seconds_used"], 35)
        self.assertEqual(next_turn["completed_own_moves"], 1)
        self.assertEqual(next_turn["own_moves_to_next_stage"], 39)

    def test_black_fortieth_own_move_awards_one_stage_and_replay_is_idempotent(self):
        self.create()
        for index in range(41):
            ply = 2*index+1  # Full-move/ply parity does not count opponent moves.
            clock.observe_turn(self.path, ply)
            self.advance(10)
            done = clock.verify_submission(self.path, ply, "a7a6")
            self.assertEqual(done["completed_own_moves"], index+1)
            self.assertEqual(done["earned_increment_seconds"], 30*(index+1))
            self.assertEqual(done["earned_stage_seconds"], 1800 if index >= 39 else 0)
            if index == 38:
                self.assertEqual(done["total_seconds"], 6570)
                self.assertEqual(done["own_moves_to_next_stage"], 1)
                self.assertEqual(done["stage_grants"], [])
            if index == 39:
                self.assertEqual(done["total_seconds"], 8400)
                self.assertEqual(done["game_seconds_used"], 400)
                self.assertEqual(done["game_remaining_seconds"], 8000)
                self.assertIsNone(done["next_stage_own_move"])
                event = self.events()[-1]["data"]
                self.assertEqual(event["increment_awarded_seconds"], 30)
                self.assertEqual(event["stage_awarded_seconds"], 1800)
                self.assertEqual(event["game_balance_before_award_seconds"], 6170)
                self.assertEqual(event["game_balance_after_award_seconds"], 8000)
            self.advance(50)  # Opponent time never consumes or earns own time.
        self.assertEqual(done["total_seconds"], 8430)
        self.assertEqual(len(done["stage_grants"]), 1)
        self.assertEqual(done["stage_grants"][0]["own_move"], 40)
        self.assertEqual(done["stage_grants"][0]["ply"], 79)
        before = self.path.read_bytes()
        self.assertEqual(clock.clock_status(self.path), clock.clock_status(self.path))
        with self.assertRaisesRegex(ValueError, "active ply"):
            clock.verify_submission(self.path, 81, "a7a6")
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(clock.clock_status(self.path)["earned_stage_seconds"], 1800)

    def test_queries_rejections_and_critical_markers_never_earn_time(self):
        self.create()
        clock.observe_turn(self.path, 0)
        self.advance(10)
        with clock.query_clock(self.path, 5):
            self.advance(5)
        critical = clock.mark_critical(self.path, "Forcing countercheck")
        self.assertEqual(critical["allocation_seconds"], 240)
        self.assertEqual(critical["elapsed_seconds"], 15)
        self.assertEqual(critical["query_available_seconds"], 185)
        clock.record_event(self.path, "submission", move="e2e4")
        self.advance(10)
        with self.assertRaisesRegex(ValueError, "differs"):
            clock.verify_submission(self.path, 0, "d2d4")
        clock.record_event(self.path, "submission_rejected", reason="Board unchanged")
        clock.record_event(self.path, "query_rejected", reason="Malformed request")
        self.assertEqual(clock.clock_status(self.path)["total_seconds"], 5400)
        self.assertEqual(clock.clock_status(self.path)["completed_own_moves"], 0)
        self.advance(5)
        clock.record_event(self.path, "submission", move="d2d4")
        done = clock.verify_submission(self.path, 0, "d2d4")
        self.assertEqual(done["game_seconds_used"], 30)
        self.assertEqual(done["earned_increment_seconds"], 30)

    def test_low_balance_cannot_borrow_the_imminent_stage_or_increment(self):
        self.create(total_seconds=100, stage_moves=2, reserve_seconds=5)
        first = clock.observe_turn(self.path, 0)
        self.assertEqual(first["allocation_seconds"], 50)
        self.advance(50)
        clock.verify_submission(self.path, 0, "e2e4")
        second = clock.observe_turn(self.path, 2, critical=True)
        self.assertEqual(second["game_remaining_seconds"], 80)
        self.assertEqual(second["allocation_seconds"], 80)
        self.assertEqual(second["query_available_seconds"], 75)
        self.assertEqual(second["earned_stage_seconds"], 0)
        self.advance(81)
        expired = clock.clock_status(self.path)
        self.assertEqual(expired["game_balance_seconds"], -1)
        self.assertEqual(expired["query_available_seconds"], 0)
        with self.assertRaisesRegex(ValueError, "reserve"):
            with clock.query_clock(self.path, 1):
                self.fail("No future credit can fund this search")
        done = clock.verify_submission(self.path, 2, "g1f3")
        # A cooperative clock records a late real move; its incoming credit does
        # not conceal that the move had already exceeded the then-earned budget.
        self.assertEqual(done["game_remaining_seconds"], 1829)
        self.assertEqual(done["game_overrun_seconds"], 0)
        self.assertEqual(done["verified_game_overruns"], [{"ply": 2, "seconds": 1}])
        event = self.events()[-1]["data"]
        self.assertEqual(event["game_overrun_before_award_seconds"], 1)
        self.assertEqual(event["game_balance_before_award_seconds"], -1)
        self.assertEqual(event["increment_awarded_seconds"], 30)
        self.assertEqual(event["stage_awarded_seconds"], 1800)

    def test_resignation_does_not_count_as_a_completed_move_or_award_time(self):
        self.create(stage_moves=1)
        clock.observe_turn(self.path, 0)
        self.advance(15)
        done = clock.finish_game_clock(self.path, "0-1", reason="resignation")
        self.assertEqual(done["game_seconds_used"], 15)
        self.assertEqual(done["completed_own_moves"], 0)
        self.assertEqual(done["earned_increment_seconds"], 0)
        self.assertEqual(done["earned_stage_seconds"], 0)
        self.assertEqual(done["total_seconds"], 5400)

    def test_user_refund_and_extension_are_separate_from_earned_time(self):
        self.create()
        clock.observe_turn(self.path, 0)
        self.advance(60)
        clock.verify_submission(self.path, 0, "e2e4")
        before = self.path.read_bytes()
        refunded = clock.refund_turn_time(self.path, 0, 20,
            reason="User forgave an interruption", adjustment_id="refund")
        self.assertTrue(self.path.read_bytes().startswith(before))
        self.assertEqual(refunded["earned_increment_seconds"], 30)
        self.assertEqual(refunded["raw_game_seconds_used"], 60)
        self.assertEqual(refunded["game_seconds_used"], 40)
        clock.observe_turn(self.path, 2)
        self.advance(10)
        paused = self.stamp
        self.advance(100)
        clock.resume_with_extension(self.path, paused_utc=paused, resumed_utc=self.stamp,
            extra_seconds=900, reason="User approved extra time", adjustment_id="extension",
            turn_seconds=200)
        self.advance(15)
        done = clock.verify_submission(self.path, 2, "g1f3")
        self.assertEqual(done["original_total_seconds"], 5400)
        self.assertEqual(done["extension_seconds"], 900)
        self.assertEqual(done["earned_increment_seconds"], 60)
        self.assertEqual(done["total_seconds"], 6360)
        self.assertEqual(done["raw_game_seconds_used"], 85)
        self.assertEqual(done["game_seconds_used"], 65)
        self.assertEqual(done["refunded_seconds"], 20)
        self.assertEqual(done["excluded_pause_seconds"], 100)
        self.assertEqual(done["completed_own_moves"], 2)
        self.assertEqual(clock.observe_turn(self.path, 4)["allocation_seconds"], 200)

    def test_legacy_schema_one_retains_fixed_total_without_new_event_fields(self):
        clock.create_game_clock(self.path)
        config = self.events()[0]["data"]
        self.assertEqual(config, dict(schema=1, mode="game", total_seconds=3600.0,
            move_seconds=120.0, reserve_seconds=40.0, charge_to_submission=False))
        self.assertEqual(clock.observe_turn(self.path, 0)["allocation_seconds"], 90)
        self.advance(35)
        clock.record_event(self.path, "submission", move="e2e4")
        self.advance(25)
        done = clock.verify_submission(self.path, 0, "e2e4")
        self.assertEqual(done["game_seconds_used"], 60)
        self.assertEqual(done["total_seconds"], 3600)
        self.assertEqual(done["earned_increment_seconds"], 0)
        self.assertEqual(done["earned_stage_seconds"], 0)
        self.assertEqual(done["game_remaining_seconds"], 3540)
        self.assertNotIn("increment_awarded_seconds", self.events()[-1]["data"])
        before = self.path.read_bytes()
        clock.clock_status(self.path)
        self.assertEqual(self.path.read_bytes(), before)

    def test_increment_without_stage_and_post_stage_forecast_have_no_future_credit(self):
        self.create(stage_moves=None, stage_seconds=0)
        first = clock.observe_turn(self.path, 0)
        self.assertIsNone(first["next_stage_own_move"])
        self.assertEqual(first["allocation_seconds"], 120)
        self.advance(60)
        done = clock.verify_submission(self.path, 0, "e2e4")
        self.assertEqual(done["total_seconds"], 5430)
        self.assertEqual(done["earned_stage_seconds"], 0)
        config = dict(clock._state(clock._read(self.path))["config"], stage_moves=40)
        self.assertEqual(clock._allocation(config, config["total_seconds"]-100, 40, False, 40), 5)
        self.assertEqual(clock._allocation(config, config["total_seconds"]-100, 40, True, 40), 10)
        self.assertEqual(clock._allocation(config, config["total_seconds"]-100, 70, False, 70), 100/12)

    def test_invalid_controls_fail_before_creating_ledger(self):
        invalid = [dict(increment_seconds=-1), dict(increment_seconds=True),
                   dict(stage_moves=0), dict(stage_moves=True), dict(stage_moves=1.5),
                   dict(stage_moves=None), dict(stage_seconds=0), dict(stage_seconds=-1),
                   dict(ordinary_seconds=0), dict(critical_seconds=100),
                   dict(critical_seconds=float("nan")), dict(mode="move"),
                   dict(reserve_seconds=120)]
        for kwargs in invalid:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.create(**kwargs)
            self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
