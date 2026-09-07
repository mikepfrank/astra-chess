"""Astra Search Lab: local chess questions, inspectable answers, shared turn clocks.

Runtime dependencies: Python standard library only. No network access.
See ENGINE.md for request examples and the distinction between a witness and proof.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager, ExitStack
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import time


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def positive_number(value, name, maximum=180):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= maximum:
        raise ValueError(f"{name} must be a finite number greater than 0 and at most {maximum}")
    return float(value)


def integer(value, name, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer from {minimum} to {maximum}")
    return value


@contextmanager
def locked_session(path):
    if path is None:
        yield None
        return
    path = Path(path)
    lock = path.with_name(path.name + ".lock")
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as error:
        raise ValueError("This turn already has an active query. Run turn queries sequentially.") from error
    try:
        os.close(descriptor)
        session = json.loads(path.read_text(encoding="utf-8"))
        yield session
    finally:
        lock.unlink(missing_ok=True)


def session_status(session):
    elapsed = time.monotonic() - session["started_monotonic"]
    if elapsed < 0:
        raise ValueError("This turn clock belongs to an earlier system uptime; start a new turn clock")
    remaining = max(0.0, session["turn_seconds"] - elapsed)
    engine_remaining = max(0.0, session["engine_seconds"] - session["engine_seconds_used"])
    return {
        "elapsed_seconds": round(elapsed, 3),
        "remaining_seconds": round(remaining, 3),
        "engine_remaining_seconds": round(engine_remaining, 3),
        "reserve_seconds": session["reserve_seconds"],
        "query_available_seconds": round(max(0.0, min(engine_remaining, remaining - session["reserve_seconds"])), 3),
        "expired": remaining <= 0,
        "calls": session["calls"],
    }


def prepare(request):
    from astra_engine.rules import Position, START_FEN

    if not isinstance(request, dict):
        raise ValueError("The query must be a JSON object")
    allowed = {"label", "mode", "fen", "after", "history_fens", "depth", "seconds", "candidates", "root_moves", "goal",
               "diagnostics", "evaluation", "threat_extensions", "proof_only"}
    unknown = set(request) - allowed
    if unknown:
        raise ValueError("Unknown query fields: " + ", ".join(sorted(unknown)))
    mode = request.get("mode", "analyze")
    if mode not in ("analyze", "probe"):
        raise ValueError("mode must be analyze or probe")
    fen = request.get("fen", "startpos")
    if not isinstance(fen, str):
        raise ValueError("fen must be a string")
    position = Position.from_fen(START_FEN if fen == "startpos" else fen)
    raw_history = request.get("history_fens", [])
    after = request.get("after", [])
    if not isinstance(raw_history, list) or not all(isinstance(f, str) for f in raw_history):
        raise ValueError("history_fens must be an array of earlier FEN strings, excluding the starting FEN")
    if not isinstance(after, list) or not all(isinstance(m, str) for m in after):
        raise ValueError("after must be an array of legal UCI moves")
    history_positions = [Position.from_fen(fen) for fen in raw_history]
    for uci in after:
        history_positions.append(position)
        position = position.play(position.parse_uci(uci))
    depth = integer(request.get("depth", 5 if mode == "analyze" else 4), "depth", 1, 32)
    seconds = positive_number(request.get("seconds", 3.0), "seconds")
    candidates = integer(request.get("candidates", 3), "candidates", 1, 10)
    root_moves = request.get("root_moves")
    if root_moves is not None:
        if mode != "analyze" or not isinstance(root_moves, list) or not root_moves:
            raise ValueError("root_moves must be a nonempty array for analyze mode")
        root_moves = [position.parse_uci(m).uci() for m in root_moves]
        if len(root_moves) != len(set(root_moves)):
            raise ValueError("root_moves must not contain duplicates")
    if mode == "probe" and not isinstance(request.get("goal"), dict):
        raise ValueError("probe mode requires a goal object")
    if mode == "analyze" and "goal" in request:
        raise ValueError("Use mode probe for a goal; analyze never silently filters defensive replies")
    for name in ("diagnostics", "proof_only"):
        if name in request and not isinstance(request[name], bool):
            raise ValueError(f"{name} must be a boolean")
    if mode != "probe" and "proof_only" in request:
        raise ValueError("proof_only applies only to probe mode")
    evaluation = request.get("evaluation", {})
    if not isinstance(evaluation, dict) or set(evaluation) - {"mobility", "restricted_piece", "king_exposure"}:
        raise ValueError("evaluation accepts only mobility, restricted_piece, and king_exposure")
    if not all(isinstance(value, bool) for value in evaluation.values()):
        raise ValueError("evaluation options must be booleans")
    integer(request.get("threat_extensions", 0), "threat_extensions", 0, 2)
    if mode != "analyze" and ("evaluation" in request or "threat_extensions" in request):
        raise ValueError("evaluation and threat_extensions apply only to analyze mode")
    label = request.get("label", "Candidate search" if mode == "analyze" else "Goal question")
    if not isinstance(label, str):
        raise ValueError("label must be a string")
    return position, history_positions, mode, depth, seconds, candidates, root_moves, label


def attach_diagnostics(result, deadline):
    """Inspect returned boards outside search; incomplete coverage stays explicit."""
    from astra_engine.diagnostics import diagnose
    from astra_engine.rules import Position

    started = time.monotonic()
    side = 0 if result["start_fen"].split()[1] == "w" else 1
    cache = {}
    skipped = 0

    def inspect(fen, previous=None):
        nonlocal skipped
        key = (fen, previous)
        if key in cache:
            return cache[key]
        if time.monotonic() >= deadline:
            skipped += 1
            return None
        board = Position.from_fen(fen)
        answer = diagnose(board, side=side, previous=Position.from_fen(previous) if previous else None)
        cache[key] = answer
        return answer

    root = inspect(result["start_fen"])
    for line in result.get("candidates", result.get("lines", [])):
        line["position_diagnostics"] = [inspect(fen, line["fens"][i-1] if i else None)
                                        for i, fen in enumerate(line["fens"])]
    result["position_diagnostics"] = root
    result["diagnostic_coverage"] = {"positions_inspected": len(cache), "positions_skipped": skipped,
                                     "complete": skipped == 0, "elapsed_seconds": round(time.monotonic()-started, 6),
                                     "scope": "Query player's pieces and king; heuristic, not a proof of safety."}


def run_query(args):
    from astra_engine.search import analyze, probe

    started = time.monotonic()
    game_clock = getattr(args, "game_clock", None)
    if game_clock and args.session:
        raise ValueError("Use either --game-clock or legacy --session, not both")
    try:
        request = json.loads(args.request.read_text(encoding="utf-8"))
        position, history_positions, mode, depth, seconds, candidates, root_moves, label = prepare(request)
    except (OSError, ValueError, TypeError) as error:
        if game_clock:
            from astra_engine.clock import record_event
            record_event(game_clock, "query_rejected", reason=str(error), request=str(args.request))
        raise
    if args.output.resolve() == args.request.resolve():
        raise ValueError("The result path must differ from the query path")
    clock_paths = {Path(path).resolve() for path in (args.session, game_clock) if path}
    if args.output.resolve() in clock_paths:
        raise ValueError("The result path must differ from the clock path")
    if args.html and args.html.resolve() in clock_paths | {args.request.resolve(), args.output.resolve()}:
        raise ValueError("The HTML path must differ from request, result, and clock paths")
    with ExitStack() as stack:
        session = stack.enter_context(locked_session(args.session))
        before = session_status(session) if session else None
        allotted = min(seconds, before["query_available_seconds"]) if before else seconds
        if game_clock:
            from astra_engine.clock import query_clock, clock_status
            clock_query = stack.enter_context(query_clock(game_clock, seconds, metadata={"request": str(args.request), "label": label}))
            allotted = clock_query["allotted_seconds"]
        if allotted <= 0.01:
            raise ValueError("Turn search budget exhausted; preserve the remaining time for review and moving")
        search_started = time.monotonic()
        try:
            diagnostic_reserve = min(0.5, allotted * 0.1) if request.get("diagnostics", False) else 0
            options = dict(max_depth=depth, time_limit=allotted-diagnostic_reserve,
                           history=[p.repetition_key() for p in history_positions])
            if mode == "analyze":
                result = analyze(position, multipv=candidates, root_moves=root_moves,
                                 evaluation=request.get("evaluation"), threat_extensions=request.get("threat_extensions", 0), **options)
            else:
                result = probe(position, request["goal"], max_lines=candidates,
                               proof_only=request.get("proof_only", False), **options)
        finally:
            if session:
                session["engine_seconds_used"] += time.monotonic() - search_started
                session["calls"] += 1
                write_json(args.session, session)
        if request.get("diagnostics", False):
            attach_diagnostics(result, min(search_started + allotted, time.monotonic() + 1.0))
        result["label"] = label
        result["query"] = request
        result["position_history_fens"] = [p.fen() for p in history_positions]
        result["query_time_limit_seconds"] = allotted
        result["created_utc"] = datetime.now(timezone.utc).isoformat()
        source_dir = Path(__file__).resolve().parent / "astra_engine"
        source_hash = hashlib.sha256()
        for name in ("rules.py", "search.py", "diagnostics.py"):
            source_hash.update(name.encode("ascii") + b"\0" + (source_dir / name).read_bytes())
        result["engine"] = {"name": "Astra Search Lab", "version": "0.2", "source_sha256": source_hash.hexdigest()}
        result["turn_budget"] = clock_status(game_clock) if game_clock else session_status(session) if session else None
        result["interface_elapsed_seconds"] = round(time.monotonic() - started, 3)
        write_json(args.output, result)
        if args.html:
            from astra_engine.report import render_report
            render_report(result, args.html)
        if session or game_clock:
            result["turn_budget"] = clock_status(game_clock) if game_clock else session_status(session)
            result["interface_elapsed_seconds"] = round(time.monotonic() - started, 3)
            write_json(args.output, result)
    if game_clock:
        # The ledger now includes this completed query, including its first
        # report render. Refresh the artifacts with that final accounting.
        # These final small writes remain charged by the active own-turn clock.
        result["turn_budget"] = clock_query["after"]
        result["budget_snapshot"] = "After query completion, before final artifact refresh"
        result["interface_elapsed_seconds"] = round(time.monotonic() - started, 3)
        write_json(args.output, result)
        if args.html:
            render_report(result, args.html)
    summary = {key: result.get(key) for key in ("kind", "label", "completed_depth", "status", "proof_status", "witness_status", "nodes", "elapsed_seconds", "timed_out", "fallback") if key in result}
    summary["result_file"] = str(args.output.resolve())
    if args.html:
        summary["report_file"] = str(args.html.resolve())
    if result["turn_budget"]:
        summary["turn_budget"] = result["turn_budget"]
    print(json.dumps(summary, indent=2))
    for line in result.get("candidates", result.get("lines", [])):
        score = f"{line['score_cp'] / 100:+.2f}: " if line.get("score_cp") is not None else ""
        declaration = (" [declare " + line["claim_by_intended_move"] + " and claim draw]") if line.get("claim_by_intended_move") else ""
        print(score + " ".join(line.get("san", [])) + declaration)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    query = commands.add_parser("query", help="Answer a JSON chess question and save every candidate position")
    query.add_argument("--request", type=Path, required=True)
    query.add_argument("--output", type=Path, default=Path("engine-result.json"))
    query.add_argument("--html", type=Path, help="Optional standalone visual report")
    query.add_argument("--session", type=Path, help="Charge search against a shared turn clock")
    query.add_argument("--game-clock", type=Path, help="Charge the complete query against the game's append-only clock ledger")
    start = commands.add_parser("turn-start", help="Start the clock when the opponent's move is observed")
    start.add_argument("--session", type=Path, default=Path("engine-turn.json"))
    start.add_argument("--seconds", type=float, default=60)
    start.add_argument("--engine-seconds", type=float, default=12)
    start.add_argument("--reserve", type=float, default=8)
    start.add_argument("--replace", action="store_true", help="Replace a previous turn clock")
    status = commands.add_parser("turn-status", help="Include deliberation and browser time in elapsed turn time")
    status.add_argument("--session", type=Path, default=Path("engine-turn.json"))
    args = parser.parse_args()
    try:
        if args.command == "query":
            run_query(args)
        elif args.command == "turn-start":
            seconds = positive_number(args.seconds, "turn seconds", 300)
            engine_seconds = positive_number(args.engine_seconds, "engine seconds", 120)
            reserve = positive_number(args.reserve, "reserve", 120)
            if reserve >= seconds or engine_seconds > seconds - reserve:
                raise ValueError("Engine budget must fit inside the turn after reserving review/move time")
            if args.session.exists() and not args.replace:
                raise ValueError("Turn clock already exists; use --replace when starting the next turn")
            if args.session.with_name(args.session.name + ".lock").exists():
                raise ValueError("Cannot restart the clock during an active query")
            session = {"started_monotonic": time.monotonic(), "started_utc": datetime.now(timezone.utc).isoformat(),
                       "turn_seconds": seconds, "engine_seconds": engine_seconds, "reserve_seconds": reserve,
                       "engine_seconds_used": 0.0, "calls": 0}
            write_json(args.session, session)
            print(json.dumps(session_status(session), indent=2))
        else:
            session = json.loads(args.session.read_text(encoding="utf-8"))
            print(json.dumps(session_status(session), indent=2))
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f"Error: {error}\n")


if __name__ == "__main__":
    main()
