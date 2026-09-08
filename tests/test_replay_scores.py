"""Historical-score alignment and honest absence/mate semantics in game replays."""
import contextlib
import copy
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from build_replay import attach_evaluations, build, normalized_fen
from export_evaluations import extract


def embedded_data(text):
    return json.loads(re.search(r'<script id="replay-data" type="application/json">(.*?)</script>',
                               text, re.S).group(1))


class ReplayScoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pgn = ROOT / "engine-games/wally-engine-v02/game.pgn"
        cls.evaluations = ROOT / "engine-output/wally-v02-evaluation/data.json"
        cls.source = json.loads(cls.evaluations.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            output = Path(directory) / "replay.html"
            build(cls.pgn, output, "Engine v0.2 trial", evaluations=cls.evaluations)
            cls.html = output.read_text(encoding="utf-8")
            cls.data = embedded_data(cls.html)

    def with_rows(self, rows):
        frames = copy.deepcopy(self.data["frames"])
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "scores.json"
            source.write_text(json.dumps({"rows": rows}), encoding="utf-8")
            attach_evaluations(frames, source)
        return frames

    def test_all_actual_white_choices_match_and_black_frames_are_unscored(self):
        frames = self.data["frames"]
        self.assertEqual(len(frames), 62)
        self.assertEqual(self.data["evaluations"]["recordedChoices"], 31)
        self.assertIsNone(frames[0]["evaluation"])
        for row in self.source["rows"]:
            frame = frames[row["ply"] + 1]
            self.assertEqual(frame["move"]["uci"], row["uci"])
            self.assertEqual(frame["evaluation"]["source"], row["source"])
            if row["score_kind"] == "search_estimate":
                self.assertEqual(frame["evaluation"]["scoreCp"], row["score_cp"])
                self.assertIn("before this move", frame["evaluation"]["note"])
        self.assertTrue(all(f["evaluation"] is None for f in frames[2::2]))

    def test_mate_is_relative_to_displayed_board_not_encoded_material(self):
        frames = self.data["frames"]
        self.assertEqual(frames[57]["evaluation"]["label"], "Mate in 2")
        self.assertIn("5 plies", frames[57]["evaluation"]["note"])
        self.assertEqual(frames[59]["evaluation"]["label"], "Mate in 1")
        self.assertEqual(frames[61]["evaluation"]["label"], "Checkmate")
        self.assertTrue(frames[61]["mate"])
        for index in (57, 59, 61):
            self.assertIsNone(frames[index]["evaluation"]["scoreCp"])
        self.assertNotIn("299.95", self.html)

    def test_mismatched_move_position_turn_or_duplicate_rejected(self):
        original = self.source["rows"][0]
        mutations = [{"uci": "d2d4"}, {"san": "Nf3"}, {"move": 2}, {"ply": 1},
                     {"pre_move_fen": self.source["rows"][1]["pre_move_fen"]},
                     {"post_move_fen": original["post_move_fen"].replace(" 1 1", " 4 1")}]
        for change in mutations:
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.with_rows([dict(original, **change)])
        with self.assertRaises(ValueError):
            self.with_rows([original, original])

    def test_en_passant_notation_normalized_but_full_position_still_checked(self):
        row = copy.deepcopy(self.source["rows"][2])
        self.assertIn(" d3 ", row["post_move_fen"])
        self.assertIn(" - ", self.data["frames"][5]["fen"])
        self.assertEqual(self.with_rows([row])[5]["evaluation"]["label"], "+0.14 pawns")
        row["post_move_fen"] = row["post_move_fen"].replace(" KQkq ", " KQ ")
        with self.assertRaises(ValueError):
            self.with_rows([row])

    def test_missing_rows_stay_missing_and_malformed_scores_are_rejected(self):
        self.assertTrue(all(f["evaluation"] is None for f in self.with_rows([])))
        row = self.source["rows"][0]
        for change in ({"score_cp": None}, {"score_cp": float("nan")},
                       {"score_pawns": 2}, {"completed_depth": 0},
                       {"score_cp": 29995, "score_pawns": 299.95}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.with_rows([dict(row, **change)])

    def test_mate_proof_requires_forcing_status_and_actual_mate_requires_mate(self):
        row = copy.deepcopy(self.source["rows"][29])
        row["proof"]["status"] = "witness"
        with self.assertRaises(ValueError):
            self.with_rows([row])
        row = dict(self.source["rows"][0], score_kind="actual_checkmate", score_cp=None,
                   score_pawns=None, completed_depth=None)
        with self.assertRaises(ValueError):
            self.with_rows([row])

    def test_explicit_missing_choice_is_attached_without_carrying_a_previous_score(self):
        scored = self.source["rows"][0]
        missing = dict(self.source["rows"][1], score_kind="not_recorded", score_cp=None,
                       score_pawns=None, mate_in_plies=None, completed_depth=None, proof=None)
        frames = self.with_rows([scored, missing])
        self.assertEqual(frames[1]["evaluation"]["label"], "+0.00 pawns")
        self.assertIsNone(frames[2]["evaluation"])
        record = frames[3]["evaluation"]
        self.assertEqual(record["forMove"], "2. Nf3")
        self.assertEqual(record["label"], "No recorded evaluation")
        self.assertIsNone(record["scoreCp"])
        self.assertIsNone(record["depth"])
        self.assertIn("No score has been filled in", record["note"])
        for change in ({"score_cp": 0}, {"completed_depth": 3},
                       {"proof": {"status": "forced"}}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.with_rows([dict(missing, **change)])

    def test_forced_proof_uses_completed_depth_not_larger_requested_horizon(self):
        row = copy.deepcopy(self.source["rows"][29])
        row["proof"]["horizon_plies_from_post_move_position"] = 8
        row["proof"]["completed_depth"] = 2
        record = self.with_rows([row])[59]["evaluation"]
        self.assertEqual(record["label"], "Mate in 1")
        self.assertIn("2 plies", record["detail"])
        self.assertIn("at most", record["detail"])
        row["proof"]["horizon_plies_from_post_move_position"] = 3
        self.assertEqual(self.with_rows([row])[59]["evaluation"]["label"], "Mate in 1")
        row["proof"]["completed_depth"] = 4
        with self.assertRaises(ValueError):
            self.with_rows([row])

    def test_scored_mating_move_displays_checkmate_with_search_provenance(self):
        row = dict(self.source["rows"][30], score_kind="search_mate", score_cp=29999,
                   mate_in_plies=1, completed_depth=1)
        record = self.with_rows([row])[61]["evaluation"]
        self.assertEqual(record["label"], "Checkmate")
        self.assertEqual(record["kind"], "search_mate")
        self.assertEqual(record["mateMovesRemaining"], 0)
        self.assertEqual(record["depth"], 1)
        self.assertIsNone(record["scoreCp"])
        nonmate = dict(self.source["rows"][0], score_kind="search_mate", score_cp=29999,
                       score_pawns=None, mate_in_plies=1, completed_depth=1)
        with self.assertRaises(ValueError):
            self.with_rows([nonmate])

    def test_build_without_scores_remains_compatible_and_names_are_correct(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            output = Path(directory) / "plain.html"
            build(self.pgn, output)
            plain = embedded_data(output.read_text(encoding="utf-8"))
        self.assertNotIn("evaluations", plain)
        self.assertTrue(all("evaluation" not in f for f in plain["frames"]))
        self.assertEqual(plain["displayNames"]["white"], "Astra")
        self.assertIn("Astra (Ultra) vs. Wally", self.html)
        self.assertIn("Engine v0.2 trial", self.html)


class BlackReplayScoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pgn = ROOT / "engine-games/wally-v02-black/game.pgn"
        cls.source = extract("wally-v02-black")
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            source = Path(directory) / "scores.json"
            source.write_text(json.dumps(cls.source), encoding="utf-8")
            output = Path(directory) / "replay.html"
            build(cls.pgn, output, "Engine v0.2 trial / Astra as Black", evaluations=source)
            cls.html = output.read_text(encoding="utf-8")
            cls.data = embedded_data(cls.html)

    def attach(self, source):
        frames = copy.deepcopy(self.data["frames"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scores.json"
            path.write_text(json.dumps(source), encoding="utf-8")
            attach_evaluations(frames, path, player_side="black")
        return frames

    def test_black_identity_orientation_result_and_full_journal_match(self):
        self.assertEqual(self.data["playerSide"], "black")
        self.assertEqual(self.data["displayNames"], {"white": "Wally", "black": "Astra"})
        self.assertEqual(self.data["headers"]["WhiteElo"], "1800")
        self.assertNotIn("BlackElo", self.data["headers"])
        self.assertEqual(self.data["outcome"]["winner"], "black")
        self.assertIn("Astra (Ultra) vs. Wally", self.html)
        self.assertIn("Astra as Black", self.html)
        self.assertIn('[Black "Astra (Ultra)"]', self.data["pgn"])
        journal = json.loads((ROOT / "engine-games/wally-v02-black/game.json").read_text(encoding="utf-8"))
        self.assertEqual(len(self.data["frames"]), 97)
        self.assertEqual([normalized_fen(fen) for fen in journal["fens"]],
                         [frame["fen"] for frame in self.data["frames"]])
        self.assertEqual(journal["uci"], [frame["move"]["uci"] for frame in self.data["frames"][1:]])

    def test_scores_attach_only_after_black_moves_in_black_perspective(self):
        frames = self.data["frames"]
        self.assertEqual(self.data["evaluations"]["perspective"], "black")
        self.assertEqual(self.data["evaluations"]["recordedChoices"], 48)
        self.assertTrue(all(frame["evaluation"] is None for frame in frames[1::2]))
        for row in self.source["rows"]:
            evaluation = frames[row["ply"] + 1]["evaluation"]
            self.assertEqual(evaluation["forMove"], f"{row['move']}… {row['san']}")
            if row["score_kind"] == "search_estimate":
                self.assertEqual(evaluation["scoreCp"], row["score_cp"])
                self.assertIn("Positive favors Black", evaluation["detail"])
        for move in (42, 43, 44):
            value = frames[move * 2]["evaluation"]
            self.assertEqual(value["label"], "No recorded evaluation")
            self.assertIn("This Black move", value["note"])
        self.assertEqual(frames[90]["evaluation"]["label"], "+17.05 pawns")

    def test_black_mate_distances_adjust_to_displayed_board_and_final_result(self):
        frames = self.data["frames"]
        for ply, label in ((92, "Mate in 2"), (94, "Mate in 1"), (96, "Checkmate")):
            evaluation = frames[ply]["evaluation"]
            self.assertEqual(evaluation["label"], label)
            self.assertIn("Black", evaluation["detail"])
            self.assertIsNone(evaluation["scoreCp"])
        self.assertIn("5 plies", frames[92]["evaluation"]["note"])
        self.assertEqual(frames[96]["move"]["san"], "Rcxd2#")
        self.assertTrue(frames[96]["mate"])
        self.assertEqual(frames[96]["evaluation"]["kind"], "actual_checkmate")
        self.assertNotIn("299.95", self.html)

    def test_negative_black_root_mate_names_white_as_mating_side(self):
        source = copy.deepcopy(self.source)
        source["rows"] = [dict(source["rows"][0], score_kind="search_mate",
                              score_cp=-29996, score_pawns=None, mate_in_plies=-4, completed_depth=4)]
        value = self.attach(source)[2]["evaluation"]
        self.assertEqual(value["label"], "White mates in 2")
        self.assertIn("White moves remaining", value["detail"])

    def test_wrong_perspective_or_player_cannot_silently_reverse_scores(self):
        for change in ({"score_perspective": "white"}, {"player_side": "white"},
                       {"player_side": "red"}):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "perspective"):
                self.attach(dict(self.source, **change))


if __name__ == "__main__":
    unittest.main()
