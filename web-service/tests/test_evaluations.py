from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
import uuid

from fastapi.testclient import TestClient

from astra_web.app import create_app
from astra_web import chess_game as game
from astra_web.config import Config
from astra_web.evaluations import MAX_RESULT_BYTES, latest_astra_evaluation


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.config = Config(data_dir=Path(self.directory.name), origin="http://testserver",
                             player_mode="disabled", secure_cookies=False, smtp_host="", smtp_from="")

    def state(self, astra_side="black"):
        state = game.new_game({"id": "test-player", "name": "Player"},
                              "white" if astra_side == "black" else "black", self.config)
        moves = ["e2e4", "e7e5", "g1f3", "b8c6"] if astra_side == "black" else ["e2e4", "e7e5"]
        for uci in moves:
            actor = "astra" if game.side_to_move(state) == astra_side else "human"
            game.apply_move(state, uci, actor)
        return state

    def result(self, state, score=-12, ply=None):
        if ply is None:
            ply = max(i for i, move in enumerate(state["moves"]) if move["actor"] == "astra")
        chosen = state["moves"][ply]
        before = game.START_FEN if ply == 0 else state["moves"][ply - 1]["fen"]
        candidate = {"root_move": chosen["uci"], "uci": [chosen["uci"]], "san": [chosen["san"]],
                     "fens": [before, chosen["fen"]], "rank": 2, "score_cp": score,
                     "mate_in_plies": None, "depth": 5, "score_is_exact_for_search": True}
        return {"kind": "analysis", "start_fen": before, "turn": state["astra_side"],
                "completed_depth": 5, "fallback": False, "timed_out": True,
                "candidates": [candidate], "query": {"mode": "analyze", "fen": before}}

    def goal_result(self, state, *, direct_after=True, depth=6, ply=None):
        if ply is None:
            ply = max(i for i, move in enumerate(state["moves"]) if move["actor"] == "astra")
        chosen = state["moves"][ply]
        before = game.START_FEN if ply == 0 else state["moves"][ply - 1]["fen"]
        pre_move = deepcopy(state)
        pre_move.update(moves=state["moves"][:ply], fen=before)
        history = game.history(pre_move)
        goal = {"type": "checkmate", "side": state["astra_side"]}
        start_fen = chosen["fen"] if direct_after else before
        board = game.Position.from_fen(start_fen)
        # These are stored-result fixtures, not claims about the opening position.
        # Legal line metadata is intentionally shorter than the forced proof depth.
        line = {"uci": [], "san": [], "fens": [start_fen], "ending": "goal_reached",
                "claim_by_intended_move": None, "evidence": "proof_representative"}
        for index in range(4):
            legal = board.legal_moves()
            if not legal:
                break
            move = board.parse_uci(chosen["uci"]) if not direct_after and index == 0 else legal[0]
            line["uci"].append(move.uci())
            line["san"].append(board.san(move))
            board = board.play(move)
            line["fens"].append(board.fen())
        return {"kind": "goal_probe", "start_fen": start_fen, "goal": deepcopy(goal),
                "horizon_plies": 8, "status": "forced", "proof_status": "forced",
                "proof_completed_depth": depth, "witness_status": "found", "lines": [line],
                "history_supplied": True, "position_history_fens": history + ([before] if direct_after else []),
                "timed_out": False, "diagnostics": {"proof_budget_exhausted": False,
                    "witness_budget_exhausted": False},
                "query": {"mode": "probe", "fen": before, "after": [chosen["uci"]] if direct_after else [],
                          "history_fens": history, "goal": goal, "depth": 8}}

    def save(self, state, result, *, ply=None, name=None):
        if ply is None:
            ply = max(i for i, move in enumerate(state["moves"]) if move["actor"] == "astra")
        relative = Path("games") / state["id"] / "queries" / (name or f"{len(state['queries'])}.result.json")
        path = self.config.data_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if result is not None:
            path.write_text(json.dumps(result), encoding="utf-8")
        state["queries"].append({"ply": ply, "path": str(relative)})
        return path

    def evaluate(self, state):
        return latest_astra_evaluation(state, self.config.data_dir)

    def test_black_actual_rank_two_score_survives_later_hypothetical_and_human_reply(self):
        state = self.state("black")
        result = self.result(state)
        best = deepcopy(result["candidates"][0])
        best.update(root_move="g8f6", uci=["g8f6"], san=["Nf6"], rank=1, score_cp=44)
        result["candidates"].insert(0, best)
        self.save(state, result)
        hypothetical = deepcopy(result)
        hypothetical.update(start_fen=state["fen"], turn="white")
        hypothetical["query"]["after"] = ["b8c6"]
        self.save(state, hypothetical)
        expected = {"score_pawns": -0.12, "mate_in_moves": None, "mate_for": None,
                    "ply": 3, "uci": "b8c6", "san": "Nc6", "completed_depth": 5}
        self.assertEqual(self.evaluate(state), expected)
        game.apply_move(state, "f1b5", "human")
        self.assertEqual(self.evaluate(state), expected)
        self.assertNotIn("path", self.evaluate(state))

    def test_latest_qualifying_query_order_wins_not_depth_rank_or_filename(self):
        state = self.state()
        self.save(state, self.result(state, 25), name="z-old.result.json")
        later = self.result(state, -37)
        later["completed_depth"] = later["candidates"][0]["depth"] = 3
        self.save(state, later, name="a-new.result.json")
        self.assertEqual(self.evaluate(state)["score_pawns"], -0.37)
        self.assertEqual(self.evaluate(state)["completed_depth"], 3)
        fallback = self.result(state, 900)
        fallback["fallback"] = True
        self.save(state, fallback)
        self.assertEqual(self.evaluate(state)["score_pawns"], -0.37)

    def test_white_score_and_no_reuse_of_an_older_astra_move(self):
        state = self.state("white")
        self.save(state, self.result(state, 123))
        self.assertEqual(self.evaluate(state)["score_pawns"], 1.23)
        self.assertEqual(self.evaluate(state)["ply"], 0)
        game.apply_move(state, "g1f3", "astra")
        self.assertIsNone(self.evaluate(state))
        self.save(state, self.result(state, -6))
        self.assertEqual(self.evaluate(state)["score_pawns"], -0.06)

    def test_mate_distance_is_after_selected_move_and_signed_for_either_color(self):
        for side in ("white", "black"):
            for plies, moves, winner in ((3, 1, "astra"), (5, 2, "astra"), (-4, 2, "opponent")):
                with self.subTest(side=side, plies=plies):
                    state = self.state(side)
                    result = self.result(state, 30000 - plies if plies > 0 else -30000 - plies)
                    result["candidates"][0]["mate_in_plies"] = plies
                    self.save(state, result)
                    actual = self.evaluate(state)
                    self.assertIsNone(actual["score_pawns"])
                    self.assertEqual((actual["mate_in_moves"], actual["mate_for"]), (moves, winner))

    def test_direct_after_goal_proof_uses_completed_depth_not_shorter_line_for_both_colors(self):
        for side in ("white", "black"):
            with self.subTest(side=side):
                state = self.state(side)
                result = self.goal_result(state)
                ply = 0 if side == "white" else 3
                chosen = state["moves"][ply]
                authentic_history = [] if ply == 0 else [game.START_FEN] + [m["fen"] for m in state["moves"][:ply - 1]]
                self.assertEqual(result["query"]["history_fens"], authentic_history)
                self.assertEqual(result["position_history_fens"], authentic_history + [result["query"]["fen"]])
                self.assertEqual(len(result["lines"][0]["uci"]), 4)
                self.save(state, result)
                self.assertEqual(self.evaluate(state), {"score_pawns": None, "mate_in_moves": 3,
                    "mate_for": "astra", "ply": ply, "uci": chosen["uci"], "san": chosen["san"],
                    "completed_depth": 6, "source": "goal_probe"})

    def test_pre_move_goal_proof_requires_actual_first_move_and_excludes_it_from_distance(self):
        for side in ("white", "black"):
            for omit_after in (False, True):
                with self.subTest(side=side, omit_after=omit_after):
                    state = self.state(side)
                    result = self.goal_result(state, direct_after=False, depth=5)
                    if omit_after:
                        result["query"].pop("after")
                    self.save(state, result)
                    actual = self.evaluate(state)
                    self.assertEqual((actual["mate_in_moves"], actual["mate_for"]), (2, "astra"))
                    self.assertEqual(actual["source"], "goal_probe")

    def test_forced_goal_proof_survives_later_numeric_query_and_human_reply_but_not_next_astra_move(self):
        state = self.state("black")
        self.save(state, self.goal_result(state))
        self.save(state, self.result(state, -70))
        expected = self.evaluate(state)
        self.assertEqual(expected["mate_in_moves"], 3)
        self.assertEqual(expected["source"], "goal_probe")
        game.apply_move(state, "f1b5", "human")
        self.assertEqual(self.evaluate(state), expected)
        game.apply_move(state, "a7a6", "astra")
        self.assertIsNone(self.evaluate(state))

    def test_witness_timeout_does_not_discard_an_already_completed_forced_proof(self):
        state = self.state()
        result = self.goal_result(state)
        result["timed_out"] = True
        result["diagnostics"]["witness_budget_exhausted"] = True
        self.save(state, result)
        self.assertEqual(self.evaluate(state)["mate_in_moves"], 3)

    def test_direct_after_opponent_goal_and_omitted_query_side_follow_probe_root_turn(self):
        for side in ("white", "black"):
            for omit_side in (False, True):
                with self.subTest(side=side, omit_side=omit_side):
                    state = self.state(side)
                    result = self.goal_result(state, depth=5)
                    opponent = "white" if side == "black" else "black"
                    result["goal"]["side"] = opponent
                    result["query"]["goal"]["side"] = opponent
                    if omit_side:
                        result["query"]["goal"].pop("side")
                    self.save(state, result)
                    actual = self.evaluate(state)
                    self.assertEqual((actual["mate_in_moves"], actual["mate_for"]), (3, "opponent"))
        state = self.state()
        result = self.goal_result(state, direct_after=False, depth=5)
        result["query"]["goal"].pop("side")
        self.save(state, result)
        self.assertEqual(self.evaluate(state)["mate_for"], "astra")

    def test_goal_probe_requires_exact_root_history_and_completed_forced_mate_evidence(self):
        changes = {
            "wrong kind": lambda r: r.update(kind="other"),
            "unknown proof": lambda r: r.update(proof_status="unknown"),
            "refuted proof": lambda r: r.update(proof_status="refuted"),
            "witness only": lambda r: r.update(status="possible", proof_status="refuted"),
            "inconsistent status": lambda r: r.update(status="unknown"),
            "nonmate result goal": lambda r: r["goal"].update(type="check"),
            "nonmate matching goals": lambda r: (r["goal"].update(type="check"), r["query"]["goal"].update(type="check")),
            "mismatched requested side": lambda r: r["query"]["goal"].update(side="white"),
            "wrong query mode": lambda r: r["query"].update(mode="analyze"),
            "filtered root moves": lambda r: r["query"].update(root_moves=["b8c6"]),
            "wrong requested depth": lambda r: r["query"].update(depth=7),
            "boolean requested depth": lambda r: r["query"].update(depth=True),
            "missing query": lambda r: r.pop("query"),
            "wrong original root FEN": lambda r: r["query"].update(fen=game.START_FEN),
            "wrong result root FEN": lambda r: r.update(start_fen=game.START_FEN),
            "wrong after move": lambda r: r["query"].update(after=["g8f6"]),
            "multiple hypothetical moves": lambda r: r["query"]["after"].append("f1b5"),
            "non-list after": lambda r: r["query"].update(after="b8c6"),
            "missing supplied history flag": lambda r: r.pop("history_supplied"),
            "history not supplied": lambda r: r.update(history_supplied=False),
            "numeric history flag": lambda r: r.update(history_supplied=1),
            "missing request history": lambda r: r["query"].pop("history_fens"),
            "wrong request history": lambda r: r["query"].update(history_fens=[]),
            "root duplicated in request history": lambda r: r["query"]["history_fens"].append(r["query"]["fen"]),
            "wrong expanded history": lambda r: r.update(position_history_fens=r["query"]["history_fens"]),
            "missing expanded history": lambda r: r.pop("position_history_fens"),
            "zero proof depth": lambda r: r.update(proof_completed_depth=0),
            "negative proof depth": lambda r: r.update(proof_completed_depth=-1),
            "Astra cannot mate on opponent's first ply": lambda r: r.update(proof_completed_depth=1),
            "Astra cannot mate on opponent's fifth ply": lambda r: r.update(proof_completed_depth=5),
            "boolean proof depth": lambda r: r.update(proof_completed_depth=True),
            "fractional proof depth": lambda r: r.update(proof_completed_depth=5.5),
            "missing proof depth": lambda r: r.pop("proof_completed_depth"),
            "proof beyond horizon": lambda r: r.update(proof_completed_depth=9),
            "invalid horizon": lambda r: r.update(horizon_plies=0),
            "boolean horizon": lambda r: r.update(horizon_plies=True),
            "oversize horizon": lambda r: (r.update(horizon_plies=33), r["query"].update(depth=33)),
            "proof exhausted": lambda r: r["diagnostics"].update(proof_budget_exhausted=True),
            "missing proof diagnostics": lambda r: r.pop("diagnostics"),
            "missing proof budget flag": lambda r: r["diagnostics"].pop("proof_budget_exhausted"),
        }
        for label, change in changes.items():
            with self.subTest(case=label):
                state = self.state()
                result = self.goal_result(state)
                change(result)
                self.save(state, result)
                self.assertIsNone(self.evaluate(state))

    def test_pre_move_goal_probe_rejects_wrong_selected_line_or_opponent_goal(self):
        changes = {
            "no representative line": lambda r: r.update(lines=[]),
            "cooperative line": lambda r: r["lines"][0].update(evidence="cooperative_witness"),
            "wrong first UCI": lambda r: r["lines"][0]["uci"].__setitem__(0, "g8f6"),
            "wrong first SAN": lambda r: r["lines"][0]["san"].__setitem__(0, "Nf6"),
            "wrong before FEN": lambda r: r["lines"][0]["fens"].__setitem__(0, game.START_FEN),
            "wrong after FEN": lambda r: r["lines"][0]["fens"].__setitem__(1, game.START_FEN),
            "wrong line ending": lambda r: r["lines"][0].update(ending="draw_claim"),
            "already mated after move": lambda r: r.update(proof_completed_depth=1),
            "Astra cannot mate on opponent's even ply": lambda r: r.update(proof_completed_depth=4),
            "opponent goal": lambda r: (r["goal"].update(side="white"), r["query"]["goal"].update(side="white")),
        }
        for label, change in changes.items():
            with self.subTest(case=label):
                state = self.state()
                result = self.goal_result(state, direct_after=False, depth=5)
                change(result)
                self.save(state, result)
                self.assertIsNone(self.evaluate(state))

    def test_impossible_goal_proof_parity_preserves_valid_numeric_fallback(self):
        state = self.state()
        self.save(state, self.result(state, 42))
        self.save(state, self.goal_result(state, depth=5))
        actual = self.evaluate(state)
        self.assertEqual(actual["score_pawns"], 0.42)
        self.assertIsNone(actual["mate_in_moves"])
        self.assertNotIn("source", actual)

    def test_goal_probe_is_hidden_after_actual_checkmate(self):
        state = game.new_game({"id": "player", "name": "Player"}, "white", self.config)
        for move in ("f2f3", "e7e5", "g2g4", "d8h4"):
            game.apply_move(state, move, "astra" if game.side_to_move(state) == "black" else "human")
        result = self.goal_result(state, direct_after=False, depth=1)
        self.save(state, result)
        self.assertEqual(state["termination"], "checkmate")
        self.assertIsNone(self.evaluate(state))

    def test_initial_and_actual_checkmate_positions_have_no_display_evaluation(self):
        initial = game.new_game({"id": "player", "name": "Player"}, "white", self.config)
        self.assertIsNone(self.evaluate(initial))
        for side in ("white", "black"):
            state = game.new_game({"id": "player", "name": "Player"},
                                  "black" if side == "white" else "white", self.config)
            for move in ("f2f3", "e7e5", "g2g4", "d8h4"):
                game.apply_move(state, move, "astra" if game.side_to_move(state) == side else "human")
            self.assertEqual(state["termination"], "checkmate")
            self.save(state, self.result(state))
            self.assertIsNone(self.evaluate(state))

    def test_wrong_or_unevaluated_provenance_is_unavailable(self):
        changes = {
            "probe": lambda r: r.update(kind="goal_probe"),
            "wrong pre FEN": lambda r: r.update(start_fen=game.START_FEN),
            "wrong side": lambda r: r.update(turn="white"),
            "fallback": lambda r: r.update(fallback=True),
            "no completed depth": lambda r: r.update(completed_depth=0),
            "boolean depth": lambda r: r.update(completed_depth=True),
            "nonexact": lambda r: r["candidates"][0].update(score_is_exact_for_search=False),
            "wrong depth": lambda r: r["candidates"][0].update(depth=4),
            "wrong root move": lambda r: r["candidates"][0].update(root_move="g8f6"),
            "wrong UCI": lambda r: r["candidates"][0].update(uci=["g8f6"]),
            "wrong SAN": lambda r: r["candidates"][0].update(san=["Nf6"]),
            "wrong post FEN": lambda r: r["candidates"][0]["fens"].__setitem__(1, game.START_FEN),
            "missing score": lambda r: r["candidates"][0].update(score_cp=None),
            "nan score": lambda r: r["candidates"][0].update(score_cp=float("nan")),
            "infinite score": lambda r: r["candidates"][0].update(score_cp=float("inf")),
            "boolean score": lambda r: r["candidates"][0].update(score_cp=True),
            "overflowing score": lambda r: r["candidates"][0].update(score_cp=10 ** 500),
            "missing mate classification": lambda r: r["candidates"][0].pop("mate_in_plies"),
            "zero mate": lambda r: r["candidates"][0].update(mate_in_plies=0),
            "mate already completed by chosen move": lambda r: r["candidates"][0].update(mate_in_plies=1),
            "negative mate with no remaining plies": lambda r: r["candidates"][0].update(mate_in_plies=-1),
            "noninteger mate": lambda r: r["candidates"][0].update(mate_in_plies=2.5),
            "hypothetical metadata": lambda r: r["query"].update(after=["b8c6"]),
            "wrong request FEN": lambda r: r["query"].update(fen=game.START_FEN),
            "duplicate selected roots": lambda r: r["candidates"].append(deepcopy(r["candidates"][0])),
        }
        for label, change in changes.items():
            with self.subTest(case=label):
                state = self.state()
                result = self.result(state)
                change(result)
                self.save(state, result)
                self.assertIsNone(self.evaluate(state))

    def test_missing_malformed_or_oversize_files_are_graceful_and_null_is_not_cached(self):
        state = self.state()
        path = self.save(state, None)
        self.assertIsNone(self.evaluate(state))
        for content in (b"{", b"[]", b"\xff", b"[" * 1200 + b"]" * 1200, b" " * (MAX_RESULT_BYTES + 1)):
            path.write_bytes(content)
            self.assertIsNone(self.evaluate(state))
        path.write_text(json.dumps(self.result(state)), encoding="utf-8")
        self.assertEqual(self.evaluate(state)["score_pawns"], -0.12)
        before = deepcopy(state)
        self.evaluate(state)
        self.assertEqual(state, before)

    def test_other_game_absolute_traversal_and_nonresult_paths_are_rejected(self):
        state = self.state()
        valid = self.save(state, self.result(state))
        relative = state["queries"][0]["path"]
        for raw in (str(valid.resolve()), "../" + relative,
                    relative.replace(state["id"], "f" * 32), relative.replace(".result.json", ".request.json"),
                    "games/" + state["id"] + "/queries/../queries/0.result.json", "C:/elsewhere/0.result.json"):
            with self.subTest(path=raw):
                state["queries"][0]["path"] = raw
                self.assertIsNone(self.evaluate(state))
        state["queries"][0]["path"] = relative.replace("/", "\\")
        self.assertEqual(self.evaluate(state)["score_pawns"], -0.12)
        state["queries"][0]["ply"] = 1
        self.assertIsNone(self.evaluate(state))

    def test_symlink_cannot_read_outside_current_game_query_directory(self):
        state = self.state()
        path = self.save(state, None)
        outside = self.config.data_dir / "outside.result.json"
        outside.write_text(json.dumps(self.result(state)), encoding="utf-8")
        try:
            path.symlink_to(outside)
        except OSError:
            self.skipTest("Creating symlinks is unavailable for this Windows account")
        self.assertIsNone(self.evaluate(state))

    def test_public_api_enriches_create_get_action_and_duplicate_without_blocking_moves(self):
        app = create_app(self.config)
        with TestClient(app) as client:
            client.headers["Origin"] = self.config.origin
            registered = client.post("/api/auth/register", json={"name": "Evaluation test"})
            client.headers["X-CSRF-Token"] = registered.json()["csrf_token"]
            initial = client.post("/api/games", json={"side": "white"}).json()
            self.assertIsNone(initial["last_astra_evaluation"])
            game_id = initial["id"]

            def human(action, **fields):
                version = app.state.store.get(game_id)["version"]
                body = {"action": action, "version": version, "request_id": uuid.uuid4().hex, **fields}
                response = client.post(f"/api/games/{game_id}/actions", json=body)
                self.assertEqual(response.status_code, 200, response.text)
                return response, body

            human("move", move="e2e4")
            state = app.state.store.mutate(game_id, lambda s: game.apply_move(s, "e7e5", "astra"))
            path = self.save(state, self.result(state, 42))
            app.state.store.mutate(game_id, lambda s: s.update(queries=state["queries"]))
            snapshot = client.get(f"/api/games/{game_id}").json()
            self.assertEqual(snapshot["last_astra_evaluation"]["score_pawns"], 0.42)
            response, body = human("move", move="g1f3")
            self.assertEqual(response.json()["last_astra_evaluation"]["score_pawns"], 0.42)
            retried = client.post(f"/api/games/{game_id}/actions", json=body)
            self.assertEqual(retried.json()["last_astra_evaluation"]["score_pawns"], 0.42)
            path.write_text("malformed result", encoding="utf-8")
            resigned, _ = human("resign")
            self.assertIsNone(resigned.json()["last_astra_evaluation"])
            self.assertEqual(resigned.json()["status"], "finished")


if __name__ == "__main__":
    unittest.main()
