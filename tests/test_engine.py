"""Independent checks for the from-scratch engine.

Run from the workspace: python -m unittest discover -s tests -v
The existing replay copy of python-chess is an optional rules-only test oracle.
It is never imported by the engine and no engine, book, or tablebase is used.
"""

from __future__ import annotations

import random
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from astra_engine.rules import BLACK, WHITE, START_FEN, Move, Position

try:
    sys.path.insert(0, str(ROOT / ".replay-deps"))
    import chess
    import chess.pgn
except ImportError:
    chess = None


def position(fen: str = START_FEN) -> Position:
    return Position.from_fen(fen)


def moves(pos: Position) -> set[str]:
    return {move.uci() for move in pos.legal_moves()}


def play(pos: Position, *sequence: str) -> Position:
    for uci in sequence:
        pos = pos.play(pos.parse_uci(uci))
    return pos


def perft(pos: Position, depth: int) -> int:
    if depth == 0:
        return 1
    return sum(perft(pos.play(move), depth - 1) for move in pos.legal_moves())


class RulesTests(unittest.TestCase):
    def test_start_perft(self):
        pos = position()
        for depth, expected in [(1, 20), (2, 400), (3, 8902)]:
            with self.subTest(depth=depth):
                self.assertEqual(perft(pos, depth), expected)

    def test_fen_roundtrip_and_immutable_play(self):
        pos = position()
        self.assertEqual(pos.fen(), START_FEN)
        after = play(pos, "e2e4")
        self.assertEqual(pos.fen(), START_FEN)
        self.assertEqual(after.fen(), "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1")
        self.assertEqual(Position.from_fen(after.fen()).fen(), after.fen())
        self.assertEqual(Move(12, 28).uci(), "e2e4")
        self.assertEqual(Move(48, 56, "n").uci(), "a7a8n")

    def test_castling_transit_and_irrelevant_b_file_attack(self):
        fixtures = [
            ("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1", True, True),
            ("4kr2/8/8/8/8/8/8/R3K2R w KQ - 0 1", False, True),
            ("4k1r1/8/8/8/8/8/8/R3K2R w KQ - 0 1", False, True),
            ("1r2k3/8/8/8/8/8/8/R3K2R w KQ - 0 1", True, True),
            ("1k2r3/8/8/8/8/8/8/R3K2R w KQ - 0 1", False, False),
        ]
        for fen, kingside, queenside in fixtures:
            with self.subTest(fen=fen):
                legal = moves(position(fen))
                self.assertEqual("e1g1" in legal, kingside)
                self.assertEqual("e1c1" in legal, queenside)

    def test_castling_updates_both_pieces_and_rights(self):
        pos = position("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
        self.assertEqual(pos.san(pos.parse_uci("e1g1")), "O-O")
        self.assertEqual(play(pos, "e1g1").fen(), "r3k2r/8/8/8/8/8/8/R4RK1 b kq - 1 1")
        self.assertEqual(play(pos, "a1a2", "a8a7", "a2a1", "a7a8").fen().split()[2], "Kk")
        capture = position("r3k2r/1B6/8/8/8/8/8/R3K2R w KQkq - 0 1")
        self.assertEqual(play(capture, "b7a8").fen().split()[2], "KQk")

    def test_en_passant_pins_and_capture(self):
        vertical = position("4r2k/8/8/3pP3/8/8/8/4K3 w - d6 0 1")
        horizontal = position("7k/8/8/r4pPK/8/8/8/8 w - f6 0 1")
        self.assertNotIn("e5d6", moves(vertical))
        self.assertNotIn("g5f6", moves(horizontal))
        legal = position("7k/8/8/3pP3/8/8/8/7K w - d6 0 1")
        self.assertEqual(legal.san(legal.parse_uci("e5d6")), "exd6")
        self.assertEqual(play(legal, "e5d6").fen(), "7k/8/3P4/8/8/8/8/7K b - - 0 1")

    def test_promotions_include_all_underpromotions(self):
        pos = position("7k/P7/8/8/8/8/8/7K w - - 0 1")
        self.assertEqual({uci for uci in moves(pos) if uci.startswith("a7a8")},
                         {"a7a8q", "a7a8r", "a7a8b", "a7a8n"})
        self.assertEqual(pos.san(pos.parse_uci("a7a8n")), "a8=N")
        self.assertTrue(play(pos, "a7a8n").fen().startswith("N6k/"))

    def test_san_disambiguation(self):
        knights = position("4k3/8/8/8/8/8/8/1N2KN2 w - - 0 1")
        self.assertEqual(knights.san(knights.parse_uci("b1d2")), "Nbd2")
        self.assertEqual(knights.san(knights.parse_uci("f1d2")), "Nfd2")
        rooks = position("7k/8/8/8/8/R7/8/R6K w - - 0 1")
        self.assertEqual(rooks.san(rooks.parse_uci("a1a2")), "R1a2")
        self.assertEqual(rooks.san(rooks.parse_uci("a3a2")), "R3a2")

    def test_checkmate_and_stalemate_distinct(self):
        mate = position("7k/6Q1/5K2/8/8/8/8/8 b - - 0 1")
        stale = position("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")
        self.assertEqual(moves(mate), set())
        self.assertEqual(moves(stale), set())
        self.assertTrue(mate.in_check())
        self.assertFalse(stale.in_check())

    def test_insufficient_material_conservative(self):
        for fen in ["7k/8/8/8/8/8/8/K7 w - - 0 1",
                    "7k/8/8/8/8/8/8/KB6 w - - 0 1",
                    "7k/8/8/8/8/8/8/KN6 w - - 0 1"]:
            with self.subTest(fen=fen):
                self.assertTrue(position(fen).insufficient_material())
        # Two knights cannot force mate, but a legal mating position is possible.
        self.assertFalse(position("7k/8/8/8/8/8/8/KNN5 w - - 0 1").insufficient_material())
        self.assertFalse(position("7k/8/8/8/8/8/P7/K7 w - - 0 1").insufficient_material())

    def test_repetition_key_ignores_counters_and_unusable_ep(self):
        pos = position()
        loop = play(pos, "g1f3", "g8f6", "f3g1", "f6g8")
        self.assertEqual(pos.repetition_key(), loop.repetition_key())
        ep = play(pos, "e2e4")
        no_ep = position(ep.fen().replace(" e3 ", " - "))
        self.assertEqual(ep.repetition_key(), no_ep.repetition_key())
        pinned = position("4r2k/8/8/3pP3/8/8/8/4K3 w - d6 0 1")
        self.assertEqual(pinned.repetition_key(), position(pinned.fen().replace(" d6 ", " - ")).repetition_key())
        active = position("7k/8/8/3pP3/8/8/8/7K w - d6 0 1")
        self.assertNotEqual(active.repetition_key(), position(active.fen().replace(" d6 ", " - ")).repetition_key())

    def test_invalid_fen_and_illegal_uci_rejected(self):
        bad_fens = ["", "8/8/8/8/8/8/8 w - - 0 1",
                    "9/8/8/8/8/8/8/K6k w - - 0 1",
                    "7z/8/8/8/8/8/8/K6k w - - 0 1",
                    "7k/8/8/8/8/8/8/K7 x - - 0 1",
                    "7k/8/8/8/8/8/8/K7 w X - 0 1",
                    "7k/8/8/8/8/8/8/K7 w - z9 0 1",
                    "7k/8/8/8/8/8/8/K7 w - - -1 1",
                    "7k/8/8/8/8/8/8/K7 w - - 0 0"]
        for fen in bad_fens:
            with self.subTest(fen=fen), self.assertRaises(ValueError):
                position(fen)
        for uci in ["e2e5", "e1e8", "a7a8q", "wat", "e2e4q"]:
            with self.subTest(uci=uci), self.assertRaises(ValueError):
                position().parse_uci(uci)


@unittest.skipIf(chess is None, "Optional local python-chess rules oracle unavailable")
class OracleRulesTests(unittest.TestCase):
    def compare_position(self, ours, reference, played=None):
        self.assertEqual(ours.fen(), reference.fen(en_passant="fen"))
        ours_legal = {move.uci(): move for move in ours.legal_moves()}
        theirs = {move.uci(): move for move in reference.legal_moves}
        self.assertEqual(set(ours_legal), set(theirs), f"Legal moves differ at {ours.fen()}")
        self.assertEqual(ours.in_check(), reference.is_check())
        choices = sorted(theirs)
        samples = choices[:1] + choices[-1:]
        if played is not None:
            samples.append(played.uci())
        for uci in set(samples):
            self.assertEqual(ours.san(ours_legal[uci]), reference.san(theirs[uci]),
                             f"SAN differs for {uci} at {ours.fen()}")

    def test_all_archived_game_positions(self):
        archives = sorted((ROOT / "early-games").glob("*/*.pgn"))
        self.assertGreaterEqual(len(archives), 6)
        for path in archives:
            with self.subTest(archive=path.name), path.open(encoding="utf-8-sig") as stream:
                game = chess.pgn.read_game(stream)
                self.assertIsNotNone(game)
                self.assertEqual(game.errors, [])
                reference = game.board()
                ours = position(reference.fen(en_passant="fen"))
                for ply, move in enumerate(game.mainline_moves(), 1):
                    with self.subTest(ply=ply):
                        self.compare_position(ours, reference, move)
                        ours = ours.play(ours.parse_uci(move.uci()))
                        reference.push(move)
                self.compare_position(ours, reference)

    def test_seeded_random_playouts_and_attack_maps(self):
        for seed in [1729, 2718, 3141, 4706]:
            rng = random.Random(seed)
            reference = chess.Board()
            ours = position()
            for ply in range(100):
                with self.subTest(seed=seed, ply=ply):
                    self.compare_position(ours, reference)
                    if ply % 10 == 0:
                        for sq in range(64):
                            self.assertEqual(ours.is_attacked(sq, WHITE), reference.is_attacked_by(chess.WHITE, sq))
                            self.assertEqual(ours.is_attacked(sq, BLACK), reference.is_attacked_by(chess.BLACK, sq))
                    legal = list(reference.legal_moves)
                    if not legal:
                        break
                    move = rng.choice(legal)
                    ours = ours.play(ours.parse_uci(move.uci()))
                    reference.push(move)

    def test_special_position_perft_against_rules_oracle(self):
        def oracle_perft(board, depth):
            if depth == 0:
                return 1
            count = 0
            for move in list(board.legal_moves):
                board.push(move)
                count += oracle_perft(board, depth - 1)
                board.pop()
            return count

        for fen in ["r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1",
                    "7k/8/8/r4pPK/8/8/8/8 w - f6 0 1",
                    "7k/P7/8/8/8/8/8/7K w - - 0 1"]:
            with self.subTest(fen=fen):
                self.assertEqual(perft(position(fen), 2), oracle_perft(chess.Board(fen), 2))


class SearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global analyze, probe
        from astra_engine.search import analyze, probe

    def assert_line_consistent(self, initial, line):
        self.assertEqual(line["fens"][0], initial.fen())
        self.assertEqual(len(line["fens"]), len(line["uci"]) + 1)
        self.assertEqual(len(line["san"]), len(line["uci"]))
        pos = initial
        for index, uci in enumerate(line["uci"]):
            move = pos.parse_uci(uci)
            self.assertEqual(line["san"][index], pos.san(move))
            pos = pos.play(move)
            self.assertEqual(line["fens"][index + 1], pos.fen())

    def test_score_sign_is_root_side(self):
        white = analyze(position("7k/8/8/8/8/8/8/3Q3K w - - 0 1"), max_depth=1, time_limit=1)
        black = analyze(position("7k/8/8/8/8/8/8/3Q3K b - - 0 1"), max_depth=1, time_limit=1)
        self.assertGreater(white["candidates"][0]["score_cp"], 500)
        self.assertLess(black["candidates"][0]["score_cp"], -500)

    def test_mate_in_one_and_candidate_replay(self):
        pos = position("7k/8/5KQ1/8/8/8/8/8 w - - 0 1")
        result = analyze(pos, max_depth=2, time_limit=2, multipv=3)
        self.assertEqual(result["candidates"][0]["mate_in_plies"], 1)
        for line in result["candidates"]:
            self.assert_line_consistent(pos, line)

    def test_root_move_restriction(self):
        pos = position()
        result = analyze(pos, max_depth=2, time_limit=2, multipv=5, root_moves=["a2a3", "h2h3"])
        self.assertEqual({line["uci"][0] for line in result["candidates"]}, {"a2a3", "h2h3"})
        for line in result["candidates"]:
            self.assert_line_consistent(pos, line)
        for invalid in [[], ["e2e5"]]:
            with self.subTest(root_moves=invalid), self.assertRaises(ValueError):
                analyze(pos, max_depth=1, time_limit=0.1, root_moves=invalid)

    def test_top_candidates_match_independent_full_root_searches(self):
        pos = position("4k3/8/3q4/8/3R4/8/8/4K3 w - - 0 1")
        combined = analyze(pos, max_depth=2, time_limit=3, multipv=3)
        self.assertEqual(combined["completed_depth"], 2)
        independent = {}
        for move in pos.legal_moves():
            single = analyze(pos, max_depth=2, time_limit=2, multipv=1, root_moves=[move])
            self.assertEqual(single["completed_depth"], 2, move.uci())
            independent[move.uci()] = single["candidates"][0]["score_cp"]
        expected_scores = sorted(independent.values(), reverse=True)[:3]
        self.assertEqual([line["score_cp"] for line in combined["candidates"]], expected_scores)
        for line in combined["candidates"]:
            self.assertEqual(line["score_cp"], independent[line["uci"][0]])

    def test_depth_and_time_limits_return_legal_fallback(self):
        started = time.monotonic()
        result = analyze(position(), max_depth=12, time_limit=0.02, multipv=3)
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 1.0)
        self.assertLessEqual(result["completed_depth"], 12)
        self.assertTrue(result["timed_out"])
        self.assertTrue(result["candidates"])
        for line in result["candidates"]:
            self.assert_line_consistent(position(), line)
        full = analyze(position(), max_depth=1, time_limit=2, multipv=2)
        self.assertEqual(full["completed_depth"], 1)

    def test_terminal_draws_and_mate_precedence(self):
        fixtures = [
            ("7k/6Q1/5K2/8/8/8/8/8 b - - 150 1", "checkmate", "1-0"),
            ("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1", "stalemate", "1/2-1/2"),
            ("7k/8/8/8/8/8/8/7K w - - 0 1", "insufficient_material", "1/2-1/2"),
            ("7k/8/8/8/8/8/8/R6K w - - 150 1", "seventy_five_moves", "1/2-1/2"),
        ]
        for fen, reason, outcome in fixtures:
            with self.subTest(fen=fen):
                result = analyze(position(fen), max_depth=1, time_limit=1)
                self.assertEqual(result["terminal"]["reason"], reason)
                self.assertEqual(result["terminal"]["result"], outcome)
                self.assertEqual(result["recommended_action"], "game_over")
                self.assertEqual(result["candidates"], [])

    def test_draw_claims_and_repetition_history(self):
        losing = position("7k/8/8/8/8/8/8/3Q3K b - - 100 1")
        result = analyze(losing, max_depth=1, time_limit=1)
        self.assertTrue(result["draw_claim_available"])
        self.assertIn("fifty_moves", result["draw_claim_reasons"])
        self.assertEqual(result["recommended_action"], "claim_draw")
        self.assertEqual(result["root_score_cp"], 0)
        pos = position()
        key = pos.repetition_key()
        three = analyze(pos, max_depth=1, time_limit=1, history=[key, key])
        self.assertTrue(three["draw_claim_available"])
        self.assertIn("threefold_repetition", three["draw_claim_reasons"])
        five = analyze(pos, max_depth=1, time_limit=1, history=[key] * 4)
        self.assertEqual(five["terminal"]["reason"], "fivefold_repetition")

    def test_prospective_fifty_move_claim_at_root_and_quiet_frontier(self):
        losing = position("7k/8/8/8/8/8/8/3Q3K b - - 99 1")
        claim = analyze(losing, max_depth=1, time_limit=1)
        self.assertEqual(claim["root_score_cp"], 0)
        self.assertEqual(claim["candidates"][0]["ending"], "intended_move_draw_claim")
        self.assertEqual(claim["recommended_action"], "claim_draw")
        self.assertTrue(claim["draw_claim_available"])
        self.assertFalse(claim["current_draw_claim_available"])
        self.assertIn(claim["intended_move"], moves(losing))
        for line in claim["candidates"]:
            self.assertEqual(line["uci"], [])
            self.assertEqual(line["fens"], [losing.fen()])
            self.assertIn(line["claim_by_intended_move"], moves(losing))
        # At depth one Black's quiet next move lies in quiescence, but the
        # declaration option still prevents a spurious White material advantage.
        before = position("7k/8/8/8/8/8/8/3Q3K w - - 98 1")
        frontier = analyze(before, max_depth=1, time_limit=1, root_moves=["d1d2"])
        self.assertEqual(frontier["root_score_cp"], 0)
        self.assertEqual(frontier["candidates"][0]["uci"], ["d1d2"])
        self.assert_line_consistent(before, frontier["candidates"][0])
        self.assertIn(frontier["candidates"][0]["claim_by_intended_move"], moves(play(before, "d1d2")))

    def test_prospective_repetition_uses_actual_prior_positions(self):
        pos = position()
        history = []
        for uci in ["g1f3", "g8f6", "f3g1", "f6g8", "g1f3", "g8f6", "f3g1"]:
            history.append(pos.repetition_key())
            pos = play(pos, uci)
        result = analyze(pos, max_depth=1, time_limit=1, history=history)
        self.assertFalse(result["current_draw_claim_available"])
        self.assertIn("f6g8", result["draw_claim_by_intended_moves"])
        unknown_history = analyze(pos, max_depth=1, time_limit=1)
        self.assertFalse(unknown_history["draw_claim_available"])

    def test_goal_witness_is_not_claimed_as_forced_and_tracks_target(self):
        pos = position("7k/8/8/8/8/q7/8/R6K b - - 0 1")
        result = probe(pos, {"type": "capture", "side": "white", "target": "a3"},
                       max_depth=2, time_limit=3, max_lines=2)
        self.assertEqual(result["status"], "possible")
        self.assertEqual(result["proof_status"], "refuted")
        self.assertEqual(result["witness_status"], "found")
        self.assertTrue(result["lines"])
        for line in result["lines"]:
            self.assert_line_consistent(pos, line)
            self.assertEqual(len(line["uci"]), 2)
            self.assertTrue(line["uci"][0].startswith("a3"))
            self.assertEqual(line["uci"][1][2:4], line["uci"][0][2:4])

    def test_capture_target_identity_survives_promotion(self):
        pos = position("7k/8/8/8/8/8/p6K/1R6 b - - 0 1")
        result = probe(pos, {"type": "capture", "side": "white", "target": "a2"},
                       max_depth=2, time_limit=3, max_lines=2)
        self.assertEqual(result["status"], "possible")
        for line in result["lines"]:
            self.assert_line_consistent(pos, line)
            self.assertTrue(line["uci"][0].startswith("a2a1"))
            self.assertEqual(line["uci"][1], "b1a1")

    def test_en_passant_capture_goal(self):
        pos = position("7k/8/8/3pP3/8/8/8/7K w - d6 0 1")
        result = probe(pos, {"type": "capture", "side": "white", "target": "d5"},
                       max_depth=1, time_limit=1)
        self.assertEqual(result["status"], "forced")
        self.assertIn(["e5d6"], [line["uci"] for line in result["lines"]])

    def test_avoid_goal_covers_entire_horizon(self):
        pos = position("r6k/8/8/8/8/8/8/4K3 w - - 0 1")
        goal = {"type": "avoid_check", "side": "white"}
        short = probe(pos, goal, max_depth=1, time_limit=2)
        longer = probe(pos, goal, max_depth=2, time_limit=2)
        self.assertEqual(short["status"], "forced")
        self.assertEqual(longer["status"], "possible")
        self.assertEqual(longer["proof_status"], "refuted")
        for line in longer["lines"]:
            self.assertEqual(len(line["uci"]), 2)
            for fen in line["fens"]:
                self.assertFalse(position(fen).in_check(WHITE))

    def test_avoid_capture_checks_adversarial_reply(self):
        pos = position("7k/8/8/8/8/q7/8/R6K b - - 0 1")
        result = probe(pos, {"type": "avoid_capture", "side": "white", "target": "a1"},
                       max_depth=1, time_limit=2)
        self.assertEqual(result["status"], "possible")
        self.assertEqual(result["proof_status"], "refuted")
        self.assertTrue(result["lines"])
        for line in result["lines"]:
            self.assert_line_consistent(pos, line)
            self.assertNotEqual(line["uci"][0], "a3a1")

    def test_avoid_mate_and_stalemate_are_distinct(self):
        pos = position("7k/8/5KQ1/8/8/8/8/8 w - - 0 1")
        for goal_type in ["avoid_checkmate", "avoid_stalemate"]:
            with self.subTest(goal=goal_type):
                result = probe(pos, {"type": goal_type, "side": "black"},
                               max_depth=1, time_limit=2)
                self.assertEqual(result["status"], "possible")
                self.assertEqual(result["proof_status"], "refuted")
                self.assertTrue(result["lines"])
                for line in result["lines"]:
                    self.assert_line_consistent(pos, line)
                    end = position(line["fens"][-1])
                    if not end.legal_moves():
                        self.assertEqual(end.in_check(), goal_type == "avoid_stalemate")

    def test_castling_check_mate_and_stalemate_goals(self):
        fixtures = [
            ("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1", {"type": "castle"}),
            ("7k/8/5KQ1/8/8/8/8/8 w - - 0 1", {"type": "check"}),
            ("7k/8/5KQ1/8/8/8/8/8 w - - 0 1", {"type": "checkmate"}),
            ("7k/8/5KQ1/8/8/8/8/8 w - - 0 1", {"type": "stalemate"}),
        ]
        for fen, goal in fixtures:
            with self.subTest(goal=goal):
                result = probe(position(fen), goal, max_depth=1, time_limit=2)
                self.assertEqual(result["status"], "forced")
                self.assertTrue(result["lines"])
                for line in result["lines"]:
                    self.assert_line_consistent(position(fen), line)

    def test_goal_timeout_is_unknown_not_a_proof(self):
        started = time.monotonic()
        result = probe(position(), {"type": "capture", "side": "white", "target": "d8"},
                       max_depth=12, time_limit=0.02)
        self.assertLess(time.monotonic() - started, 1.0)
        self.assertTrue(result["timed_out"])
        self.assertEqual(result["proof_status"], "unknown")
        self.assertNotIn(result["status"], {"forced", "unreachable"})

    def test_invalid_queries_rejected(self):
        for kwargs in [{"max_depth": 0}, {"max_depth": 33}, {"time_limit": 0},
                       {"time_limit": float("nan")}, {"time_limit": float("inf")}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                analyze(position(), **kwargs)
        for goal in [{"type": "capture"}, {"type": "capture", "target": "e4"},
                     {"type": "capture", "target": "e2"}, {"type": "magic"},
                     {"type": "check", "side": "purple"}, {"type": "check", "bogus": True}]:
            with self.subTest(goal=goal), self.assertRaises(ValueError):
                probe(position(), goal, max_depth=1, time_limit=0.1)


class InterfaceTests(unittest.TestCase):
    def test_prepare_future_position_and_history(self):
        from astra_chess import prepare

        root = play(position(), "e2e4", "e7e5")
        history = [position(), play(position(), "e2e4")]
        result = prepare({"fen": root.fen(), "after": ["g1f3", "b8c6"],
                          "history_fens": [p.fen() for p in history],
                          "root_moves": ["f1b5"], "depth": 3, "seconds": 0.5})
        final, earlier, mode, depth, seconds, count, root_moves, label = result
        self.assertEqual(final.fen(), play(root, "g1f3", "b8c6").fen())
        self.assertEqual([p.fen() for p in earlier], [p.fen() for p in history] +
                         [root.fen(), play(root, "g1f3").fen()])
        self.assertEqual(mode, "analyze")
        self.assertEqual(depth, 3)
        self.assertEqual(seconds, 0.5)
        self.assertEqual(root_moves, ["f1b5"])

    def test_prepare_rejects_misspelled_and_incompatible_fields(self):
        from astra_chess import prepare

        for query in [{"depht": 3}, {"mode": "analyse"}, {"goal": {"type": "check"}},
                      {"mode": "probe"}, {"mode": "probe", "goal": {}, "root_moves": ["e2e4"]},
                      {"root_moves": ["e2e4", "e2e4"]}, {"after": ["e2e5"]},
                      {"depth": True}, {"seconds": float("nan")}, {"candidates": 0}]:
            with self.subTest(query=query), self.assertRaises(ValueError):
                prepare(query)

    def test_shared_clock_preserves_reserve_and_engine_cap(self):
        from astra_chess import session_status

        session = {"started_monotonic": 100, "turn_seconds": 60, "engine_seconds": 12,
                   "reserve_seconds": 8, "engine_seconds_used": 3, "calls": 2}
        with patch("astra_chess.time.monotonic", return_value=120):
            status = session_status(session)
            self.assertEqual(status["remaining_seconds"], 40)
            self.assertEqual(status["query_available_seconds"], 9)
        with patch("astra_chess.time.monotonic", return_value=150):
            self.assertEqual(session_status(session)["query_available_seconds"], 2)
        with patch("astra_chess.time.monotonic", return_value=155):
            status = session_status(session)
            self.assertEqual(status["query_available_seconds"], 0)
            self.assertFalse(status["expired"])
        with patch("astra_chess.time.monotonic", return_value=161):
            self.assertTrue(session_status(session)["expired"])

    def test_cli_refuses_exhausted_budget_without_writing_answer(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            request = directory / "query.json"
            session = directory / "turn.json"
            output = directory / "answer.json"
            request.write_text(json.dumps({"depth": 1, "seconds": 0.05}), encoding="utf-8")
            session.write_text(json.dumps({"started_monotonic": time.monotonic(), "turn_seconds": 60,
                                          "engine_seconds": 12, "reserve_seconds": 8,
                                          "engine_seconds_used": 12, "calls": 3}), encoding="utf-8")
            completed = subprocess.run([sys.executable, str(ROOT / "astra_chess.py"), "query",
                                        "--request", str(request), "--session", str(session),
                                        "--output", str(output)], capture_output=True, text=True,
                                       timeout=5, cwd=ROOT)
            self.assertEqual(completed.returncode, 2, completed.stderr)
            self.assertIn("budget exhausted", completed.stderr)
            self.assertFalse(output.exists())
            self.assertFalse(session.with_name(session.name + ".lock").exists())

    def test_cli_rejects_unknown_goal_fields(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            request = directory / "query.json"
            output = directory / "answer.json"
            request.write_text(json.dumps({"mode": "probe", "goal": {"type": "check", "depty": 1},
                                           "depth": 1, "seconds": 0.05}), encoding="utf-8")
            completed = subprocess.run([sys.executable, str(ROOT / "astra_chess.py"), "query",
                                        "--request", str(request), "--output", str(output)],
                                       capture_output=True, text=True, timeout=5, cwd=ROOT)
            self.assertEqual(completed.returncode, 2, completed.stderr)
            self.assertIn("goal", completed.stderr.lower())
            self.assertFalse(output.exists())

    def test_cli_runs_without_site_packages_and_charges_active_budget(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            request = directory / "query.json"
            session = directory / "turn.json"
            output = directory / "answer.json"
            request.write_text(json.dumps({"depth": 12, "seconds": 1, "candidates": 2}), encoding="utf-8")
            session.write_text(json.dumps({"started_monotonic": time.monotonic(), "turn_seconds": 60,
                                          "engine_seconds": 0.03, "reserve_seconds": 8,
                                          "engine_seconds_used": 0, "calls": 0}), encoding="utf-8")
            completed = subprocess.run([sys.executable, "-S", str(ROOT / "astra_chess.py"), "query",
                                        "--request", str(request), "--session", str(session),
                                        "--output", str(output)], capture_output=True, text=True,
                                       timeout=5, cwd=ROOT)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            answer = json.loads(output.read_text(encoding="utf-8"))
            clock = json.loads(session.read_text(encoding="utf-8"))
            self.assertLessEqual(answer["query_time_limit_seconds"], 0.03)
            self.assertTrue(answer["candidates"])
            self.assertEqual(clock["calls"], 1)
            self.assertGreater(clock["engine_seconds_used"], 0)
            self.assertLess(clock["engine_seconds_used"], 0.5)
            self.assertEqual(answer["turn_budget"]["calls"], 1)
            self.assertFalse(session.with_name(session.name + ".lock").exists())


if __name__ == "__main__":
    unittest.main()
