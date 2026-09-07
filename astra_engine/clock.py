"""Append-only, cooperative wall clock for a human/engine combined player.

No move is assumed to have happened until verification. The ledger is evidence,
not a chess server clock: observation latency and clock discontinuities are
reported, and exceeding a budget never erases elapsed time.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import time


def _sample():
    return datetime.now(timezone.utc), time.monotonic()


def _utc(value):
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError("Timestamp must be an ISO 8601 string with a time zone")
    if result.tzinfo is None:
        raise ValueError("Timestamp must include a time zone")
    return result.astimezone(timezone.utc)


def _number(value, name, minimum=0):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < minimum:
        raise ValueError(f"{name} must be a finite number at least {minimum}")
    return float(value)


@contextmanager
def _locked(path):
    path = Path(path)
    lock = path.with_name(path.name + ".lock")
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as error:
        raise ValueError("Clock is busy; complete the active query or journal operation first") from error
    try:
        os.close(fd)
        yield path
    finally:
        lock.unlink(missing_ok=True)


def _read(path):
    events = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    if not events or events[0].get("kind") != "game_started" or events[0].get("data", {}).get("schema") != 1:
        raise ValueError("Not an Astra game clock ledger")
    if any(event.get("seq") != i for i, event in enumerate(events)):
        raise ValueError("Clock ledger sequence is incomplete or out of order")
    return events


def _append(path, events, kind, data, sample=None):
    stamp, mono = sample or _sample()
    event = {"seq": len(events), "kind": kind, "utc": stamp.isoformat(), "monotonic": mono, "data": data}
    with Path(path).open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    events.append(event)
    return event


def _state(events):
    active = None
    used = 0.0
    finished = False
    turns = 0
    prior_plies = set()
    uncertainty = []
    overruns = []
    for event in events[1:]:
        data = event["data"]
        if event["kind"] == "turn_observed":
            active = dict(data)
            active["queries"] = 0
            active["query_seconds"] = 0.0
            active["submission"] = None
            turns += 1
            prior_plies.add(data["ply"])
            uncertainty.extend(data.get("uncertainty", []))
        elif event["kind"] == "critical_position" and active is not None:
            active["allocation_seconds"] = data["allocation_seconds"]
            active["critical"] = True
        elif event["kind"] == "query_started" and active is not None:
            active["queries"] += 1
        elif event["kind"] == "query_completed" and active is not None:
            active["query_seconds"] += data["elapsed_seconds"]
        elif event["kind"] == "submission" and active is not None:
            active["submission"] = dict(data, recorded_utc=event["utc"])
        elif event["kind"] == "submission_rejected" and active is not None:
            active["submission"] = None
        elif event["kind"] in ("verification", "turn_ended"):
            used += data["charged_seconds"]
            uncertainty.extend(data.get("uncertainty", []))
            if data["overrun_seconds"] > 0:
                overruns.append({"ply": data["ply"], "seconds": data["overrun_seconds"]})
            active = None
        elif event["kind"] == "game_finished":
            finished = True
    return dict(active=active, used=used, finished=finished, turns=turns,
                prior_plies=prior_plies, uncertainty=uncertainty, overruns=overruns)


def _elapsed(active, sample):
    stamp, mono = sample
    wall = max(0.0, (stamp - _utc(active["observed_utc"])).total_seconds())
    monotonic = mono - active["started_monotonic"]
    warning = []
    if monotonic < 0 or abs(monotonic - wall) > 5:
        warning.append("System clock or uptime changed; elapsed time uses the larger nonnegative wall/monotonic interval")
    # Never erase elapsed time because of a wall-clock correction or a reboot.
    return max(0.0, monotonic, wall), warning


def _allocation(config, used, turns, critical):
    if config["mode"] == "move":
        return config["move_seconds"]
    remaining = max(0.0, config["total_seconds"] - used)
    expected_turns_left = max(12, 40 - turns)
    ordinary = min(90.0, remaining / expected_turns_left)
    return min(remaining, ordinary * 2 if critical else ordinary, 180.0 if critical else 90.0)


def _status(events, sample=None):
    state = _state(events)
    config = events[0]["data"]
    active = state["active"]
    elapsed, extra_warnings = _elapsed(active, sample or _sample()) if active else (0.0, [])
    total_used = state["used"] + elapsed
    game_remaining = max(0.0, config["total_seconds"] - total_used) if config["mode"] == "game" else None
    allocation = active["allocation_seconds"] if active else 0.0
    remaining = max(0.0, allocation - elapsed)
    if game_remaining is not None:
        remaining = min(remaining, game_remaining)
    query_available = max(0.0, remaining - config["reserve_seconds"]) if active and not state["finished"] else 0.0
    status = {
        "clock_kind": "game_ledger", "mode": config["mode"], "active_ply": active["ply"] if active else None,
        "finished": state["finished"], "critical": bool(active and active["critical"]),
        "allocation_seconds": allocation, "elapsed_seconds": elapsed, "remaining_seconds": remaining,
        "reserve_seconds": config["reserve_seconds"], "query_available_seconds": query_available,
        "game_seconds_used": total_used, "game_remaining_seconds": game_remaining,
        "turn_overrun_seconds": max(0.0, elapsed - allocation),
        "game_overrun_seconds": max(0.0, total_used - config["total_seconds"]) if config["mode"] == "game" else 0.0,
        "expired": bool(active and remaining <= 0), "calls": active["queries"] if active else 0,
        "query_seconds_used": active["query_seconds"] if active else 0.0,
        "verified_turn_overruns": state["overruns"],
        "timing_uncertainty": list(dict.fromkeys(state["uncertainty"] + extra_warnings)),
        "submission_pending_verification": bool(active and active["submission"]),
        "cooperative_clock": True,
    }
    return {key: round(value, 3) if isinstance(value, float) else value for key, value in status.items()}


def create_game_clock(path, *, mode="game", total_seconds=3600, move_seconds=120, reserve_seconds=40):
    """Create once. mode='game' shares a cumulative budget; 'move' has no game cap."""
    if mode not in ("game", "move"):
        raise ValueError("Clock mode must be game or move")
    total_seconds = _number(total_seconds, "total_seconds", 1)
    move_seconds = _number(move_seconds, "move_seconds", 1)
    reserve_seconds = _number(reserve_seconds, "reserve_seconds")
    if reserve_seconds >= (min(90, total_seconds / 40) if mode == "game" else move_seconds):
        raise ValueError("The initial turn allocation must leave time beyond the move-entry reserve")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _locked(path):
        # x prevents accidental replacement of a game ledger, including finished games.
        with path.open("x", encoding="utf-8"):
            pass
        events = []
        _append(path, events, "game_started", dict(schema=1, mode=mode, total_seconds=total_seconds,
                move_seconds=move_seconds, reserve_seconds=reserve_seconds))
    return _status(events)


def clock_status(path):
    return _status(_read(path))


def observe_turn(path, ply, *, observed_utc=None, initial_candidate=None, concern="", critical=False):
    """Start at first observed own turn. Re-observing any previously seen ply is an error."""
    if isinstance(ply, bool) or not isinstance(ply, int) or ply < 0:
        raise ValueError("ply must be a nonnegative integer")
    with _locked(path) as path:
        events = _read(path)
        state = _state(events)
        if state["finished"]:
            raise ValueError("Game clock has finished")
        if state["active"] is not None:
            raise ValueError("An own turn is still active; retries and follow-up queries must share that clock")
        if ply in state["prior_plies"] or (state["prior_plies"] and ply <= max(state["prior_plies"])):
            raise ValueError("Cannot reset a clock for the same or an earlier ply")
        stamp, mono = _sample()
        observed = _utc(observed_utc) if observed_utc else stamp
        age = (stamp - observed).total_seconds()
        if age < 0:
            raise ValueError("Observation timestamp cannot be in the future")
        last_verified = next((event["data"]["verified_utc"] for event in reversed(events)
                              if event["kind"] == "verification"), None)
        if last_verified and observed < _utc(last_verified):
            raise ValueError("Next turn observation cannot precede the previous verified move")
        config = events[0]["data"]
        allocation = _allocation(config, state["used"], state["turns"], critical)
        warnings = []
        if age > 1:
            warnings.append(f"Observation timestamp entered {age:.3f}s later; interval is charged from the supplied observation")
        data = dict(ply=ply, observed_utc=observed.isoformat(), started_monotonic=mono-age,
                    allocation_seconds=allocation, critical=bool(critical), concern=concern,
                    uncertainty=warnings)
        _append(path, events, "turn_observed", data, (stamp, mono))
        if initial_candidate is not None:
            _append(path, events, "initial_candidate", dict(ply=ply, move=initial_candidate), (stamp, mono))
        return _status(events, (stamp, mono))


def mark_critical(path, reason):
    """Increase the target from the original observation; never reset elapsed time."""
    if not reason:
        raise ValueError("Record the concrete reason for a critical-position allowance")
    with _locked(path) as path:
        events = _read(path)
        state = _state(events)
        if state["active"] is None or state["finished"]:
            raise ValueError("No active own turn")
        active = state["active"]
        allocation = max(active["allocation_seconds"], _allocation(events[0]["data"], state["used"], state["turns"]-1, True))
        _append(path, events, "critical_position", dict(ply=active["ply"], reason=reason, allocation_seconds=allocation))
        return _status(events)


def record_event(path, kind, **data):
    """Record commentary/decision or an attempted submission; a rejection keeps time running."""
    if kind not in ("initial_candidate", "decision", "submission", "submission_rejected", "query_rejected", "note"):
        raise ValueError("Use the dedicated clock API for structural events")
    with _locked(path) as path:
        events = _read(path)
        state = _state(events)
        if state["active"] is None or state["finished"]:
            raise ValueError("No active own turn")
        active = state["active"]
        if "ply" in data and data["ply"] != active["ply"]:
            raise ValueError("Event does not belong to the active ply")
        if kind == "submission":
            if not isinstance(data.get("move"), str) or not data["move"]:
                raise ValueError("Submission requires a move")
            stamp, _ = _sample()
            submitted = _utc(data.get("submitted_utc", stamp))
            if not _utc(active["observed_utc"]) <= submitted <= stamp:
                raise ValueError("Submission must fall between observation and now")
            data["submitted_utc"] = submitted.isoformat()
        _append(path, events, kind, dict(data, ply=active["ply"]))
        return _status(events)


@contextmanager
def query_clock(path, requested_seconds, metadata=None):
    """Hold the ledger lock and charge an entire query/report, including failure.

    The caller must use allotted_seconds as its complete search/report deadline.
    This context records overhead and overruns; it cannot interrupt Python code.
    """
    requested_seconds = _number(requested_seconds, "requested_seconds", 0.001)
    with _locked(path) as path:
        events = _read(path)
        before = _status(events)
        if before["active_ply"] is None or before["finished"]:
            raise ValueError("Observe an own turn before querying this game clock")
        allotted = min(requested_seconds, before["query_available_seconds"])
        if allotted <= 0.01:
            _append(path, events, "query_rejected", dict(ply=before["active_ply"],
                    requested_seconds=requested_seconds, reason="Move-entry reserve exhausted", metadata=metadata or {}))
            raise ValueError("Search budget exhausted; preserve the remaining move-entry reserve")
        sample = _sample()
        _append(path, events, "query_started", dict(ply=before["active_ply"], requested_seconds=requested_seconds,
                allotted_seconds=allotted, metadata=metadata or {}), sample)
        ticket = {"allotted_seconds": allotted, "before": before}
        error = None
        try:
            yield ticket
        except BaseException as exc:
            error = type(exc).__name__
            raise
        finally:
            completed = _sample()
            elapsed = max(0.0, completed[1]-sample[1], (completed[0]-sample[0]).total_seconds())
            _append(path, events, "query_completed", dict(ply=before["active_ply"], elapsed_seconds=elapsed,
                    allotted_seconds=allotted, overrun_seconds=max(0.0, elapsed-allotted), error=error), completed)
            ticket["after"] = _status(events, completed)


def verify_submission(path, ply, move, *, submitted_utc=None, verified_utc=None, uncertainty=""):
    """End an own turn only after the caller confirms the legal move on the board.

    If verification is recorded later, a supplied verified_utc stops at that actual
    observation. Without it, charge through now (a conservative upper estimate).
    """
    with _locked(path) as path:
        events = _read(path)
        state = _state(events)
        active = state["active"]
        if active is None or active["ply"] != ply or state["finished"]:
            raise ValueError("Verification must match the active ply")
        stamp, mono = _sample()
        verified = _utc(verified_utc) if verified_utc else stamp
        observation = _utc(active["observed_utc"])
        submission = active["submission"]
        if submission is not None and submission["move"] != move:
            raise ValueError("Verified move differs from the latest submitted move; record a new submission")
        submitted = _utc(submitted_utc) if submitted_utc else _utc(submission["submitted_utc"]) if submission else None
        if not observation <= verified <= stamp or (submitted and not observation <= submitted <= verified):
            raise ValueError("Require observation <= submission <= verification <= now")
        if verified_utc:
            activity = next((event for event in reversed(events) if event["kind"] in
                             ("turn_observed", "query_completed", "decision", "submission_rejected")), None)
            if activity and activity["kind"] != "turn_observed" and verified < _utc(activity["utc"]):
                raise ValueError("Verification cannot precede recorded analysis, decision, or a rejected submission")
        elapsed, warnings = _elapsed(active, (stamp, mono))
        if verified_utc:
            # Caller-provided actual verification is authoritative; retain uncertainty.
            elapsed = (verified-observation).total_seconds()
            if (stamp-verified).total_seconds() > 1:
                warnings.append("Verification entered later using the supplied observation timestamp")
        if submission is None:
            if submitted is None:
                warnings.append("No separate submission timestamp; charged through verification")
            _append(path, events, "submission", dict(ply=ply, move=move,
                    submitted_utc=submitted.isoformat() if submitted else verified.isoformat(),
                    inferred_from_verification=submitted is None), (stamp, mono))
        if uncertainty:
            warnings.append(uncertainty)
        _append(path, events, "verification", dict(ply=ply, move=move, verified_utc=verified.isoformat(),
                charged_seconds=elapsed, overrun_seconds=max(0.0, elapsed-active["allocation_seconds"]),
                uncertainty=warnings), (stamp, mono))
        return _status(events, (stamp, mono))


def finish_game_clock(path, result, *, reason=""):
    """Charge an unfinished own turn, such as resignation, then close the ledger."""
    if result not in ("1-0", "0-1", "1/2-1/2", "*"):
        raise ValueError("Invalid game result")
    with _locked(path) as path:
        events = _read(path)
        state = _state(events)
        if state["finished"]:
            raise ValueError("Game clock already finished")
        sample = _sample()
        active = state["active"]
        if active:
            elapsed, warnings = _elapsed(active, sample)
            _append(path, events, "turn_ended", dict(ply=active["ply"], reason=reason or "game finished",
                    charged_seconds=elapsed, overrun_seconds=max(0.0, elapsed-active["allocation_seconds"]),
                    uncertainty=warnings), sample)
        _append(path, events, "game_finished", dict(result=result, reason=reason), sample)
        return _status(events, sample)
