"""Operator-only paid HTTP integration check; never collected by unittest.

Requires --live and an already-running local server. Creates one private guest
game, makes one human move, sends one chat, then resigns and checks replay
sharing/revocation. Existing browser sessions and player accounts are untouched.
"""
import argparse
import json
import re
import time
from urllib.parse import urlsplit
import uuid

import httpx


WAIT_SECONDS = 300
POLL_SECONDS = 2
CHAT = "How does the tactical engine help you choose a move?"
WORKER_STATES = {"idle", "queued", "thinking", "calculating", "compacting", "error", "disabled"}


def loopback_origin(value):
    if not re.fullmatch(r"http://127\.0\.0\.1(?::[0-9]{1,5})?/?", value):
        raise argparse.ArgumentTypeError("Use an http://127.0.0.1 origin with an optional port.")
    try:
        port = urlsplit(value).port
    except ValueError:
        raise argparse.ArgumentTypeError("Choose a valid local port.") from None
    if port is not None and not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("Choose a valid local port.")
    return value.rstrip("/")


class CheckFailure(Exception):
    def __init__(self, code, status=None):
        self.code, self.status = code, status
        super().__init__(code)


def request(client, method, path, *, expected=200, timeout=15, **kwargs):
    try:
        response = client.request(method, path, timeout=timeout, **kwargs)
    except httpx.HTTPError:
        raise CheckFailure("connection_failed") from None
    if response.status_code != expected:
        raise CheckFailure("unexpected_http_status", response.status_code)
    return response


def json_request(client, method, path, **kwargs):
    response = request(client, method, path, **kwargs)
    try:
        data = response.json()
    except ValueError:
        raise CheckFailure("invalid_json_response") from None
    if not isinstance(data, dict):
        raise CheckFailure("unexpected_response_shape")
    return data


def action(client, game_id, name, **fields):
    # Each action has one fresh version and one request ID; no automatic retry.
    current = json_request(client, "GET", f"/api/games/{game_id}")
    version = current.get("version")
    if type(version) is not int:
        raise CheckFailure("missing_board_version")
    return json_request(client, "POST", f"/api/games/{game_id}/actions", json={
        "action": name, "version": version, "request_id": uuid.uuid4().hex, **fields})


def astra_messages(state):
    return sum(message.get("author") == "astra" for message in state.get("messages", []))


def wait_for_reply(client, game_id, ready):
    deadline = time.monotonic() + WAIT_SECONDS
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise CheckFailure("reply_deadline_reached")
        state = json_request(client, "GET", f"/api/games/{game_id}", timeout=min(15, remaining))
        worker = state.get("worker", {}).get("state")
        if worker in {"error", "disabled"}:
            raise CheckFailure("worker_unavailable_or_interrupted")
        if state.get("status") != "active":
            raise CheckFailure("game_ended_before_check_completed")
        if worker == "idle":
            if ready(state):
                return state
            raise CheckFailure("worker_finished_without_expected_reply")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise CheckFailure("reply_deadline_reached")
        time.sleep(min(POLL_SECONDS, remaining))


def report(stage, state=None, **fields):
    output = {"stage": stage, **fields}
    if state is not None:
        moves = [move.get("uci", "") for move in state.get("moves", [])]
        output.update(
            state=state.get("status") if state.get("status") in {"active", "suspended", "finished"} else "unknown",
            worker=state.get("worker", {}).get("state") if state.get("worker", {}).get("state") in WORKER_STATES else "unknown",
            ply=len(moves), messages=len(state.get("messages", [])),
            moves=[move for move in moves[:2] if isinstance(move, str) and re.fullmatch(r"[a-h][1-8][a-h][1-8][qrbn]?", move)],
        )
    print(json.dumps(output, separators=(",", ":")), flush=True)


