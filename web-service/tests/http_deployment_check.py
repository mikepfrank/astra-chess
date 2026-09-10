"""Explicit HTTP deployment check: creates a QA guest and three resigned games.

Does not submit a legal move or chat message, so no model action is scheduled.
Use --connect-local only on the deployment host: TLS still verifies the public
hostname, while its connections go to the local Caddy listener.
"""
import argparse
import json
import socket
from urllib.parse import urlsplit
import uuid

import httpx


def check(origin):
    with httpx.Client(base_url=origin, timeout=15, trust_env=False) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "content-security-policy" in page.headers
        registration = client.post("/api/auth/register",
            json={"name": "Deployment QA " + uuid.uuid4().hex[:8]}, headers={"Origin": origin})
        assert registration.status_code == 200, registration.status_code
        cookie = registration.headers["set-cookie"].lower()
        assert "secure" in cookie and "httponly" in cookie and "samesite" in cookie
        client.headers.update({"Origin": origin, "X-CSRF-Token": registration.json()["csrf_token"]})
        games = []
        for _ in range(3):
            response = client.post("/api/games", json={"side": "white"})
            assert response.status_code == 201, response.status_code
            state = response.json()
            assert not state["moves"] and state["worker"]["state"] == "idle"
            games.append(state)
        assert len({game["id"] for game in games}) == 3
        assert client.post("/api/games", json={"side": "white"}).status_code == 400
        for state in games:
            url = "/api/games/" + state["id"]
            rejected = client.post(url + "/actions", json={"action": "move", "move": "e2e5",
                "version": state["version"], "request_id": uuid.uuid4().hex})
            assert rejected.status_code == 400
            loaded = client.get(url).json()
            assert not loaded["moves"] and loaded["status"] == "active"
            ended = client.post(url + "/actions", json={"action": "resign",
                "version": loaded["version"], "request_id": uuid.uuid4().hex})
            assert ended.status_code == 200 and ended.json()["status"] == "finished"
        listing = client.get("/api/games").json()["games"]
        assert len(listing) == 3 and all(game["status"] == "finished" for game in listing)
        blocked = client.post("/api/games", json={"side": "white"}, headers={"Origin": "https://example.invalid"})
        assert blocked.status_code == 403
    return {"https_certificate_valid": True, "security_headers_present": True,
            "secure_session_cookie": True, "three_distinct_games": True,
            "fourth_unfinished_game_rejected": True, "illegal_moves_rejected": True,
            "games_preserved_on_reload": True, "resignation_persisted": True,
            "foreign_origin_rejected": True, "model_actions_started": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--live-http", action="store_true", required=True,
                        help="Authorize creation of the QA account and game records")
    parser.add_argument("--connect-local", action="store_true")
    args = parser.parse_args()
    origin = args.origin.rstrip("/")
    parts = urlsplit(origin)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.path or parts.query or parts.fragment:
        parser.error("Provide an HTTPS origin without a path or credentials.")
    original = socket.getaddrinfo
    if args.connect_local:
        def resolve(host, port, *values, **options):
            return original("127.0.0.1" if host == parts.hostname else host, port, *values, **options)
        socket.getaddrinfo = resolve
    try:
        print(json.dumps(check(origin), indent=2))
    finally:
        socket.getaddrinfo = original


if __name__ == "__main__":
    main()
