from copy import deepcopy
import json
from pathlib import Path
import unittest

from astra_web.engine_view import compact_result


REPO = Path(__file__).resolve().parents[2]


def fixture(relative):
    return json.loads((REPO / relative).read_text(encoding="utf-8"))


class EngineViewTests(unittest.TestCase):
    def setUp(self):
        self.result = fixture("engine-games/wally-v02-black/turn-01-query-1.json")

    def test_archived_analysis_preserves_every_nonprojected_field_and_reduces_size(self):
        view = compact_result(self.result)
        self.assertEqual({key: value for key, value in view.items() if key != "candidates"},
                         {key: value for key, value in self.result.items() if key != "candidates"})
        for before, after in zip(self.result["candidates"], view["candidates"]):
            self.assertNotIn("position_diagnostics", after)
            self.assertIs(after["diagnostics_available"], True)
            self.assertEqual({key: value for key, value in before.items() if key != "position_diagnostics"},
                             {key: value for key, value in after.items() if key not in {"diagnostics_available", "diagnostic_summary"}})
        # Compare serialized payloads, not pretty-print indentation savings.
        compact = len(json.dumps(view, separators=(",", ":")))
        original = len(json.dumps(self.result, separators=(",", ":")))
        self.assertLess(compact, original * 0.65)

    def test_all_frame_warnings_limitations_context_and_tactical_changes_survive(self):
        result = fixture("engine-output/wally-bishop-threat-v02.json")
        view = compact_result(result)
        warnings = []
        for before, after in zip(result["candidates"], view["candidates"]):
            summary = after["diagnostic_summary"]
            for index, (frame, reduced) in enumerate(zip(before["position_diagnostics"], summary["frames"])):
                self.assertEqual(reduced["frame"], index)
                self.assertEqual(after["fens"][index], frame["fen"])
                self.assertEqual(reduced["warnings"], frame["warnings"])
                warnings.extend(reduced["warnings"])
                self.assertEqual([summary["limitations"][i] for i in reduced["limitation_indices"]], frame["limitations"])
                for field in ("side", "turn_context", "king_lines", "new_king_lines"):
                    self.assertEqual(reduced[field], frame[field])
        self.assertTrue(any("Capture threat" in text for text in warnings))
        self.assertTrue(any("Pawn advances" in text for text in warnings))
        # Exercise a nonempty king-line change even if this archived PV has none.
        line = {"kind": "single_screen", "attacker": "f8", "king": "f1", "screen": "f2", "line": ["f8", "f2", "f1"]}
        result["candidates"][0]["position_diagnostics"][1]["new_king_lines"] = [line]
        self.assertEqual(compact_result(result)["candidates"][0]["diagnostic_summary"]["frames"][1]["new_king_lines"], [line])

    def test_no_input_mutation_or_shared_nested_objects(self):
        before = deepcopy(self.result)
        view = compact_result(self.result)
        self.assertEqual(self.result, before)
        view["candidates"][0]["diagnostic_summary"]["frames"][0]["warnings"].append("changed copy")
        view["position_diagnostics"]["warnings"].append("changed root copy")
        view["candidates"][0]["uci"].append("changed line")
        self.assertEqual(self.result, before)

    def test_null_frames_incomplete_coverage_and_duplicate_limitations_are_explicit(self):
        candidate = self.result["candidates"][0]
        candidate["position_diagnostics"][1] = None
        candidate["position_diagnostics"][0]["limitations"] = ["Not a proof", "Not a proof", "Unknown beyond horizon"]
        self.result["diagnostic_coverage"].update(complete=False, positions_skipped=1)
        view = compact_result(self.result)
        summary = view["candidates"][0]["diagnostic_summary"]
        self.assertIsNone(summary["frames"][1])
        self.assertFalse(view["diagnostic_coverage"]["complete"])
        self.assertEqual(view["diagnostic_coverage"]["positions_skipped"], 1)
        self.assertEqual([summary["limitations"][i] for i in summary["frames"][0]["limitation_indices"]],
                         ["Not a proof", "Not a proof", "Unknown beyond horizon"])

    def test_fallback_null_scores_mate_and_draw_claim_fields_are_not_reinterpreted(self):
        self.result.update(fallback=True, timed_out=True, completed_depth=0, root_score_cp=None,
                           history_supplied=False, draw_claim_available=True, recommended_action="claim_draw",
                           intended_move="f6g8", draw_claim_reasons=["threefold_repetition"],
                           proof_status="unknown", future_proof={"status": "unknown", "limits": ["horizon"]})
        candidate = self.result["candidates"][0]
        candidate.update(score_cp=None, depth=0, score_is_exact_for_search=False,
                         ending="unevaluated_legal_fallback", claim_by_intended_move="f6g8", mate_in_plies=None)
        view = compact_result(self.result)
        for key in ("fallback", "timed_out", "completed_depth", "root_score_cp", "history_supplied", "draw_claim_available",
                    "recommended_action", "intended_move", "draw_claim_reasons", "proof_status", "future_proof"):
            self.assertEqual(view[key], self.result[key])
        for key in ("score_cp", "depth", "score_is_exact_for_search", "ending", "claim_by_intended_move", "mate_in_plies"):
            self.assertEqual(view["candidates"][0][key], candidate[key])
        candidate.update(score_cp=99999, mate_in_plies=1, ending="checkmate")
        mate = compact_result(self.result)["candidates"][0]
        self.assertEqual((mate["score_cp"], mate["mate_in_plies"], mate["ending"]), (99999, 1, "checkmate"))

    def test_goal_probe_unknown_proof_and_unrecognized_shapes_pass_through(self):
        probe = fixture("engine-output/mate-in-one.json")
        probe.update(status="unknown", proof_status="unknown", witness_status="found")
        # A future probe may also use candidates; kind still prevents projection.
        probe["candidates"] = self.result["candidates"]
        self.assertEqual(compact_result(probe), probe)
        for edit in (lambda c: c.update(position_diagnostics={"new_format": True}),
                     lambda c: c["position_diagnostics"][0].update(future_proof={"status": "unknown"}),
                     lambda c: c["position_diagnostics"][0]["minor_pieces"][0].update(limitations=["new warning"]),
                     lambda c: c["fens"].pop(),
                     lambda c: c.update(diagnostic_summary={"future": True})):
            result = deepcopy(self.result)
            edit(result["candidates"][0])
            self.assertEqual(compact_result(result)["candidates"][0], result["candidates"][0])
        for unknown in (None, [], {"kind": "future_analysis", "candidates": self.result["candidates"]}):
            self.assertEqual(compact_result(unknown), unknown)


if __name__ == "__main__":
    unittest.main()
