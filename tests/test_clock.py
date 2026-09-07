"""Shared-clock accounting and manual journal state transitions, without a browser."""
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from astra_engine import clock
import play_engine_game as journal


class FakeTime:
    def __init__(self):
        self.utc = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)
        self.monotonic = 10000.0

    def sample(self):
        return self.utc, self.monotonic

    def advance(self, seconds):
        self.utc += timedelta(seconds=seconds)
        self.monotonic += seconds

    def iso(self):
        return self.utc.isoformat()


class ClockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "clock.jsonl"
        self.time = FakeTime()
        self.patcher = patch.object(clock, "_sample", self.time.sample)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def create(self, **options):
        return clock.create_game_clock(self.path, **options)

    def events(self):
        return [json.loads(line) for line in self.path.read_text().splitlines()]

    def test_shared_queries_review_and_verified_submission_charge_one_interval(self):
        self.create()
        clock.observe_turn(self.path, 0, initial_candidate="e2e4")
        self.time.advance(10)  # Deliberation before first query.
        with clock.query_clock(self.path, 15) as first:
            self.time.advance(12)
        self.assertEqual(first["allotted_seconds"], 15)
        self.time.advance(5)
        with clock.query_clock(self.path, 60) as second:
            self.assertEqual(second["allotted_seconds"], 23)  # 90 - 27 elapsed - 40 reserve.
            self.time.advance(10)
        self.time.advance(12)
        clock.record_event(self.path, "decision", move="e2e4")
        self.time.advance(10)
        clock.record_event(self.path, "submission", move="e2e4")
        self.time.advance(4)
        done = clock.verify_submission(self.path, 0, "e2e4")
        self.assertEqual(done["game_seconds_used"], 63)
        self.assertIsNone(done["active_ply"])
        self.time.advance(80)  # Opponent's time is excluded.
        new = clock.observe_turn(self.path, 2)
        self.assertEqual(new["game_seconds_used"], 63)
        self.assertEqual(new["game_remaining_seconds"], 3537)
        kinds = [e["kind"] for e in self.events()]
        self.assertEqual(kinds.count("query_started"), 2)
        self.assertIn("initial_candidate", kinds)
        self.assertIn("decision", kinds)
        self.assertIn("verification", kinds)

    def test_rejected_browser_click_stays_active_and_same_ply_cannot_restart(self):
        self.create()
        clock.observe_turn(self.path, 0)
        self.time.advance(40)
        clock.record_event(self.path, "submission", move="e2e4")
        self.time.advance(8)
        clock.record_event(self.path, "submission_rejected", reason="Board unchanged")
        with self.assertRaisesRegex(ValueError, "still active"):
            clock.observe_turn(self.path, 0)
        self.assertEqual(clock.clock_status(self.path)["elapsed_seconds"], 48)
        self.assertFalse(clock.clock_status(self.path)["submission_pending_verification"])
        self.time.advance(10)
        clock.verify_submission(self.path, 0, "e2e4")
        with self.assertRaisesRegex(ValueError, "same or an earlier ply"):
            clock.observe_turn(self.path, 0)

    def test_reserve_failure_and_query_exception_retain_time_and_evidence(self):
        self.create()
        clock.observe_turn(self.path, 0)
        with self.assertRaisesRegex(RuntimeError, "query failure"):
            with clock.query_clock(self.path, 5):
                self.time.advance(7)
                raise RuntimeError("query failure")
        event = self.events()[-1]
        self.assertEqual(event["data"]["error"], "RuntimeError")
        self.assertEqual(event["data"]["overrun_seconds"], 2)
        self.assertEqual(clock.clock_status(self.path)["calls"], 1)
        self.time.advance(43)
        with self.assertRaisesRegex(ValueError, "reserve"):
            with clock.query_clock(self.path, 5):
                self.fail("Should not run")
        self.assertEqual(clock.clock_status(self.path)["elapsed_seconds"], 50)

    def test_critical_allowance_keeps_original_start_and_move_policy_is_hard_cap(self):
        self.create()
        clock.observe_turn(self.path, 0)
        self.time.advance(55)
        status = clock.mark_critical(self.path, "Attacked bishop with blocked retreats")
        self.assertEqual(status["allocation_seconds"], 180)
        self.assertEqual(status["elapsed_seconds"], 55)
        self.assertEqual(status["query_available_seconds"], 85)
        other = Path(self.temp.name) / "per-move.jsonl"
        clock.create_game_clock(other, mode="move")
        clock.observe_turn(other, 0, critical=True)
        self.time.advance(125)
        status = clock.mark_critical(other, "Checks continue")
        self.assertEqual(status["allocation_seconds"], 120)
        self.assertEqual(status["turn_overrun_seconds"], 5)
        self.assertIsNone(status["game_remaining_seconds"])

    def test_cumulative_cap_and_later_allocation_shrink(self):
        self.create(total_seconds=800, reserve_seconds=5)
        start = clock.observe_turn(self.path, 0)
        self.assertEqual(start["allocation_seconds"], 20)
        self.time.advance(400)
        clock.verify_submission(self.path, 0, "e2e4")
        later = clock.observe_turn(self.path, 2)
        self.assertLess(later["allocation_seconds"], start["allocation_seconds"])
        self.time.advance(405)
        status = clock.finish_game_clock(self.path, "0-1", reason="resignation")
        self.assertEqual(status["game_overrun_seconds"], 5)
        self.assertEqual(status["game_seconds_used"], 805)
        self.assertEqual(len(status["verified_turn_overruns"]), 2)
        with self.assertRaisesRegex(ValueError, "finished"):
            clock.observe_turn(self.path, 4)

    def test_delayed_observation_and_verification_uncertainty_are_visible(self):
        self.create()
        observation = self.time.iso()
        self.time.advance(20)
        status = clock.observe_turn(self.path, 0, observed_utc=observation)
        self.assertEqual(status["elapsed_seconds"], 20)
        self.assertTrue(status["timing_uncertainty"])
        self.time.advance(30)
        verified = self.time.iso()
        self.time.advance(12)
        done = clock.verify_submission(self.path, 0, "e2e4", verified_utc=verified)
        self.assertEqual(done["game_seconds_used"], 50)
        self.assertTrue(any("entered later" in s for s in done["timing_uncertainty"]))

    def test_clock_discontinuity_cannot_erase_elapsed(self):
        self.create()
        clock.observe_turn(self.path, 0)
        self.time.advance(30)
        self.time.utc -= timedelta(seconds=20)
        status = clock.clock_status(self.path)
        self.assertEqual(status["elapsed_seconds"], 30)
        self.assertTrue(status["timing_uncertainty"])
        self.time.utc += timedelta(seconds=50)
        self.time.monotonic = 1  # Reboot: wall interval remains charged.
        self.assertEqual(clock.clock_status(self.path)["elapsed_seconds"], 60)

    def test_parallel_queries_and_restart_cannot_overwrite_ledger(self):
        self.create()
        clock.observe_turn(self.path, 0)
        with clock.query_clock(self.path, 5):
            with self.assertRaisesRegex(ValueError, "busy"):
                with clock.query_clock(self.path, 5):
                    self.fail("Concurrent query acquired lock")
            with self.assertRaisesRegex(ValueError, "busy"):
                clock.mark_critical(self.path, "new threat")
        before = self.path.read_bytes()
        with self.assertRaises(FileExistsError):
            self.create()
        self.assertEqual(self.path.read_bytes(), before)

    def test_bad_submission_does_not_end_active_turn(self):
        self.create()
        clock.observe_turn(self.path, 0)
        self.time.advance(5)
        clock.record_event(self.path, "submission", move="e2e4")
        with self.assertRaisesRegex(ValueError, "differs"):
            clock.verify_submission(self.path, 0, "d2d4")
        self.assertEqual(clock.clock_status(self.path)["active_ply"], 0)
        clock.record_event(self.path, "query_rejected", reason="Malformed option")
        self.assertEqual(self.events()[-1]["kind"], "query_rejected")

    def test_backdated_verification_cannot_remove_recorded_analysis(self):
        self.create()
        clock.observe_turn(self.path, 0)
        self.time.advance(10)
        backdated = self.time.iso()
        with clock.query_clock(self.path, 10):
            self.time.advance(10)
        with self.assertRaisesRegex(ValueError, "cannot precede recorded"):
            clock.verify_submission(self.path, 0, "e2e4", verified_utc=backdated)
        self.assertEqual(clock.clock_status(self.path)["elapsed_seconds"], 20)


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fake = FakeTime()
        for obj, name, value in ((journal, "ROOT", self.root), (journal, "now", self.fake.iso),
                                 (clock, "_sample", self.fake.sample)):
            p = patch.object(obj, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.game = self.root / "engine-games" / "trial"
        self.call("init", "--round", "9")

    def call(self, command, *args):
        with redirect_stdout(io.StringIO()):
            journal.main([command, "--game", "trial", *args])

    def test_observe_then_candidate_and_verify_are_distinct(self):
        self.call("turn")
        self.fake.advance(10)
        self.call("candidate", "--move", "e2e4")
        self.call("choose", "--move", "e2e4")
        self.fake.advance(10)
        self.call("submit")
        self.assertEqual(journal.load(self.game)["uci"], [])
        with self.assertRaisesRegex(ValueError, "Verify"):
            self.call("turn", "--opponent", "e5")
        self.call("reject", "--note", "Click did not move the piece")
        self.assertEqual(journal.load(self.game)["uci"], [])
        self.fake.advance(10)
        self.call("choose", "--move", "d2d4")
        self.call("submit")
        self.fake.advance(2)
        self.call("verify")
        self.assertEqual(journal.load(self.game)["uci"], ["d2d4"])
        self.fake.advance(20)
        self.call("turn", "--opponent", "d5", "--initial", "c2c4")
        data = journal.load(self.game)
        self.assertEqual(data["uci"], ["d2d4", "d7d5"])
        self.assertEqual(data["turns"][-1]["initial_candidate"], "c2c4")
        self.assertEqual(clock.clock_status(self.game / "clock.jsonl")["game_seconds_used"], 32)

    def test_invalid_candidate_or_opponent_does_not_mutate_journal(self):
        before = (self.game / "game.json").read_bytes()
        ledger = (self.game / "clock.jsonl").read_bytes()
        with self.assertRaises(ValueError):
            self.call("turn", "--initial", "e2e5")
        self.assertEqual((self.game / "game.json").read_bytes(), before)
        self.assertEqual((self.game / "clock.jsonl").read_bytes(), ledger)
        with self.assertRaisesRegex(ValueError, "does not expect"):
            self.call("turn", "--opponent", "e5")
        self.assertEqual((self.game / "game.json").read_bytes(), before)

    def test_query_propagates_settings_and_position_without_auto_search(self):
        with patch.object(journal, "run_query") as run:
            self.call("turn", "--initial", "e2e4")
            run.assert_not_called()
            self.call("query", "--goal", '{"type":"check","side":"white"}', "--seconds", "20", "--html")
            args = run.call_args.args[0]
            request = json.loads(args.request.read_text())
            self.assertTrue(request["proof_only"])
            self.assertTrue(request["diagnostics"])
            self.assertEqual(request["depth"], 8)
            self.assertEqual(args.game_clock, self.game / "clock.jsonl")
            self.assertIsNone(args.session)
            self.assertEqual(request["history_fens"], [])

    def test_finish_resignation_charges_turn_and_cannot_overwrite_game(self):
        self.call("turn", "--initial", "e2e4")
        self.fake.advance(95)
        self.call("finish", "--result", "0-1", "--termination", "resignation")
        data = journal.load(self.game)
        self.assertEqual(data["final_clock"]["game_seconds_used"], 95)
        self.assertIn('[Round "9"]', (self.game / "game.pgn").read_text())
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.call("init", "--round", "10")
        with self.assertRaisesRegex(ValueError, "finished"):
            self.call("turn")

    def test_explicit_directory_and_historical_guard(self):
        with self.assertRaises(ValueError):
            journal.game_directory("../old")
        old = self.root / "engine-games" / "old"
        old.mkdir()
        (old / "game.json").write_text('{"historical":true}')
        with self.assertRaisesRegex(ValueError, "historical games are preserved"):
            journal.main(["turn", "--game", "old"])
        self.assertEqual((old / "game.json").read_text(), '{"historical":true}')

    def test_invalid_initial_clock_does_not_leave_a_directory(self):
        with self.assertRaisesRegex(ValueError, "reserve"):
            journal.main(["init", "--game", "invalid", "--round", "9", "--reserve", "100"])
        self.assertFalse((self.root / "engine-games" / "invalid").exists())

    def test_finish_records_final_opponent_move_without_starting_an_own_turn(self):
        self.call("turn", "--initial", "e2e4")
        self.fake.advance(15)
        self.call("choose", "--move", "e2e4")
        self.call("verify")
        self.fake.advance(30)
        self.call("finish", "--opponent", "e5", "--result", "1/2-1/2", "--termination", "agreement")
        data = journal.load(self.game)
        self.assertEqual(data["uci"], ["e2e4", "e7e5"])
        self.assertEqual(data["final_clock"]["game_seconds_used"], 15)
        self.assertEqual(len(data["turns"]), 1)


if __name__ == "__main__":
    unittest.main()
