"""Historical evaluation provenance, without search or browser interaction."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from astra_engine.rules import Position, START_FEN
import export_evaluations as exporter


class EvaluationExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = self.root / "engine-games" / "trial"
        self.folder.mkdir(parents=True)
        self.before = Position.from_fen(START_FEN)
        self.after = self.before.play(self.before.parse_uci("e2e4"))
        self.turn = {"ply": 0, "move": 1, "selected_move": "e2e4", "selected_san": "e4",
                     "initial_candidate": "d2d4", "assessment": "Compared candidates.",
                     "verified_utc": "2026-09-07T12:00:00Z", "queries": []}
        self.game = {"white": "Astra (Ultra)", "black": "Test bot", "round": 12,
                     "date": "2026.09.07", "result": "*", "uci": ["e2e4"],
                     "san": ["e4"], "fens": [self.before.fen(), self.after.fen()],
                     "turns": [self.turn], "pending": None}

    def save(self, path, value):
        path.write_text(json.dumps(value), encoding="utf-8")

    def query(self, name, score=25, *, mate=None):
        path = self.folder / f"{name}.json"
        query = {"kind": "analysis", "start_fen": self.before.fen(), "turn": "white",
                 "completed_depth": 4, "fallback": False, "elapsed_seconds": 1.25,
                 "timed_out": True, "candidates": [{"root_move": "e2e4", "uci": ["e2e4"],
                    "san": ["e4"], "fens": [self.before.fen(), self.after.fen()],
                    "score_cp": score, "mate_in_plies": mate, "depth": 4,
                    "rank": 1, "score_is_exact_for_search": True}]}
        self.save(path, query)
        self.turn["queries"].append(path.relative_to(self.root).as_posix())
        return path, query

    def extract(self):
        self.save(self.folder / "game.json", self.game)
        return exporter.extract("trial", root=self.root)

    def test_latest_matching_completed_query_and_actual_post_move_required(self):
        self.query("first", 25)
        hypothetical_path, hypothetical = self.query("hypothetical", 999)
        hypothetical["start_fen"] = self.after.fen()
        self.save(hypothetical_path, hypothetical)
        latest_path, latest = self.query("latest", 45)
        fallback_path, fallback = self.query("fallback", 800)
        fallback["fallback"] = True
        self.save(fallback_path, fallback)
        absent_path, absent = self.query("different-choice", 900)
        absent["candidates"][0]["root_move"] = "d2d4"
        self.save(absent_path, absent)

        result = self.extract()
        row = result["rows"][0]
        self.assertEqual((row["score_cp"], row["score_pawns"]), (45, 0.45))
        self.assertEqual(row["source"], latest_path.relative_to(self.root).as_posix())
        self.assertEqual(len([item for item in row["audit"] if "excluded" in item]), 3)
        self.assertEqual(result["source_sha256"][row["source"]],
                         hashlib.sha256(latest_path.read_bytes()).hexdigest())
        latest["candidates"][0]["fens"][1] = self.before.fen()
        self.save(latest_path, latest)
        with self.assertRaisesRegex(ValueError, "timeline disagrees"):
            self.extract()

    def test_pending_choice_is_omitted_even_when_it_has_a_submission_time(self):
        black = self.after.play(self.after.parse_uci("e7e5"))
        self.game["uci"].append("e7e5")
        self.game["san"].append("e5")
        self.game["fens"].append(black.fen())
        self.game["pending"] = {"uci": "g1f3", "san": "Nf3", "submitted_utc": "2026-09-07T12:01:00Z"}
        pending = deepcopy(self.turn)
        pending.update(ply=2, move=2, selected_move="g1f3", selected_san="Nf3",
                       queries=["engine-games/trial/not-yet-written-query.json"])
        pending.pop("verified_utc")
        self.game["turns"].append(pending)
        rows = self.extract()["rows"]
        self.assertEqual([row["uci"] for row in rows], ["e2e4"])
        self.assertEqual(rows[0]["score_kind"], "not_recorded")
        self.assertIsNone(rows[0]["score_cp"])

    def test_mate_encodings_and_goal_proofs_never_become_pawn_scores(self):
        self.query("mate", 29995, mate=5)
        row = self.extract()["rows"][0]
        self.assertEqual((row["score_kind"], row["mate_in_plies"]), ("search_mate", 5))
        self.assertIsNone(row["score_pawns"])

        self.turn["queries"] = ["engine-games/trial/proof.json"]
        proof = {"kind": "goal_probe", "start_fen": self.after.fen(),
                 "goal": {"type": "checkmate", "side": "white"},
                 "proof_status": "forced", "horizon_plies": 2, "proof_completed_depth": 2}
        self.save(self.folder / "proof.json", proof)
        self.save(self.folder / "proof.request.json", {"fen": self.before.fen(), "after": ["e2e4"]})
        row = self.extract()["rows"][0]
        self.assertEqual(row["score_kind"], "forced_mate_proof")
        self.assertEqual(row["proof"]["horizon_plies_from_post_move_position"], 2)
        for field in ("score_cp", "score_pawns", "mate_in_plies"):
            self.assertIsNone(row[field])

        proof.update(proof_status="refuted", witness_status="found", status="possible")
        self.save(self.folder / "proof.json", proof)
        row = self.extract()["rows"][0]
        self.assertEqual(row["score_kind"], "not_recorded")
        self.assertIsNone(row["proof"])

    def test_game_nine_rows_and_source_hashes_preserve_original_chart_evidence(self):
        saved = json.loads((exporter.ROOT / "engine-output/wally-v02-evaluation/data.json").read_text(encoding="utf-8"))
        result = exporter.extract("wally-engine-v02")
        self.assertEqual(result["rows"], saved["rows"])
        self.assertEqual(result["source_sha256"], saved["source_sha256"])
        self.assertEqual(len(result["rows"]), 31)
        self.assertEqual([row["move"] for row in result["rows"] if row["score_pawns"] is None], [29, 30, 31])
        self.assertEqual(result["rows"][-1]["score_kind"], "actual_checkmate")


if __name__ == "__main__":
    unittest.main()
