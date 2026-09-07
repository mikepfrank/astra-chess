"""Recovery preserves pending actions and time; never advances a game."""
from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from astra_engine import clock
import play_engine_game as journal
import resume_chess


class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.directory = self.root / "engine-games" / "recovery"
        self.patch = patch.object(journal, "ROOT", self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.hash_patch = patch.object(resume_chess, "engine_fingerprint", return_value="test-hash")
        self.hash_patch.start()
        self.addCleanup(self.hash_patch.stop)
        self.call("init", "--round", "1")

    def call(self, command, *args):
        with redirect_stdout(io.StringIO()):
            journal.main([command, "--game", "recovery", *args])

    def snapshot(self):
        return resume_chess.snapshot(self.directory, self.root)

    def test_pending_move_survives_read_without_advancing_or_resetting(self):
        self.call("turn", "--initial", "e2e4")
        self.call("choose", "--move", "e2e4")
        originals = {p.name: p.read_bytes() for p in self.directory.iterdir() if p.is_file()}
        used_before = clock.clock_status(self.directory / "clock.jsonl")["game_seconds_used"]
        status = self.snapshot()
        self.assertEqual(status["phase"], "pending_unverified")
        self.assertEqual(status["verified_plies"], 0)
        self.assertEqual(status["pending"]["uci"], "e2e4")
        self.assertEqual(status["pending"]["expected_fen_if_accepted"].split()[1], "b")
        self.assertGreaterEqual(status["clock"]["game_seconds_used"], used_before)
        self.assertEqual(originals, {p.name: p.read_bytes() for p in self.directory.iterdir() if p.is_file()})

    def test_verified_move_is_not_resubmitted_on_recovery(self):
        self.call("turn", "--initial", "e2e4")
        self.call("choose", "--move", "e2e4")
        self.call("verify")
        state = self.snapshot()
        self.assertEqual(state["phase"], "awaiting_opponent_observation")
        self.assertEqual(state["last_verified_move"], "e4")
        self.assertIsNone(state["pending"])
        self.assertIsNone(state["clock"]["active_ply"])

    def test_inconsistent_clock_fails_closed_and_finished_game_stays_finished(self):
        self.call("turn")
        game = journal.load(self.directory)
        game["turns"] = []
        journal.save(self.directory, game)
        self.assertEqual(self.snapshot()["phase"], "needs_record_reconciliation")
        self.call("finish", "--result", "0-1", "--termination", "resignation")
        self.assertEqual(self.snapshot()["phase"], "finished")

    def test_lists_games_without_selecting_and_rejects_history_mismatch(self):
        self.assertEqual(resume_chess.list_games(self.root)["games"][0]["game"], "recovery")
        game = journal.load(self.directory)
        game["uci"] = ["e2e4"]
        journal.save(self.directory, game)
        with self.assertRaisesRegex(ValueError, "lengths disagree"):
            self.snapshot()

    def test_latest_query_remains_available_when_new_turn_has_no_search(self):
        self.call("turn", "--initial", "e2e4")
        game = journal.load(self.directory)
        query = self.directory / "old-query.json"
        query.write_text('{"kind":"analysis","start_fen":"old position","engine":{"source_sha256":"test-hash"},"candidates":[]}', encoding="utf-8")
        game["turns"][-1]["queries"] = [str(query.relative_to(self.root))]
        journal.save(self.directory, game)
        self.call("choose", "--move", "e2e4")
        self.call("verify")
        self.call("turn", "--opponent", "e5")
        state = self.snapshot()
        self.assertEqual(state["latest_query"]["recorded_on_white_move"], 1)
        self.assertFalse(state["latest_query"]["starts_at_verified_position"])
        self.assertTrue(state["latest_query_engine_matches_current"])

    def test_legacy_journal_does_not_invent_a_clock_or_restart_finished_game(self):
        self.call("finish", "--result", "0-1", "--termination", "resignation")
        (self.directory / "clock.jsonl").unlink()
        status = self.snapshot()
        self.assertEqual(status["phase"], "finished")
        self.assertFalse(status["clock_available"])
        self.assertIsNone(status["clock"]["game_remaining_seconds"])
        self.assertIn("+00:00", status["as_of_utc"])
        game = journal.load(self.directory)
        game["result"] = "*"
        journal.save(self.directory, game)
        self.assertEqual(self.snapshot()["phase"], "needs_record_reconciliation")


if __name__ == "__main__":
    unittest.main()
