"""HTTP/persistence/supervisor integration tests; no model, mail or real search."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, closing
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import AsyncMock
from urllib.parse import urlsplit
import uuid

from fastapi.testclient import TestClient

from astra_web.app import create_app
from astra_web import chess_game as game
from astra_web.config import Config
from astra_web.process_lock import ProcessLock


class FakePlayers:
    def __init__(self, behavior=None, fail_close=False):
        self.behavior, self.fail_close = behavior, fail_close
        self.calls, self.closed = [], []
        self.started = threading.Event()

    def __call__(self, config):
        owner = self

        class Player:
            async def run(self, game_id, snapshot, tool, emit, thread_id=None):
                owner.calls.append((game_id, snapshot, thread_id))
                owner.started.set()
                if owner.behavior:
                    return await owner.behavior(game_id, snapshot, tool, emit)
                await emit("Hello from the test player.")
                return {"usage_tokens": 11}

            async def close(self):
                owner.closed.append(True)
                if owner.fail_close:
                    raise RuntimeError("test close failure")

        return Player()


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        directory = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.config = Config(data_dir=Path(directory), origin="http://testserver",
                             player_mode="disabled", secure_cookies=False, smtp_host="", smtp_from="")
        self.addCleanup(self.stack.close)

    def start(self, players=None):
        self.app = create_app(self.config, player_factory=players)
        self.client = self.stack.enter_context(TestClient(self.app))
        return self.client

    def register(self, name="Player", password=None, email=None, client=None):
        client = client or self.client
        body = {"name": name}
        if password:
            body["password"] = password
        if email:
            body["email"] = email
        response = client.post("/api/auth/register", json=body, headers={"Origin": self.config.origin})
        self.assertEqual(response.status_code, 200, response.text)
        client.headers.update({"Origin": self.config.origin, "X-CSRF-Token": response.json()["csrf_token"]})
        return response.json()["user"]

    def new_game(self, side="white", client=None):
        response = (client or self.client).post("/api/games", json={"side": side})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def action(self, game_id, action, **fields):
        version = fields.pop("version", None)
        if version is None:
            version = self.app.state.store.get(game_id)["version"]
        payload = {"action": action, "version": version, "request_id": uuid.uuid4().hex, **fields}
        return self.client.post(f"/api/games/{game_id}/actions", json=payload)

    def wait_idle(self, game_id, timeout=4):
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            if game_id not in self.app.state.supervisor.tasks:
                return self.app.state.store.get(game_id)
            time.sleep(0.01)
        self.fail("Fake worker did not finish in time")

    def test_server_authority_version_conflict_and_idempotent_retries(self):
        self.start()
        self.register()
        state = self.new_game()
        game_id = state["id"]
        for move in ("e2e5", "e7e5", None, ["e2e4"]):
            bad = self.action(game_id, "move", move=move)
            self.assertEqual(bad.status_code, 400)
            self.assertEqual(self.app.state.store.get(game_id)["moves"], [])
        payload = {"action": "move", "move": "e2e4", "version": state["version"], "request_id": "durable-request-1"}
        accepted = self.client.post(f"/api/games/{game_id}/actions", json=payload)
        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.assertEqual(accepted.json()["moves"][0]["san"], "e4")
        version = accepted.json()["version"]
        retry = self.client.post(f"/api/games/{game_id}/actions", json=payload)
        self.assertEqual(retry.status_code, 200, retry.text)
        self.assertEqual(retry.json()["version"], version, "A retry must not queue another worker or change state")
        self.assertEqual(len(retry.json()["moves"]), 1)
        changed = self.client.post(f"/api/games/{game_id}/actions", json={**payload, "move": "d2d4"})
        self.assertEqual(changed.status_code, 409)
        stale = self.action(game_id, "message", text="Old version", version=0)
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(self.action(game_id, "move", move="d2d4").status_code, 400)
        self.assertEqual(self.action(game_id, "move", move="e7e5", actor="astra").status_code, 400)

    def test_boundary_requires_origin_csrf_json_host_and_size_limit(self):
        self.start()
        self.register()
        endpoint = "/api/games"
        self.assertEqual(self.client.post(endpoint, json={"side": "white"}, headers={"Origin": "https://evil.invalid"}).status_code, 403)
        self.assertEqual(self.client.post(endpoint, json={"side": "white"}, headers={"X-CSRF-Token": "wrong"}).status_code, 403)
        self.assertEqual(self.client.post(endpoint, content="side=white", headers={"Content-Type": "text/plain"}).status_code, 415)
        self.assertEqual(self.client.post(endpoint, content="x" * 16385, headers={"Content-Type": "application/json"}).status_code, 413)
        self.assertEqual(self.client.post(endpoint, content="{", headers={"Content-Type": "application/json"}).status_code, 400)
        self.assertEqual(self.client.post(endpoint, json=[]).status_code, 400)
        self.assertEqual(self.client.get("/health", headers={"Host": "evil.invalid"}).status_code, 400)
        response = self.client.get("/api/auth/me")
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertIn("frame-ancestors 'none'", response.headers["content-security-policy"])
        self.assertEqual(self.client.get("/api/games").json(), {"games": []})

    def test_owner_isolation_and_authenticated_notes_do_not_escape(self):
        self.start()
        owner = self.register(password="password for player", email="private@example.org")
        self.client.put("/api/auth/memory", json={"enabled": True, "text": "PRIVATE MEMORY VALUE"})
        state = self.new_game()
        game_id = state["id"]
        self.app.state.store.mutate(game_id, lambda s: s.update(
            thread_id="PRIVATE THREAD", candidates=[{"private": "PRIVATE CANDIDATE"}],
            queries=[{"path": "PRIVATE QUERY"}], decisions=[{"note": "PRIVATE DECISION"}]))
        private = self.client.get(f"/api/games/{game_id}").text
        for secret in (owner["id"], "private@example.org", "PRIVATE MEMORY", "PRIVATE THREAD", "PRIVATE QUERY", "PRIVATE CANDIDATE", "PRIVATE DECISION"):
            self.assertNotIn(secret, private)
        # Another browser shares the running server; it must not enter lifespan again.
        with closing(TestClient(self.app)) as other:
            self.register("Someone else", client=other)
            self.assertEqual(other.get("/api/games").json(), {"games": []})
            for suffix in ("", "/pgn"):
                self.assertEqual(other.get(f"/api/games/{game_id}{suffix}").status_code, 404)
            self.assertEqual(other.post(f"/api/games/{game_id}/actions", json={"action": "resign", "version": 0, "request_id": "intruder-123"}).status_code, 404)
            self.assertEqual(other.post(f"/api/games/{game_id}/share", json={"include_commentary": True}).status_code, 404)
            self.assertEqual(other.delete(f"/api/games/{game_id}/share").status_code, 404)

    def test_completed_share_is_opt_in_minimal_and_revocable(self):
        self.start()
        self.register(password="password for player", email="private@example.org")
        self.client.put("/api/auth/memory", json={"enabled": True, "text": "PRIVATE MEMORY VALUE"})
        state = self.new_game()
        game_id = state["id"]
        self.assertEqual(self.client.post(f"/api/games/{game_id}/share", json={"include_commentary": True}).status_code, 400)
        self.action(game_id, "message", text="A public comment only with my permission.")
        self.action(game_id, "resign")
        self.app.state.store.mutate(game_id, lambda s: s.update(thread_id="PRIVATE THREAD", queries=[{"path": "PRIVATE QUERY"}], decisions=[{"note": "PRIVATE DECISION"}]))
        self.assertEqual(self.client.post(f"/api/games/{game_id}/share", json={}).status_code, 400)
        shared = self.client.post(f"/api/games/{game_id}/share", json={"include_commentary": False}).json()
        first_token = urlsplit(shared["url"]).path.rsplit("/", 1)[1]
        with closing(TestClient(self.app)) as visitor:
            public = visitor.get(f"/api/replays/{first_token}")
            self.assertEqual(public.status_code, 200)
            self.assertEqual(public.json()["messages"], [])
            for secret in ("PRIVATE", "private@example.org", "user_id", "thread_id", "queries", "decisions", "candidates", "clock_events"):
                self.assertNotIn(secret, public.text)
            self.assertEqual(public.json()["result"], "0-1")
            self.assertEqual(visitor.get(f"/replay/{first_token}").status_code, 200)
            second = self.client.post(f"/api/games/{game_id}/share", json={"include_commentary": True}).json()
            second_token = urlsplit(second["url"]).path.rsplit("/", 1)[1]
            self.assertEqual(visitor.get(f"/api/replays/{first_token}").status_code, 404)
            self.assertEqual(visitor.get(f"/api/replays/{second_token}").json()["messages"][0]["text"], "A public comment only with my permission.")
            self.assertEqual(self.client.delete(f"/api/games/{game_id}/share").status_code, 200)
            self.assertEqual(visitor.get(f"/api/replays/{second_token}").status_code, 404)
            self.assertEqual(visitor.get(f"/replay/{second_token}").status_code, 404)
        pgn = self.client.get(f"/api/games/{game_id}/pgn")
        self.assertEqual(pgn.status_code, 200)
        self.assertIn('[Result "0-1"]', pgn.text)

    def test_draw_offer_accept_decline_and_move_declines_opponent_offer(self):
        self.start()
        self.register()
        state = self.new_game()
        game_id = state["id"]
        self.assertEqual(self.action(game_id, "accept_draw").status_code, 400)
        self.assertEqual(self.action(game_id, "offer_draw").json()["draw_offer"], "human")
        self.assertEqual(self.action(game_id, "offer_draw").status_code, 400)
        self.assertEqual(self.action(game_id, "move", move="e2e4").json()["draw_offer"], "human")
        self.app.state.store.mutate(game_id, lambda s: game.apply_move(s, "e7e5", "astra"))
        self.assertIsNone(self.app.state.store.get(game_id)["draw_offer"])
        self.app.state.store.mutate(game_id, lambda s: s.update(draw_offer="astra"))
        self.assertIsNone(self.action(game_id, "decline_draw").json()["draw_offer"])
        self.app.state.store.mutate(game_id, lambda s: s.update(draw_offer="astra"))
        accepted = self.action(game_id, "accept_draw").json()
        self.assertEqual((accepted["status"], accepted["result"], accepted["termination"]), ("finished", "1/2-1/2", "agreement"))
        self.assertEqual(self.action(game_id, "move", move="g1f3").status_code, 400)

    def test_rules_special_moves_capture_records_and_automatic_endings(self):
        self.start()
        user = self.register()
        cases = [
            ("4k3/8/8/8/8/8/8/4K2R w K - 0 1", "e1g1", "O-O", "."),
            ("4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1", "e5d6", "exd6", "p"),
            ("7k/P7/8/8/8/8/8/7K w - - 0 1", "a7a8n", "a8=N", "."),
        ]
        for fen, move, san, captured in cases:
            with self.subTest(move=move):
                state = game.new_game(user, "white", self.config)
                state["fen"] = fen
                if move == "a7a8n":
                    with self.assertRaises(ValueError):
                        game.apply_move(state, "a7a8", "human")
                game.apply_move(state, move, "human")
                self.assertEqual(state["moves"][-1]["san"], san)
                self.assertEqual(state["moves"][-1]["captured"], captured)
                if move == "a7a8n":
                    self.assertEqual(state["termination"], "insufficient_material")
        mate = game.new_game(user, "black", self.config)
        for move, actor in (("f2f3", "astra"), ("e7e5", "human"), ("g2g4", "astra"), ("d8h4", "human")):
            game.apply_move(mate, move, actor)
        self.assertEqual((mate["result"], mate["termination"]), ("0-1", "checkmate"))
        canonical = game.new_game(user, "white", self.config)
        game.apply_move(canonical, " e2e4 ", "human")
        self.assertEqual(canonical["moves"][0]["uci"], "e2e4")

    def test_repetition_claim_and_classical_credit_only_after_verified_moves(self):
        self.start()
        user = self.register()
        state = game.new_game(user, "white", self.config)
        for move, actor in [("g1f3", "human"), ("g8f6", "astra"), ("f3g1", "human"), ("f6g8", "astra")] * 2:
            game.apply_move(state, move, actor)
        self.assertTrue(game.claimable(state))
        self.app.state.store.create(state)
        response = self.action(state["id"], "claim_draw")
        self.assertEqual(response.json()["termination"], "draw_claim")
        self.assertEqual(game.clock(game.new_game(user, "white", self.config))["earned_seconds"], 5400)
        state.update(own_moves=39, active_started=None, clock_used=0)
        self.assertEqual(game.clock(state)["earned_seconds"], 6570)
        state["own_moves"] = 40
        self.assertEqual(game.clock(state)["earned_seconds"], 8400)

    def test_duplicate_message_never_schedules_a_second_worker(self):
        release = threading.Event()

        async def respond(game_id, snapshot, tool, emit):
            while not release.is_set():
                await asyncio.sleep(0.005)
            await emit("One answer.")
            return {"usage_tokens": 9}

        players = FakePlayers(respond)
        self.start(players)
        self.register()
        state = self.new_game()
        game_id = state["id"]
        payload = {"action": "message", "text": "Hello", "version": state["version"], "request_id": "message-retry-1"}
        first = self.client.post(f"/api/games/{game_id}/actions", json=payload)
        self.assertEqual(first.status_code, 200)
        self.assertTrue(players.started.wait(2))
        self.assertEqual(self.client.post(f"/api/games/{game_id}/actions", json=payload).status_code, 200)
        release.set()
        done = self.wait_idle(game_id)
        self.assertEqual(len(players.calls), 1)
        self.assertEqual(len(players.closed), 1)
        self.assertEqual([m["text"] for m in done["messages"]], ["Hello", "One answer."])
        self.assertEqual(self.client.post(f"/api/games/{game_id}/actions", json=payload).status_code, 200)
        self.wait_idle(game_id)
        self.assertEqual(len(players.calls), 1)
        self.assertEqual(done["clock_used"], 0, "Conversation during the human turn must not debit Astra's chess clock")

    def test_supervisor_requires_candidate_and_query_and_resumes_private_context(self):
        rejected = []

        async def choose(game_id, snapshot, tool, emit):
            move = "e2e4" if snapshot["ply"] == 0 else "g1f3"
            try:
                await tool("chess_choose", {"action": "move", "move": move, "note": "Too soon"})
            except ValueError as error:
                rejected.append(str(error))
            await tool("_thread", {"thread_id": "saved-test-thread"})
            await tool("chess_candidate", {"move": move, "concern": "Check the center response."})
            await tool("chess_query", {"seconds": 1})
            await asyncio.sleep(0.01)
            await tool("chess_choose", {"action": "move", "move": move, "note": "Reviewed the supplied query."})
            await emit("I reviewed and played " + move + ".")
            return {"usage_tokens": 17}

        players = FakePlayers(choose)
        self.start(players)
        user = self.register(password="password for player")
        self.client.put("/api/auth/memory", json={"enabled": True, "text": "Opted-in private note."})
        self.app.state.supervisor._query = AsyncMock(return_value=({"test": "bounded result"}, "games/fake/result.json"))
        state = self.new_game("black")
        done = self.wait_idle(state["id"])
        self.assertEqual(len(rejected), 1)
        self.assertEqual(done["moves"][0]["uci"], "e2e4")
        self.assertEqual(done["worker"]["state"], "idle")
        self.assertEqual(done["own_moves"], 1)
        self.assertGreater(done["clock_used"], 0)
        self.assertIsNone(done["active_started"])
        self.assertEqual(done["thread_id"], "saved-test-thread")
        self.assertEqual(players.calls[0][1]["memory"], "Opted-in private note.")
        self.assertNotIn("Opted-in private note.", self.client.get(f'/api/games/{state["id"]}').text)
        self.assertEqual(len(players.closed), 1)
        with self.app.state.store.connection() as db:
            budget = db.execute("SELECT tokens,reserved FROM budget").fetchone()
        self.assertEqual(tuple(budget), (17, 0))
        # A later process receives the saved conversation ID and current memory opt-in.
        self.client.put("/api/auth/memory", json={"enabled": False, "text": "Opted-in private note."})
        self.assertEqual(self.action(state["id"], "move", move="e7e5").status_code, 200)
        resumed = self.wait_idle(state["id"])
        self.assertEqual([m["uci"] for m in resumed["moves"]], ["e2e4", "e7e5", "g1f3"])
        self.assertEqual(players.calls[1][2], "saved-test-thread")
        self.assertEqual(players.calls[1][1]["memory"], "")
        self.assertEqual(len(players.closed), 2)

    def test_close_failure_still_settles_clock_and_resource_reservation(self):
        async def interrupted(game_id, snapshot, tool, emit):
            await asyncio.sleep(0.01)
            raise RuntimeError("Simulated player interruption")

        players = FakePlayers(interrupted, fail_close=True)
        self.start(players)
        self.register()
        state = self.new_game("black")
        done = self.wait_idle(state["id"])
        self.assertEqual(done["worker"]["state"], "error")
        self.assertIsNone(done["active_started"])
        self.assertGreater(done["clock_used"], 0)
        with self.app.state.store.connection() as db:
            budget = db.execute("SELECT tokens,reserved FROM budget").fetchone()
        self.assertEqual(tuple(budget), (self.config.max_turn_tokens, 0))
        self.assertNotIn("Simulated player", self.client.get(f'/api/games/{state["id"]}').text)

    def test_resignation_cancels_worker_and_settles_without_own_move_credit(self):
        async def waiting(game_id, snapshot, tool, emit):
            await asyncio.Event().wait()

        players = FakePlayers(waiting)
        self.start(players)
        self.register()
        state = self.new_game("black")
        self.assertTrue(players.started.wait(2))
        resigned = self.action(state["id"], "resign")
        self.assertEqual(resigned.status_code, 200, resigned.text)
        done = self.wait_idle(state["id"])
        self.assertEqual(done["status"], "finished")
        self.assertIsNone(done["active_started"])
        self.assertEqual(done["own_moves"], 0)
        self.assertEqual(len(players.closed), 1)
        with self.app.state.store.connection() as db:
            reserved = db.execute("SELECT reserved FROM budget").fetchone()[0]
        self.assertEqual(reserved, 0)

    def test_daily_budget_reservation_is_atomic_and_crash_recovery_conservative(self):
        self.config.max_turn_tokens = 60
        self.config.max_daily_tokens = 100
        self.start()
        store = self.app.state.store

        def reserve():
            try:
                return store.reserve()
            except ValueError:
                return None

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: reserve(), range(2)))
        self.assertEqual(sum(r is not None for r in results), 1)
        store.recover_reservations()
        store.recover_reservations()
        with store.connection() as db:
            budget = db.execute("SELECT turns,tokens,reserved FROM budget").fetchone()
        self.assertEqual(tuple(budget), (1, 60, 0))
        with self.assertRaises(ValueError):
            store.reserve()

    def test_deadline_cancels_player_and_charges_interrupted_turn(self):
        async def waiting(game_id, snapshot, tool, emit):
            await asyncio.Event().wait()

        self.config.ordinary_seconds = 0.05
        self.config.critical_seconds = 0.1
        players = FakePlayers(waiting)
        self.start(players)
        self.register()
        state = self.new_game("black")
        done = self.wait_idle(state["id"])
        self.assertEqual(done["worker"]["state"], "error")
        self.assertEqual(done["moves"], [])
        self.assertEqual(len(players.closed), 1)
        self.assertIsNone(done["active_started"])
        self.assertGreaterEqual(done["clock_used"], 0.05)
        with self.app.state.store.connection() as db:
            budget = db.execute("SELECT tokens,reserved FROM budget").fetchone()
        self.assertEqual(tuple(budget), (self.config.max_turn_tokens, 0))

    def test_queued_game_has_no_clock_or_token_charge_until_admitted(self):
        async def waiting(game_id, snapshot, tool, emit):
            await asyncio.Event().wait()

        self.config.max_workers = 1
        players = FakePlayers(waiting)
        self.start(players)
        self.register()
        first = self.new_game("black")
        self.assertTrue(players.started.wait(2))
        second = self.new_game("black")
        queued = self.app.state.store.get(second["id"])
        self.assertEqual(queued["worker"]["state"], "queued")
        self.assertIsNone(queued["active_started"])
        self.assertEqual(game.clock(queued)["used_seconds"], 0)
        self.assertEqual(len(players.calls), 1)
        with self.app.state.store.connection() as db:
            budget = db.execute("SELECT turns,reserved FROM budget").fetchone()
        self.assertEqual(tuple(budget), (1, self.config.max_turn_tokens))
        self.assertEqual(self.action(first["id"], "resign").status_code, 200)
        until = time.monotonic() + 2
        while len(players.calls) < 2 and time.monotonic() < until:
            time.sleep(0.01)
        self.assertEqual(len(players.calls), 2)
        self.assertEqual(self.action(second["id"], "resign").status_code, 200)
        self.assertEqual(len(players.closed), 2)

    def test_inactivity_suspends_and_resume_preserves_board_messages_and_clock(self):
        self.start()
        self.register()
        state = self.new_game()
        game_id = state["id"]
        self.action(game_id, "move", move="e2e4")
        self.action(game_id, "message", text="Back tomorrow.")
        self.app.state.store.mutate(game_id, lambda s: s.update(last_human_activity=time.time() - 36 * 3600 - 1, clock_used=42.0))
        before = self.app.state.store.get(game_id)
        self.app.state.supervisor.suspend_inactive()
        suspended = self.app.state.store.get(game_id)
        self.assertEqual(suspended["status"], "suspended")
        self.assertEqual(self.action(game_id, "message", text="Not resumed").status_code, 400)
        resumed = self.action(game_id, "resume")
        self.assertEqual(resumed.status_code, 200, resumed.text)
        after = self.app.state.store.get(game_id)
        for field in ("fen", "moves", "messages", "clock_used"):
            self.assertEqual(before[field], after[field])
        self.assertEqual(after["status"], "active")

    def test_restart_caps_uncertain_clock_charge_and_preserves_saved_game(self):
        # Construct evidence before entering lifespan to simulate an interrupted process.
        app = create_app(self.config)
        token = app.state.identity.register("Player")
        user = app.state.identity.user_for_token(token)
        state = game.new_game(user, "black", self.config)
        state.update(active_started=time.time() - 1000, active_deadline=time.time() - 970,
                     worker={"state": "thinking", "message": "Before restart"})
        app.state.store.create(state)
        app.state.store.reserve()
        with TestClient(app):
            recovered = app.state.store.get(state["id"])
            self.assertIsNone(recovered["active_started"])
            self.assertAlmostEqual(recovered["clock_used"], 30, places=2)
            self.assertEqual(recovered["worker"]["state"], "error")
            self.assertEqual(recovered["fen"], game.START_FEN)
            self.assertEqual(app.state.supervisor.tasks, {})
            with app.state.store.connection() as db:
                budget = db.execute("SELECT tokens,reserved FROM budget").fetchone()
            self.assertEqual(tuple(budget), (self.config.max_turn_tokens, 0))

    def test_singleton_lock_rejects_second_owner_and_releases(self):
        lock_path = self.config.data_dir / "exclusive.lock"
        with ProcessLock(lock_path):
            with self.assertRaises(RuntimeError):
                with ProcessLock(lock_path):
                    self.fail("Second service acquired the same lock")
        with ProcessLock(lock_path):
            pass


if __name__ == "__main__":
    unittest.main()