def run(args):
    stage, game_id, shared = "configuration", None, False
    result = 1
    # Neither client loads browser cookies, environment credentials, or proxies.
    with httpx.Client(base_url=args.origin, headers={"Origin": args.origin},
                      trust_env=False, follow_redirects=False) as client, \
            httpx.Client(base_url=args.origin, trust_env=False, follow_redirects=False) as visitor:
        try:
            config = json_request(client, "GET", "/api/config")
            if not config.get("player_available") or config.get("player_mode") != "codex":
                raise CheckFailure("live_player_not_configured")
            stage = "guest_registration"
            identity = json_request(client, "POST", "/api/auth/register", json={"name": "HTTP-check-" + uuid.uuid4().hex[:20]})
            csrf = identity.get("csrf_token")
            if not isinstance(csrf, str) or not re.fullmatch(r"[A-Za-z0-9_-]{20,128}", csrf):
                raise CheckFailure("missing_session_verification")
            client.headers["X-CSRF-Token"] = csrf
            stage = "game_creation"
            state = json_request(client, "POST", "/api/games", expected=201, json={"side": "white"})
            candidate_id = state.get("id")
            if not isinstance(candidate_id, str) or not re.fullmatch(r"[a-f0-9]{32}", candidate_id):
                raise CheckFailure("invalid_game_identifier")
            game_id = candidate_id
            stage = "move_reply"
            action(client, game_id, "move", move="e2e4")
            report(stage, status="waiting")
            state = wait_for_reply(client, game_id, lambda s: len(s.get("moves", [])) == 2)
            if (state["moves"][0].get("uci") != "e2e4" or state["moves"][0].get("actor") != "human"
                    or state["moves"][1].get("actor") != "astra"):
                raise CheckFailure("unexpected_move_sequence")
            report(stage, state, status="passed")
            stage = "chat_reply"
            previous = astra_messages(state)
            action(client, game_id, "message", text=CHAT)
            report(stage, status="waiting")
            state = wait_for_reply(client, game_id, lambda s: astra_messages(s) > previous)
            if len(state["moves"]) != 2:
                raise CheckFailure("chat_changed_board")
            report(stage, state, status="passed")
            stage = "resignation"
            state = action(client, game_id, "resign")
            if state.get("status") != "finished" or state.get("result") != "0-1":
                raise CheckFailure("resignation_not_recorded")
            stage = "replay_share"
            share = json_request(client, "POST", f"/api/games/{game_id}/share", json={"include_commentary": args.include_commentary})
            shared = True
            parsed = urlsplit(share.get("url", ""))
            expected_origin = urlsplit(args.origin)
            match = re.fullmatch(r"/replay/([A-Za-z0-9_-]{20,100})", parsed.path)
            if (parsed.scheme != expected_origin.scheme or parsed.netloc != expected_origin.netloc
                    or parsed.query or parsed.fragment or not match):
                raise CheckFailure("invalid_replay_location")
            token = match.group(1)
            replay = json_request(visitor, "GET", "/api/replays/" + token)
            request(visitor, "GET", "/replay/" + token)
            expected_count = len(state["messages"]) if args.include_commentary else 0
            if replay.get("result") != "0-1" or len(replay.get("moves", [])) != 2 or len(replay.get("messages", [])) != expected_count:
                raise CheckFailure("replay_content_mismatch")
            stage = "replay_revocation"
            json_request(client, "DELETE", f"/api/games/{game_id}/share")
            request(visitor, "GET", "/api/replays/" + token, expected=404)
            request(visitor, "GET", "/replay/" + token, expected=404)
            shared = False
            report("complete", state, status="passed", replay="revoked")
            result = 0
        except CheckFailure as error:
            report(stage, status="failed", reason=error.code, http_status=error.status)
            result = 1
        except KeyboardInterrupt:
            report(stage, status="cancelled")
            result = 130
        except Exception:
            # Never print exception text, response bodies, cookies, or transcripts.
            report(stage, status="failed", reason="unexpected_check_error")
            result = 1
        finally:
            if shared:
                try:
                    json_request(client, "DELETE", f"/api/games/{game_id}/share")
                    report("cleanup", replay="revoked")
                except Exception:
                    report("cleanup", replay="revocation_failed")
                    result = 1
            if game_id:
                try:
                    saved = json_request(client, "GET", f"/api/games/{game_id}")
                    if saved.get("status") == "active":
                        action(client, game_id, "resign")
                        report("cleanup", game_state="finished")
                except Exception:
                    report("cleanup", game_state="preserved_cleanup_incomplete")
                    result = 1
        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--live", action="store_true", required=True, help="Authorize one paid move reply and one paid chat reply")
    parser.add_argument("--origin", type=loopback_origin, default="http://127.0.0.1:8788", help="Already-running literal IPv4 loopback HTTP origin")
    parser.add_argument("--include-commentary", action="store_true", help="Include this test game's commentary in its briefly shared replay")
    raise SystemExit(run(parser.parse_args()))
