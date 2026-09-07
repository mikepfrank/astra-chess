"""Threat hints must stay distinct from adversarial evidence."""

import json
from pathlib import Path
import random
import unittest

from astra_engine.diagnostics import (diagnose, extra_evaluate, threat_frontier,
                                      _capture_threats, _minor_geometry,
                                      _minor_safe_count, _pawn_controls, _view)
from astra_engine.rules import BLACK, WHITE, START_FEN, Position


def position(fen=START_FEN):
    return Position.from_fen(fen)


def move(pos, uci):
    return pos.play(pos.parse_uci(uci))


def minor(report, square):
    return next(piece for piece in report["minor_pieces"] if piece["square"] == square)


class DiagnosticsTests(unittest.TestCase):
    def test_game_bishop_blockers_and_legal_pawn_push(self):
        game = json.loads((Path(__file__).resolve().parents[1] / "engine-games" /
                           "wally-2026-09-07" / "game.json").read_text())
        before = position(game["fens"][40])
        report = diagnose(before)
        bishop = minor(report, "d3")
        self.assertTrue({"c2", "e2"}.issubset(bishop["own_blockers"]))
        self.assertTrue(bishop["restricted_mobility"])
        self.assertIn("c5c4", bishop["pawn_push_threats"])
        self.assertEqual(report["turn_context"], "enemy_next_turn_hypothesis")
        after = move(before, "f1d1")
        self.assertEqual(diagnose(after, side=WHITE)["turn_context"], "enemy_to_move")
        self.assertIn("c5c4", minor(diagnose(after, side=WHITE), "d3")["pawn_push_threats"])
        # A rook could sacrifice itself on d3 even before ...c4. Do not turn
        # that unprofitable exchange into the quiet-threat extension trigger.
        self.assertFalse(threat_frontier(before))
        threatened = position(game["fens"][42])
        self.assertTrue(threat_frontier(threatened))
        self.assertIn("c4d3", minor(diagnose(threatened), "d3")["legal_capture_threats"])

    def test_safe_immobile_starting_pieces_are_not_capture_threats(self):
        pos = position()
        bishop = minor(diagnose(pos), "c1")
        self.assertTrue(bishop["restricted_mobility"])
        self.assertEqual(bishop["legal_capture_threats"], [])
        self.assertFalse(threat_frontier(pos))
        self.assertEqual(extra_evaluate(pos, {"restricted_piece": True}), 0)

    def test_pinned_pawn_capture_is_not_a_legal_threat(self):
        pos = position("4k3/2P1p3/3BR3/2P1P3/8/8/8/K7 w - - 0 1")
        self.assertTrue(pos.is_attacked(43, BLACK))  # d6 is pawn-controlled.
        bishop = minor(diagnose(pos), "d6")
        self.assertTrue(bishop["restricted_mobility"])
        self.assertEqual(bishop["legal_capture_threats"], [])
        self.assertFalse(threat_frontier(pos))
        self.assertEqual(extra_evaluate(pos, {"restricted_piece": True}), 0)

    def test_pinned_pawn_advance_is_not_reported(self):
        pinned = position("7k/8/5p2/8/4N3/2B5/8/K7 w - - 0 1")
        free = position("6k1/8/5p2/8/4N3/2B5/8/K7 w - - 0 1")
        self.assertNotIn("f6f5", minor(diagnose(pinned), "e4")["pawn_push_threats"])
        self.assertIn("f6f5", minor(diagnose(free), "e4")["pawn_push_threats"])

    def test_restricted_piece_can_capture_attacker_or_open_an_exit(self):
        pos = position("6k1/8/8/8/2p1P3/3B4/2P1P3/R5K1 w - - 0 1")
        bishop = minor(diagnose(pos), "d3")
        self.assertTrue(bishop["restricted_mobility"])
        self.assertIn("c4d3", bishop["legal_capture_threats"])
        self.assertTrue(threat_frontier(pos))
        captured = move(pos, "d3c4")
        self.assertEqual(minor(diagnose(captured, side=WHITE), "c4")["legal_capture_threats"], [])
        opened = move(pos, "c2c3")
        opened_bishop = minor(diagnose(opened, side=WHITE), "d3")
        self.assertIn("c2", opened_bishop["pawn_safe_destinations"])
        self.assertFalse(opened_bishop["restricted_mobility"])
        # A forcing countercheck is legal even though the bishop has few squares.
        checked = move(pos, "a1a8")
        self.assertTrue(checked.in_check())
        self.assertEqual(minor(diagnose(checked, side=WHITE), "d3")["legal_capture_threats"], [])
        report = diagnose(pos)
        self.assertNotIn("proof_status", report)
        self.assertNotIn("forced_loss", report)
        self.assertTrue(any("compensation" in text for text in report["limitations"]))

    def test_new_near_king_file_access_after_pawn_capture(self):
        pos = position("k4r2/8/8/8/8/6p1/5P2/6K1 w - - 0 1")
        after = move(pos, "f2g3")
        report = diagnose(after, side=WHITE, previous=pos)
        access = [line for line in report["new_king_lines"] if line["kind"] == "open_file_access"]
        self.assertTrue(any(line["attacker"] == "f8" and line["entry"] == "f1" for line in access))
        self.assertLess(extra_evaluate(after, {"king_exposure": True}),
                        extra_evaluate(pos, {"king_exposure": True}))

    def test_winning_counterattack_can_outweigh_a_restricted_piece(self):
        pos = position("7k/6pp/8/7Q/1P6/1pPB4/N7/2R3K1 w - - 0 1")
        knight = minor(diagnose(pos), "a2")
        self.assertTrue(knight["restricted_mobility"])
        self.assertIn("b3a2", knight["legal_capture_threats"])
        self.assertTrue(threat_frontier(pos))
        # White need not save the knight: Qxh7 ends the game immediately.
        mate = pos.parse_uci("h5h7")
        self.assertEqual(pos.san(mate), "Qxh7#")
        after = pos.play(mate)
        self.assertTrue(after.in_check())
        self.assertEqual(after.legal_moves(), [])

    def test_direct_king_line_and_single_friendly_screen(self):
        screened = position("k4r2/8/8/8/8/8/5N2/5K2 w - - 0 1")
        line = next(line for line in diagnose(screened)["king_lines"] if line["kind"] == "single_screen")
        self.assertEqual(line["screen"], "f2")
        self.assertEqual(line["attacker"], "f8")
        checked = position("k4r2/8/8/8/8/8/8/5K2 w - - 0 1")
        self.assertTrue(any(line["kind"] == "clear_line" for line in diagnose(checked)["king_lines"]))

    def test_final_attack_reports_king_access(self):
        pos = position("8/R4pk1/6p1/3Np2p/1P2n3/3Q1KPq/5P2/4r3 w - - 2 41")
        lines = diagnose(pos)["king_lines"]
        self.assertTrue(any(line["attacker"] == "e1" and line.get("entry") == "e3" for line in lines))

    def test_optional_evaluation_is_additive_capped_and_color_symmetric(self):
        pos = position("6k1/8/8/8/2p1P3/3B4/2P1P3/R5K1 w - - 0 1")
        options = {"mobility": True, "restricted_piece": True, "king_exposure": True}
        self.assertEqual(extra_evaluate(pos), 0)
        self.assertEqual(extra_evaluate(pos, {key: False for key in options}), 0)
        self.assertEqual(extra_evaluate(pos, options),
                         sum(extra_evaluate(pos, {key: True}) for key in options))
        self.assertGreaterEqual(extra_evaluate(pos, {"restricted_piece": True}), -48)
        mirrored = Position(tuple(piece.swapcase() for piece in reversed(pos.board)),
                            BLACK, "", None, pos.halfmove, pos.fullmove)
        self.assertEqual(extra_evaluate(pos, options), -extra_evaluate(mirrored, options))

    def test_reports_serialize_and_do_not_mutate_board(self):
        pos = position()
        report = diagnose(pos, side=BLACK, previous=pos)
        self.assertEqual(json.loads(json.dumps(report)), report)
        self.assertEqual(pos.fen(), START_FEN)
        self.assertEqual(report["new_king_lines"], [])
        with self.assertRaises(ValueError):
            diagnose(pos, side=2)

    def test_targeted_captures_and_fast_counts_match_full_rules(self):
        rng = random.Random(741)
        pos = position()
        for _ in range(160):
            controls = _pawn_controls(pos.board)
            for side in (WHITE, BLACK):
                enemy_view = _view(pos, 1 - side)
                legal = enemy_view.legal_moves()
                for sq, piece in enumerate(pos.board):
                    if piece.lower() not in ("b", "n") or piece.isupper() != (side == WHITE):
                        continue
                    expected = {candidate.uci() for candidate in legal if candidate.to_sq == sq}
                    self.assertEqual({candidate.uci() for candidate in _capture_threats(pos, sq, 1 - side)}, expected)
                    count = len(_minor_geometry(pos.board, sq, controls[1 - side])[2])
                    for cap in (2, 8):
                        self.assertEqual(_minor_safe_count(pos.board, sq, controls[1 - side], cap), min(count, cap))
            legal = pos.legal_moves()
            pos = pos.play(rng.choice(legal)) if legal else position()


if __name__ == "__main__":
    unittest.main()
