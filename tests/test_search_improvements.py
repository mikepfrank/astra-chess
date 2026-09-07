"""Rules/search regressions for optional assistance and the faster baseline."""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import random
import sys
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from astra_engine.rules import Move, Position, START_FEN
from astra_engine.search import INF, _Search, analyze, probe


class SearchImprovementTests(unittest.TestCase):
    def assert_line(self, root, line):
        self.assertEqual(line["fens"][0], root.fen())
        for index, uci in enumerate(line["uci"]):
            move = root.parse_uci(uci)
            self.assertEqual(root.san(move), line["san"][index])
            root = root.play(move)
            self.assertEqual(root.fen(), line["fens"][index + 1])

    def test_tactical_generation_matches_full_legal_moves(self):
        fixtures = [START_FEN,
                    "7k/P7/8/8/8/8/8/7K w - - 0 1",
                    "1r5k/P7/8/8/8/8/8/7K w - - 0 1",
                    "7k/8/8/3pP3/8/8/8/7K w - d6 0 1",
                    "7k/8/8/r4pPK/8/8/8/8 w - f6 0 1",
                    "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"]
        fixtures += json.loads((ROOT / "engine-games/wally-2026-09-07/game.json").read_text())["fens"]
        rng = random.Random(881)
        board = Position.from_fen(START_FEN)
        for _ in range(100):
            fixtures.append(board.fen())
            legal = board.legal_moves()
            if not legal:
                break
            board = board.play(rng.choice(legal))
        for fen in fixtures:
            with self.subTest(fen=fen):
                board = Position.from_fen(fen)
                full = board.legal_children()
                expected = [move for move in full if move.promotion or board.board[move.to_sq] != "."
                            or (board.board[move.from_sq].lower() == "p"
                                and move.to_sq == board.ep_square)]
                tactical = board.legal_children(tactical_only=True)
                self.assertEqual(list(tactical), expected)
                self.assertEqual(board.has_legal_move(), bool(full))
                for move, child in full.items():
                    self.assertEqual(child, board.play(move))

    def test_has_legal_move_stops_after_first_legal_child(self):
        board = Position.from_fen(START_FEN)
        original = Position.play
        calls = []
        def counted(position, move):
            calls.append(move)
            return original(position, move)
        with patch.object(Position, "play", counted):
            self.assertTrue(board.has_legal_move())
        self.assertEqual(len(calls), 1)

    def test_quiescence_keeps_quiet_check_evasions_and_stalemate(self):
        board = Position.from_fen("7k/8/8/8/8/8/8/K6R b - - 0 1")
        self.assertTrue(board.in_check())
        self.assertEqual(board.legal_children(tactical_only=True), {})
        worker = _Search(time.monotonic() + 2, Counter({board.repetition_key(): 1}))
        answer = worker.quiescence(board, -INF, INF, 0, 8)
        self.assertTrue(answer.pv)
        self.assertIn(answer.pv[0], board.legal_moves())
        self.assertFalse(board.play(answer.pv[0]).in_check(1))
        stale = Position.from_fen("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")
        self.assertFalse(stale.has_legal_move())
        worker = _Search(time.monotonic() + 2, Counter({stale.repetition_key(): 1}))
        answer = worker.quiescence(stale, -INF, INF, 0, 8)
        self.assertEqual((answer.score, answer.ending), (0, "stalemate"))

    def test_disabled_options_preserve_score_lines_and_nodes(self):
        board = Position.from_fen("4k3/8/3q4/8/3R4/8/8/4K3 w - - 0 1")
        ordinary = analyze(board, max_depth=2, time_limit=2)
        explicit = analyze(board, max_depth=2, time_limit=2, threat_extensions=0,
                           evaluation={"mobility": False, "restricted_piece": False, "king_exposure": False})
        self.assertEqual(ordinary["candidates"], explicit["candidates"])
        self.assertEqual(ordinary["nodes"], explicit["nodes"])
        self.assertEqual(ordinary["completed_depth"], 2)

    def test_optional_extensions_reveal_bishop_capture_and_disclose_cap(self):
        board = Position.from_fen("1r1r2k1/5pb1/4qnp1/1pp1p2p/4P3/1P1B1Q1P/2P1NPP1/R2R2K1 b - - 1 21")
        ordinary = analyze(board, max_depth=1, time_limit=2, root_moves=["c5c4"])
        one = analyze(board, max_depth=1, time_limit=2, root_moves=["c5c4"], threat_extensions=1)
        two = analyze(board, max_depth=1, time_limit=2, root_moves=["c5c4"], threat_extensions=2)
        self.assertEqual(two["completed_depth"], 1)
        self.assertGreater(two["root_score_cp"], ordinary["root_score_cp"] + 100)
        self.assertTrue(one["diagnostics"]["threat_frontier_unresolved"])
        self.assertGreater(one["diagnostics"]["capped_threat_frontiers"], 0)
        for result in (ordinary, one, two):
            for line in result["candidates"]:
                self.assert_line(board, line)
        # The discovered continuation captures the original bishop, with all
        # quiet defenses included at the extended frontiers.
        self.assertIn("c4d3", two["candidates"][0]["uci"])

    def test_optional_terms_and_limit_validation(self):
        board = Position.from_fen(START_FEN)
        for bad in ({"evaluation": {"mobility": 1}}, {"evaluation": {"mobillity": True}},
                    {"threat_extensions": True}, {"threat_extensions": 3},
                    {"max_depth": 33}, {"time_limit": 181}):
            with self.subTest(options=bad), self.assertRaises(ValueError):
                analyze(board, **bad)
        for name in ("mobility", "restricted_piece", "king_exposure"):
            result = analyze(board, max_depth=1, time_limit=2, evaluation={name: True})
            self.assertTrue(result["settings"]["evaluation"][name])
            for line in result["candidates"]:
                self.assert_line(board, line)

    def test_proof_only_never_launches_cooperative_search(self):
        from astra_engine.search import _Probe
        board = Position.from_fen("7k/8/8/8/8/q7/8/R6K b - - 0 1")
        goal = {"type": "capture", "side": "white", "target": "a3"}
        with patch.object(_Probe, "witnesses", side_effect=AssertionError("Cooperative search must be skipped")):
            result = probe(board, goal, max_depth=2, time_limit=1, proof_only=True)
        self.assertEqual(result["proof_status"], "refuted")
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["witness_status"], "not_searched")
        self.assertEqual(result["diagnostics"]["witness_nodes"], 0)
        self.assertEqual(result["lines"], [])

    def test_proof_only_avoidance_checks_full_horizon_and_keeps_proof_line(self):
        board = Position.from_fen("r6k/8/8/8/8/8/8/4K3 w - - 0 1")
        short = probe(board, {"type": "avoid_check"}, max_depth=1, time_limit=1, proof_only=True)
        longer = probe(board, {"type": "avoid_check"}, max_depth=2, time_limit=1, proof_only=True)
        self.assertEqual(short["proof_status"], "forced")
        self.assertEqual(longer["proof_status"], "refuted")
        self.assertEqual(longer["proof_completed_depth"], 2)
        self.assertEqual(short["lines"][0]["evidence"], "proof_representative")
        self.assert_line(board, short["lines"][0])

    def test_proof_only_timeout_is_unknown(self):
        board = Position.from_fen(START_FEN)
        result = probe(board, {"type": "checkmate"}, max_depth=32,
                       time_limit=0.005, proof_only=True)
        self.assertTrue(result["timed_out"])
        self.assertEqual(result["proof_status"], "unknown")
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["diagnostics"]["witness_nodes"], 0)
        with self.assertRaises(ValueError):
            probe(board, {"type": "check"}, proof_only="yes")


if __name__ == "__main__":
    unittest.main()
