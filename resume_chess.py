"""Read-only recovery snapshot for the manual chess workflow. Never plays or searches.

Without arguments, list saved journals. With --game SLUG, reconcile durable
journal and clock records; the browser still needs a fresh observation.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from astra_engine.clock import clock_status
from astra_engine.rules import Position

ROOT = Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def engine_fingerprint(root=ROOT):
    digest = hashlib.sha256()
    for name in ("rules.py", "search.py", "diagnostics.py"):
        digest.update(name.encode("ascii") + b"\0" + (root / "astra_engine" / name).read_bytes())
    return digest.hexdigest()


def list_games(root=ROOT):
    games = []
    for path in sorted((root / "engine-games").glob("*/game.json")):
        try:
            game = read(path)
            games.append(dict(game=path.parent.name, round=game.get("round"),
                              white=game.get("white"), black=game.get("black"),
                              result=game.get("result"), verified_plies=len(game.get("uci", [])),
                              pending=bool(game.get("pending")),
                              clock_available=(path.parent / "clock.jsonl").is_file()))
        except (OSError, ValueError, TypeError) as error:
            games.append(dict(game=path.parent.name, error=str(error)))
    return {"games": games, "selection": "Choose the user-intended game explicitly; listing does not start or resume play."}


def snapshot(directory, root=ROOT):
    game = read(directory / "game.json")
    plies = len(game["uci"])
    if len(game["san"]) != plies or len(game["fens"]) != plies + 1:
        raise ValueError("Journal move/SAN/FEN lengths disagree; inspect original records")
    pos = Position.from_fen(game["fens"][-1])
    if plies:
        before = Position.from_fen(game["fens"][-2])
        move = before.parse_uci(game["uci"][-1])
        if before.play(move).fen() != pos.fen() or before.san(move) != game["san"][-1]:
            raise ValueError("Last verified move does not match its recorded SAN/FEN")
    clock_available = (directory / "clock.jsonl").is_file()
    status = clock_status(directory / "clock.jsonl") if clock_available else {
        "active_ply": None, "finished": None,
        "timing_uncertainty": ["No append-only ledger exists for this legacy journal; own-time balance is unavailable."]}
    pending = game.get("pending")
    issues = []
    finished = game["result"] != "*"
    if not clock_available and not finished:
        issues.append("Unfinished legacy journal has no append-only clock; review recovery before migrating or continuing")
    if clock_available and finished != status["finished"]:
        issues.append("Game result and clock completion disagree")
    if status["active_ply"] is not None and (status["active_ply"] != plies or pos.turn != 0):
        issues.append("Active clock ply disagrees with the verified White-to-move position")
    if pending and (finished or status["active_ply"] != plies):
        issues.append("Pending choice has no matching active own turn")
    turn = game.get("turns", [])[-1] if game.get("turns") else None
    if status["active_ply"] is not None and (not turn or turn["ply"] != status["active_ply"]):
        issues.append("Active clock has no matching journal turn")
    if issues:
        phase = "needs_record_reconciliation"
        next_action = "Inspect the original journal and ledger before any mutation; do not replay a guessed move."
    elif finished:
        phase = "finished"
        next_action = "Game is complete. Archive or inspect it; a new game needs the user's authorization."
    elif pending:
        phase = "pending_unverified"
        next_action = ("Observe the live board and move list before any click. Determine whether the chosen move was "
                       "accepted, remains unplayed, or is awaiting promotion. Verify an accepted move with real "
                       "timestamps; never submit it again based only on this snapshot.")
    elif status["active_ply"] is not None:
        phase = "own_turn_active"
        next_action = "Reconcile the live position, then continue this same turn and clock; do not call turn again."
    elif pos.turn == 1:
        phase = "awaiting_opponent_observation"
        next_action = "Read the live opponent reply. Start the next own turn using its first observation timestamp."
    else:
        phase = "own_turn_not_observed"
        next_action = "Observe the live board and start the own clock at that first observation before deliberating."
    pending_view = None
    if pending:
        move = pos.parse_uci(pending["uci"])
        pending_view = dict(uci=move.uci(), san=pos.san(move),
                            expected_fen_if_accepted=pos.play(move).fen(),
                            submitted_utc=pending.get("submitted_utc"),
                            verified=False)
    latest_query = None
    query_turn = next((item for item in reversed(game.get("turns", [])) if item.get("queries")), None)
    if query_turn:
        name = query_turn["queries"][-1]
        path = (root / name.replace("\\", "/")).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError("Query path leaves the repository")
        query = read(path)
        latest_query = dict(path=path.relative_to(root.resolve()).as_posix(), kind=query.get("kind"),
                            recorded_on_white_move=query_turn["move"],
                            start_fen=query.get("start_fen"),
                            starts_at_verified_position=query.get("start_fen") == pos.fen(),
                            completed_depth=query.get("completed_depth"), proof_status=query.get("proof_status"),
                            goal=query.get("goal"), source_sha256=query.get("engine", {}).get("source_sha256"),
                            candidates=[dict(move=c["root_move"], score_cp=c["score_cp"],
                                             mate_in_plies=c.get("mate_in_plies"), san=c["san"])
                                        for c in query.get("candidates", [])[:3]])
    fingerprint = engine_fingerprint(root)
    recorded_hash = latest_query["source_sha256"] if latest_query else None
    return dict(game=directory.name, result=game["result"], phase=phase, issues=issues,
                as_of_utc=datetime.now(timezone.utc).isoformat(),
                consistency_scope="Journal lengths, last verified move, pending legality and clock phase; not a full-game replay or live-board observation.",
                verified_plies=plies, last_verified_move=game["san"][-1] if plies else None,
                verified_fen=pos.fen(), board=pos.ascii(), pending=pending_view,
                turn={k: turn.get(k) for k in ("move", "ply", "observed_utc", "initial_candidate", "concern", "assessment")} if turn else None,
                clock={k: status.get(k) for k in (
                    "active_ply", "finished", "elapsed_seconds", "allocation_seconds", "query_available_seconds",
                    "game_seconds_used", "game_remaining_seconds", "raw_game_seconds_used", "refunded_seconds",
                    "critical", "charge_to_submission", "submission_pending_verification")},
                clock_uncertainty_count=len(status["timing_uncertainty"]),
                recent_clock_uncertainties=status["timing_uncertainty"][-3:],
                clock_available=clock_available,
                clock_ledger=str(directory / "clock.jsonl"), latest_query=latest_query,
                current_engine_sha256=fingerprint,
                latest_query_engine_matches_current=(recorded_hash == fingerprint if recorded_hash else None),
                next_action=next_action,
                live_state="Not observed by this read-only helper. Reacquire the embedded browser and inspect it.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", help="Explicit saved game directory name; omission lists journals")
    args = parser.parse_args(argv)
    try:
        if args.game is None:
            result = list_games()
        else:
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", args.game):
                raise ValueError("--game must be a directory slug, not a path")
            result = snapshot(ROOT / "engine-games" / args.game)
        print(json.dumps(result, indent=2))
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f"Error: {error}\n")


if __name__ == "__main__":
    main()
