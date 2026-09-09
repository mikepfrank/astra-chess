"""Draw archives preserve actual results, evidence, and claim boundaries."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import re
import tempfile
import unittest

from build_replay import build, normalized_fen, validated_ending
from export_evaluations import extract
import chess
import chess.pgn


ROOT = Path(__file__).resolve().parents[1]


def replay_data(text):
    return json.loads(re.search(r'<script id="replay-data" type="application/json">(.*?)</script>',
                               text, re.S).group(1))


def repeated_position(plies):
    board = chess.Board()
    cycle = ("g1f3", "g8f6", "f3g1", "f6g8")
    for index in range(plies):
        board.push_uci(cycle[index % len(cycle)])
    return board


class ReplayDrawTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pgn = ROOT / "engine-games/li-v02-classical/game.pgn"
        cls.journal = json.loads(cls.pgn.with_suffix(".json").read_text(encoding="utf-8"))
        cls.scores = extract("li-v02-classical")
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            output = Path(directory) / "replay.html"
            scores = Path(directory) / "scores.json"
            scores.write_text(json.dumps(cls.scores), encoding="utf-8")
            build(cls.pgn, output, "Draw trial", evaluations=scores)
            cls.html = output.read_text(encoding="utf-8")
            cls.data = replay_data(cls.html)

    def build_fixture(self, board, result="1/2-1/2", *, termination="normal", ending=None):
        game = chess.pgn.Game.from_board(board)
        game.headers.update(Date="2026.09.09", Round="999", White="White", Black="Black",
                            Result=result, Termination=termination)
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            pgn = Path(directory) / "fixture.pgn"
            output = Path(directory) / "replay.html"
            pgn.write_text(str(game), encoding="utf-8")
            build(pgn, output, ending=ending)
            return replay_data(output.read_text(encoding="utf-8"))

    def test_li_draw_has_all_actual_positions_and_no_winner(self):
        frames = self.data["frames"]
        self.assertEqual(len(frames), 140)
        self.assertEqual([f["move"]["uci"] for f in frames[1:]], self.journal["uci"])
        self.assertEqual([f["move"]["san"] for f in frames[1:]], self.journal["san"])
        self.assertEqual([f["fen"] for f in frames],
                         [normalized_fen(fen) for fen in self.journal["fens"]])
        self.assertEqual(self.data["headers"]["Result"], "1/2-1/2")
        self.assertEqual(self.data["outcome"], {
            "winner": None, "reason": "insufficient material", "label": "Insufficient material",
            "description": "Draw by insufficient material", "detail": "Draw · Insufficient material"})
        self.assertFalse(frames[-1]["mate"])
        self.assertEqual(frames[-1]["move"]["san"], "Kxe6")
        self.assertEqual(len(frames[-1]["pieces"]), 2)

    def test_draw_keeps_final_historical_score_and_provenance(self):
        row = self.scores["rows"][-1]
        record = self.data["frames"][-1]["evaluation"]
        self.assertEqual(record["kind"], "search_estimate")
        self.assertEqual(record["scoreCp"], row["score_cp"])
        self.assertEqual(record["source"], row["source"])
        self.assertEqual(record["depth"], row["completed_depth"])
        self.assertEqual(record["forMove"], "70. Kxe6")
        self.assertIn("before this move", record["note"])
        self.assertIsNone(self.data["outcome"]["winner"])

    def test_automatic_draw_types_require_matching_result_and_ending(self):
        examples = [
            (chess.Board("8/8/4K3/7k/8/8/8/8 b - - 0 70"), "insufficient material"),
            (chess.Board("7k/5K2/6Q1/8/8/8/8/8 b - - 0 1"), "stalemate"),
            (repeated_position(16), "fivefold repetition"),
            (chess.Board("7k/8/8/8/8/8/8/KR6 w - - 150 90"), "seventy-five-move rule"),
        ]
        for board, reason in examples:
            with self.subTest(reason=reason):
                self.assertEqual(validated_ending(board, "1/2-1/2"), reason)
                self.assertEqual(validated_ending(board, "1/2-1/2", reason), reason)
                for result, ending in [("1-0", None), ("0-1", "resignation"),
                                       ("1/2-1/2", "agreement"), ("1/2-1/2", "checkmate")]:
                    with self.assertRaisesRegex(ValueError, "disagrees"):
                        validated_ending(board, result, ending)

    def test_threefold_and_fifty_move_claims_are_explicit_and_already_available(self):
        cases = [(repeated_position(8), "threefold repetition"),
                 (chess.Board("7k/8/8/8/8/8/8/KR6 w - - 100 90"), "fifty-move rule")]
        for board, reason in cases:
            with self.subTest(reason=reason):
                self.assertIsNone(board.outcome(claim_draw=False))
                self.assertEqual(validated_ending(board, "1/2-1/2", reason), reason)
                with self.assertRaisesRegex(ValueError, "explicit"):
                    validated_ending(board, "1/2-1/2")

    def test_an_unplayed_intended_move_does_not_satisfy_a_draw_claim(self):
        repetition = repeated_position(7)
        fifty = chess.Board("7k/8/8/8/8/8/8/KR6 w - - 99 90")
        self.assertTrue(repetition.can_claim_threefold_repetition())
        self.assertFalse(repetition.is_repetition(3))
        self.assertTrue(fifty.can_claim_fifty_moves())
        self.assertFalse(fifty.is_fifty_moves())
        for board, reason in [(repetition, "threefold repetition"), (fifty, "fifty-move rule")]:
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, "does not establish"):
                validated_ending(board, "1/2-1/2", reason)

    def test_nonterminal_agreed_draw_requires_explicit_intent(self):
        board = chess.Board()
        self.assertEqual(validated_ending(board, "1/2-1/2", "agreement"), "agreement")
        for ending in (None, "resignation", "stalemate", "insufficient material"):
            with self.subTest(ending=ending), self.assertRaisesRegex(ValueError, "explicit"):
                validated_ending(board, "1/2-1/2", ending)
        data = self.build_fixture(board, ending="agreement")
        self.assertEqual(data["outcome"]["description"], "Draw by agreement")
        self.assertIsNone(data["outcome"]["winner"])

    def test_pgn_termination_cannot_contradict_a_detected_draw(self):
        board = chess.Board("8/8/4K3/7k/8/8/8/8 b - - 0 70")
        with self.assertRaisesRegex(ValueError, "Termination header"):
            self.build_fixture(board, termination="checkmate")

    def test_automatic_draw_pgn_cannot_continue_after_game_end(self):
        board = repeated_position(17)
        with self.assertRaisesRegex(ValueError, "continues after"):
            self.build_fixture(board)

    def test_terminal_setup_without_moves_builds_without_fabricating_a_move(self):
        board = chess.Board("8/8/4K3/7k/8/8/8/8 b - - 0 70")
        data = self.build_fixture(board, termination="insufficient material")
        self.assertEqual(len(data["frames"]), 1)
        self.assertIsNone(data["frames"][0]["move"])
        self.assertIsNone(data["outcome"]["winner"])

    def test_decisive_checkmate_and_resignation_behaviors_are_preserved(self):
        board = chess.Board()
        for move in ("f2f3", "e7e5", "g2g4", "d8h4"):
            board.push_uci(move)
        self.assertEqual(validated_ending(board, "0-1"), "checkmate")
        data = self.build_fixture(board, "0-1", termination="checkmate")
        self.assertEqual(data["outcome"]["winner"], "black")
        self.assertEqual(data["outcome"]["detail"], "Checkmate · Black wins")
        for result in ("1-0", "1/2-1/2"):
            with self.assertRaisesRegex(ValueError, "disagrees"):
                validated_ending(board, result)
        board = chess.Board()
        self.assertEqual(validated_ending(board, "1-0", "resignation"), "resignation")
        with self.assertRaisesRegex(ValueError, "explicit"):
            validated_ending(board, "1-0")

    def test_unfinished_or_unknown_results_are_rejected(self):
        for result in ("*", "draw", "?"):
            with self.subTest(result=result), self.assertRaisesRegex(ValueError, "completed"):
                validated_ending(chess.Board(), result, "agreement")


if __name__ == "__main__":
    unittest.main()
