"""Black live-game support preserves move order, own-time boundaries and recovery."""
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
import resume_chess


class BlackJournalTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.game = self.root / "engine-games" / "black-trial"
        self.utc = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)
        self.elapsed = 0
        for obj, name, value in (
            (journal, "ROOT", self.root),
            (journal, "now", lambda: self.utc.isoformat()),
            (clock, "_sample", lambda: (self.utc, 10000.0 + self.elapsed)),
            (resume_chess, "engine_fingerprint", lambda root: "unchanged-engine"),
        ):
            patcher = patch.object(obj, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.call("init", "--round", "10", "--side", "black")

    def advance(self, seconds):
        self.utc += timedelta(seconds=seconds)
        self.elapsed += seconds

    def call(self, command, *args):
        with redirect_stdout(io.StringIO()):
            journal.main([command, "--game", "black-trial", *args])

    def state(self):
        return resume_chess.snapshot(self.game, self.root)

    def play_black(self, opponent, move):
        self.call("turn", "--opponent", opponent, "--initial", move)
        self.advance(10)
        self.call("choose", "--move", move)
        self.call("submit")
        self.advance(3)
        self.call("verify")

    def test_first_white_move_starts_black_clock_and_waiting_time_is_excluded(self):
        self.advance(120)
        state = self.state()
        self.assertEqual(state["phase"], "awaiting_opponent_observation")
        self.assertEqual(state["player_side"], "black")
        self.assertEqual(state["side_to_move"], "white")
        self.assertEqual(state["clock"]["game_seconds_used"], 0)
        before = {p.name: p.read_bytes() for p in self.game.iterdir()}
        with self.assertRaisesRegex(ValueError, "provide the observed opponent SAN"):
            self.call("turn")
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.game.iterdir()})
        self.play_black("e4", "e7e5")
        self.advance(60)
        state = self.state()
        self.assertEqual(state["phase"], "awaiting_opponent_observation")
        self.assertEqual(state["clock"]["game_seconds_used"], 10)
        self.assertEqual(state["verified_plies"], 2)
        self.call("turn", "--opponent", "Nf3")
        state = self.state()
        self.assertEqual(state["phase"], "own_turn_active")
        self.assertEqual(state["clock"]["active_ply"], 3)
        self.assertEqual(state["turn"]["move"], 2)
        self.assertEqual(state["issues"], [])

    def test_black_checkmate_pgn_has_correct_players_rating_and_move_numbers(self):
        self.play_black("f3", "e7e5")
        self.play_black("g4", "d8h4")
        self.call("finish", "--result", "0-1", "--termination", "checkmate")
        pgn = (self.game / "game.pgn").read_text(encoding="utf-8")
        self.assertIn('[White "Wally"]', pgn)
        self.assertIn('[WhiteElo "1800"]', pgn)
        self.assertIn('[Black "Astra (Ultra)"]', pgn)
        self.assertNotIn("BlackElo", pgn)
        self.assertIn("1. f3 e5 2. g4 Qh4# 0-1", pgn)
        self.assertEqual(self.state()["phase"], "finished")
        self.assertEqual(self.state()["clock"]["game_seconds_used"], 20)

    def test_final_white_checkmate_is_recorded_without_new_black_clock(self):
        self.play_black("e4", "e7e5")
        self.play_black("Bc4", "b8c6")
        self.play_black("Qh5", "g8f6")
        self.advance(90)
        self.call("finish", "--opponent", "Qxf7#", "--result", "1-0", "--termination", "checkmate")
        data = journal.load(self.game)
        self.assertEqual(data["san"][-1], "Qxf7#")
        self.assertEqual(len(data["uci"]), 7)
        self.assertEqual(len(data["turns"]), 3)
        self.assertEqual(data["final_clock"]["game_seconds_used"], 30)
        self.assertEqual(self.state()["phase"], "finished")

    def test_black_query_and_pending_recovery_use_black_position_and_identity(self):
        self.call("turn", "--opponent", "d4", "--initial", "d7d5")
        with patch.object(journal, "run_query") as run:
            self.call("query")
            request_path = run.call_args.args[0].request
            request = json.loads(request_path.read_text())
            self.assertIn("Wally game 10, move 1", request["label"])
            self.assertEqual(request["fen"].split()[1], "b")
            self.assertEqual(len(request["history_fens"]), 1)
            output = run.call_args.args[0].output
            output.write_text(json.dumps({"kind": "analysis", "start_fen": request["fen"],
                "engine": {"source_sha256": "unchanged-engine"}, "candidates": []}), encoding="utf-8")
        self.call("choose", "--move", "d7d5")
        before = {p.name: p.read_bytes() for p in self.game.iterdir()}
        state = self.state()
        self.assertEqual(state["phase"], "pending_unverified")
        self.assertEqual(state["pending"]["expected_fen_if_accepted"].split()[1], "w")
        self.assertEqual(state["latest_query"]["recorded_for_side"], "black")
        self.assertEqual(state["latest_query"]["recorded_on_move"], 1)
        self.assertNotIn("recorded_on_white_move", state["latest_query"])
        self.assertTrue(state["latest_query"]["starts_at_verified_position"])
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.game.iterdir()})

    def test_legacy_white_journal_without_side_remains_supported(self):
        with redirect_stdout(io.StringIO()):
            journal.main(["init", "--game", "legacy", "--round", "9"])
        legacy = self.root / "engine-games" / "legacy"
        data = journal.load(legacy)
        del data["player_side"]
        journal.save(legacy, data)
        with redirect_stdout(io.StringIO()):
            journal.main(["turn", "--game", "legacy", "--initial", "e2e4"])
        state = resume_chess.snapshot(legacy, self.root)
        self.assertEqual(state["player_side"], "white")
        self.assertEqual(state["phase"], "own_turn_active")
        self.assertEqual(state["issues"], [])
        self.assertEqual(journal.own_side(data), 0)

    def test_candidate_png_is_scoped_to_game_image_directory(self):
        self.call("turn", "--opponent", "e4", "--initial", "c7c5")
        with patch("board_scratchpad.render") as render:
            self.call("choose", "--move", "c7c5", "--png")
        self.assertEqual(render.call_args.args[1], self.game / "images/candidate.png")
        self.assertEqual(render.call_args.args[0]["board"]["c5"], "p")
        self.assertEqual(self.state()["phase"], "pending_unverified")


if __name__ == "__main__":
    unittest.main()
