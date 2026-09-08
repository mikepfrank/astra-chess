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
    if not events or events[0].get("kind") != "game_started" or events[0].get("data", {}).get("schema") not in (1, 2):
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
    config = dict(events[0]["data"])
    active = None
    used = 0.0
    finished = False
    turns = 0
    prior_plies = set()
    uncertainty = []
    overruns = []
    excluded_verification = 0.0
    refunded = 0.0
    refunds = []
    extensions = []
    excluded_pause = 0.0
    verified_plies = set()
    earned_increment = 0.0
    earned_stage = 0.0
    stage_grants = []
    game_overruns = []
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
            excluded_verification += data.get("excluded_verification_seconds", 0.0)
            uncertainty.extend(data.get("uncertainty", []))
            if data["overrun_seconds"] > 0:
                overruns.append({"ply": data["ply"], "seconds": data["overrun_seconds"]})
            # Check the charged balance before this move earns anything. A later
            # increment, stage, or user refund must not erase a recorded overrun.
            game_overrun = max(0.0, used-refunded-config["total_seconds"])
            if config["mode"] == "game" and game_overrun > 0:
                game_overruns.append({"ply": data["ply"], "seconds": game_overrun})
            if (event["kind"] == "verification" and active is not None
                    and data["ply"] == active["ply"] and data["ply"] not in verified_plies):
                verified_plies.add(data["ply"])
                # Replay derives credits from verified own turns, not mutable
                # totals or the caller's submission/query/decision events.
                if config["schema"] >= 2:
                    increment = config["increment_seconds"]
                    earned_increment += increment
                    config["total_seconds"] += increment
                    if config["stage_moves"] == len(verified_plies):
                        grant = config["stage_seconds"]
                        earned_stage += grant
                        config["total_seconds"] += grant
                        stage_grants.append({"own_move": len(verified_plies), "ply": data["ply"],
                                             "seconds": grant, "event_seq": event["seq"]})
            active = None
        elif event["kind"] == "game_finished":
            finished = True
        elif event["kind"] == "user_time_refund":
            refunded += data["seconds"]
            refunds.append(dict(data, recorded_utc=event["utc"]))
        elif event["kind"] == "user_time_extension":
            config["total_seconds"] += data["extra_seconds"]
            config["extended_turn_seconds"] = data["turn_seconds"]
            extensions.append(dict(data, recorded_utc=event["utc"]))
            excluded_pause += data["excluded_pause_seconds"]
            uncertainty.extend(data.get("uncertainty", []))
            if active is not None:
                active["resumption"] = data
                active["allocation_seconds"] = data["allocation_seconds"]
    return dict(active=active, used=max(0.0, used-refunded), raw_used=used,
                refunded=refunded, refunds=refunds, finished=finished, turns=turns,
                prior_plies=prior_plies, uncertainty=uncertainty, overruns=overruns,
                excluded_verification=excluded_verification, config=config,
                extensions=extensions, excluded_pause=excluded_pause,
                completed_own_moves=len(verified_plies), earned_increment=earned_increment,
                earned_stage=earned_stage, stage_grants=stage_grants,
                game_overruns=game_overruns)


def _elapsed(active, sample):
    stamp, mono = sample
    resume = active.get("resumption")
    start = resume["resumed_utc"] if resume else active["observed_utc"]
    started_mono = resume["resumed_monotonic"] if resume else active["started_monotonic"]
    prior = resume["elapsed_before_pause_seconds"] if resume else 0.0
    wall = max(0.0, (stamp - _utc(start)).total_seconds())
    monotonic = mono - started_mono
    warning = []
    if monotonic < 0 or abs(monotonic - wall) > 5:
        warning.append("System clock or uptime changed; elapsed time uses the larger nonnegative wall/monotonic interval")
    # Never erase elapsed time because of a wall-clock correction or a reboot.
    return prior + max(0.0, monotonic, wall), warning


def _elapsed_at_utc(active, stamp):
    """Settle authoritative UI timestamps without charging an approved pause."""
    resume = active.get("resumption")
    if resume:
        if stamp < _utc(resume["resumed_utc"]):
            raise ValueError("Submission or verification cannot precede the recorded resumption")
        return resume["elapsed_before_pause_seconds"] + (stamp - _utc(resume["resumed_utc"])).total_seconds()
    return (stamp - _utc(active["observed_utc"])).total_seconds()


def _allocation(config, used, turns, critical, completed_moves=None):
    if config["mode"] == "move":
        return config["move_seconds"]
    remaining = max(0.0, config["total_seconds"] - used)
    if "extended_turn_seconds" in config:
        return min(remaining, config["extended_turn_seconds"])
    if config.get("schema", 1) >= 2:
        completed = turns if completed_moves is None else completed_moves
        stage = config["stage_moves"]
        # Before the stage, spread only already credited time across the moves
        # still required to earn it. Afterward plan toward twenty further moves,
        # with a rolling twelve-move horizon for a long ending. Future increments
        # and the future stage grant never enter this available balance.
        expected_turns_left = (stage-completed if stage and completed < stage
                               else max(12, (stage+20 if stage else 40)-completed))
        forecast = remaining / expected_turns_left
        target = config["critical_seconds"] if critical else config["ordinary_seconds"]
        return min(remaining, target, forecast * (2 if critical else 1))
    expected_turns_left = max(12, 40 - turns)
    ordinary = min(90.0, remaining / expected_turns_left)
    return min(remaining, ordinary * 2 if critical else ordinary, 180.0 if critical else 90.0)


def _status(events, sample=None):
    state = _state(events)
    config = state["config"]
    active = state["active"]
    elapsed, extra_warnings = _elapsed(active, sample or _sample()) if active else (0.0, [])
    total_used = state["used"] + elapsed
    game_remaining = max(0.0, config["total_seconds"] - total_used) if config["mode"] == "game" else None
    allocation = active["allocation_seconds"] if active else 0.0
    remaining = max(0.0, allocation - elapsed)
    if game_remaining is not None:
        remaining = min(remaining, game_remaining)
    query_available = max(0.0, remaining - config["reserve_seconds"]) if active and not state["finished"] else 0.0
    stage_moves = config.get("stage_moves")
    next_stage = stage_moves if stage_moves and state["completed_own_moves"] < stage_moves else None
    status = {
        "clock_kind": "game_ledger", "mode": config["mode"], "active_ply": active["ply"] if active else None,
        "finished": state["finished"], "critical": bool(active and active["critical"]),
        "allocation_seconds": allocation, "elapsed_seconds": elapsed, "remaining_seconds": remaining,
        "reserve_seconds": config["reserve_seconds"], "query_available_seconds": query_available,
        "game_seconds_used": total_used, "game_remaining_seconds": game_remaining,
        "game_balance_seconds": config["total_seconds"]-total_used if config["mode"] == "game" else None,
        "raw_game_seconds_used": state["raw_used"] + elapsed,
        "refunded_seconds": state["refunded"], "time_refunds": state["refunds"],
        "total_seconds": config["total_seconds"],
        "original_total_seconds": events[0]["data"]["total_seconds"],
        "clock_schema": config["schema"],
        "completed_own_moves": state["completed_own_moves"],
        "increment_seconds": config.get("increment_seconds", 0.0),
        "earned_increment_seconds": state["earned_increment"],
        "stage_moves": stage_moves, "stage_seconds": config.get("stage_seconds", 0.0),
        "earned_stage_seconds": state["earned_stage"], "stage_grants": state["stage_grants"],
        "next_stage_own_move": next_stage,
        "own_moves_to_next_stage": next_stage-state["completed_own_moves"] if next_stage else None,
        "ordinary_seconds": config.get("ordinary_seconds", 90.0),
        "critical_seconds": config.get("critical_seconds", 180.0),
        "extension_seconds": sum(item["extra_seconds"] for item in state["extensions"]),
        "time_extensions": state["extensions"], "excluded_pause_seconds": state["excluded_pause"],
        "extended_turn_seconds": config.get("extended_turn_seconds"),
        "turn_overrun_seconds": max(0.0, elapsed - allocation),
        "game_overrun_seconds": max(0.0, total_used - config["total_seconds"]) if config["mode"] == "game" else 0.0,
        "expired": bool(active and remaining <= 0), "calls": active["queries"] if active else 0,
        "query_seconds_used": active["query_seconds"] if active else 0.0,
        "verified_turn_overruns": state["overruns"],
        "verified_game_overruns": state["game_overruns"],
        "timing_uncertainty": list(dict.fromkeys(state["uncertainty"] + extra_warnings)),
        "submission_pending_verification": bool(active and active["submission"]),
        "charge_to_submission": config.get("charge_to_submission", False),
        "excluded_verification_seconds": state["excluded_verification"],
        "cooperative_clock": True,
    }
    return {key: round(value, 3) if isinstance(value, float) else value for key, value in status.items()}


def create_game_clock(path, *, mode="game", total_seconds=3600, move_seconds=120, reserve_seconds=40,
                      charge_to_submission=False, increment_seconds=0, stage_moves=None,
                      stage_seconds=0, ordinary_seconds=90, critical_seconds=180):
    """Create once. Optionally settle verified moves at their recorded submission.

    Until verified, attempted moves keep the clock running. Legacy ledgers charge
    through verification; charge_to_submission excludes waiting for the opponent
    and browser confirmation when a valid submission timestamp is available.
    Staged/increment clocks award time only on verified own moves. The defaults
    retain the schema-1 fixed-total policy; custom controls use schema 2.
    """
    if mode not in ("game", "move"):
        raise ValueError("Clock mode must be game or move")
    if not isinstance(charge_to_submission, bool):
        raise ValueError("charge_to_submission must be a boolean")
    total_seconds = _number(total_seconds, "total_seconds", 1)
    move_seconds = _number(move_seconds, "move_seconds", 1)
    reserve_seconds = _number(reserve_seconds, "reserve_seconds")
    increment_seconds = _number(increment_seconds, "increment_seconds")
    stage_seconds = _number(stage_seconds, "stage_seconds")
    ordinary_seconds = _number(ordinary_seconds, "ordinary_seconds", 0.001)
    critical_seconds = _number(critical_seconds, "critical_seconds", ordinary_seconds)
    if stage_moves is not None and (isinstance(stage_moves, bool) or not isinstance(stage_moves, int) or stage_moves < 1):
        raise ValueError("stage_moves must be a positive integer or None")
    if (stage_moves is None) != (stage_seconds == 0):
        raise ValueError("A stage requires both stage_moves and positive stage_seconds")
    if mode != "game" and (increment_seconds or stage_moves is not None):
        raise ValueError("Increments and stages require cumulative game mode")
    custom = bool(increment_seconds or stage_moves is not None or ordinary_seconds != 90 or critical_seconds != 180)
    config = dict(schema=2 if custom else 1, mode=mode, total_seconds=total_seconds,
                  move_seconds=move_seconds, reserve_seconds=reserve_seconds,
                  charge_to_submission=charge_to_submission)
    if custom:
        config.update(increment_seconds=increment_seconds, stage_moves=stage_moves,
                      stage_seconds=stage_seconds, ordinary_seconds=ordinary_seconds,
                      critical_seconds=critical_seconds)
    if reserve_seconds >= _allocation(config, 0, 0, False, 0):
        raise ValueError("The initial turn allocation must leave time beyond the move-entry reserve")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _locked(path):
        # x prevents accidental replacement of a game ledger, including finished games.
        with path.open("x", encoding="utf-8"):
            pass
        events = []
        _append(path, events, "game_started", config)
    return _status(events)


def clock_status(path):
    return _status(_read(path))


def resume_with_extension(path, *, paused_utc, resumed_utc, extra_seconds,
                          reason, adjustment_id, turn_seconds=120):
    """Append a user-authorized pause/resumption and added cumulative budget.

    This is not a refund: all thinking before paused_utc stays charged. Only the
    expressly approved waiting/setup interval is excluded. The resumed turn gets
    turn_seconds of fresh allocation, and later turns use the same fixed target,
    always bounded by the remaining total and existing move-entry reserve.
    Call only after the user authorizes resumption with extra time.
    """
    extra_seconds = _number(extra_seconds, "extra_seconds", 0.001)
    turn_seconds = _number(turn_seconds, "turn_seconds", 0.001)
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("Record the user's reason for the extension")
    if not isinstance(adjustment_id, str) or not adjustment_id.strip():
        raise ValueError("A unique adjustment_id is required")
    paused, resumed = _utc(paused_utc), _utc(resumed_utc)
    with _locked(path) as path:
        events = _read(path)
        state = _state(events)
        active = state["active"]
        config = state["config"]
        if active is None or state["finished"] or config["mode"] != "game":
            raise ValueError("Extension requires an active own turn in an unfinished cumulative game clock")
        if active["submission"] is not None:
            raise ValueError("Reconcile the pending submission before resuming")
        if any(item["adjustment_id"] == adjustment_id.strip() for item in state["extensions"]):
            raise ValueError("This adjustment_id has already been applied")
        if turn_seconds <= config["reserve_seconds"]:
            raise ValueError("Turn allocation must exceed the move-entry reserve")
        stamp, mono = _sample()
        prior_resume = active.get("resumption")
        earliest = _utc(prior_resume["resumed_utc"] if prior_resume else active["observed_utc"])
        if not earliest <= paused <= resumed <= stamp:
            raise ValueError("Require active observation/resumption <= pause <= resumption <= now")
        activities = {"initial_candidate", "critical_position", "query_started", "query_completed",
                      "decision", "submission", "submission_rejected", "verification", "turn_ended"}
        if any(event["kind"] in activities and _utc(event["utc"]) > paused for event in events):
            raise ValueError("Pause cannot exclude recorded analysis or move activity")
        # Reconstruct the boundary from the closest recorded sample rather than
        # projecting today's uptime backwards across a possibly long suspension.
        anchor = min(events, key=lambda event: abs((_utc(event["utc"]) - paused).total_seconds()))
        pause_mono = anchor["monotonic"] + (paused - _utc(anchor["utc"])).total_seconds()
        prior_elapsed, warnings = _elapsed(active, (paused, pause_mono))
        boundary_note = next((event for event in reversed(events) if event["kind"] == "note"
                              and event["data"].get("paused_utc") == paused.isoformat()
                              and "own_seconds_at_pause" in event["data"]), None)
        boundary_sample_difference = 0.0
        if boundary_note:
            saved_used = _number(boundary_note["data"]["own_seconds_at_pause"], "own_seconds_at_pause")
            saved_elapsed = saved_used-state["used"]
            boundary_sample_difference = saved_elapsed-prior_elapsed
            if saved_elapsed < 0 or abs(boundary_sample_difference) > 1:
                raise ValueError("Documented pause balance disagrees with reconstructed elapsed time")
            prior_elapsed = saved_elapsed
        data = dict(ply=active["ply"], paused_utc=paused.isoformat(), resumed_utc=resumed.isoformat(),
                    resumed_monotonic=mono-(stamp-resumed).total_seconds(),
                    excluded_pause_seconds=(resumed-paused).total_seconds(),
                    elapsed_before_pause_seconds=prior_elapsed, extra_seconds=extra_seconds,
                    turn_seconds=turn_seconds, allocation_seconds=prior_elapsed+turn_seconds,
                    previous_allocation_seconds=active["allocation_seconds"],
                    original_total_seconds=config["total_seconds"],
                    boundary_note_seq=boundary_note["seq"] if boundary_note else None,
                    boundary_sample_difference_seconds=boundary_sample_difference,
                    reason=reason.strip(), adjustment_id=adjustment_id.strip(),
                    authorization="express_user_request", uncertainty=warnings)
        _append(path, events, "user_time_extension", data, (stamp, mono))
        return _status(events, (stamp, mono))


def refund_turn_time(path, ply, seconds, *, reason, adjustment_id):
    """Append an explicit user-authorized credit for a completed turn.

    Call only following an express user instruction to forgive recorded time.
    Original charges, timestamps and overruns remain intact as audit evidence.
    A unique adjustment_id prevents duplicate credits when a caller retries.
    Refunds cannot exceed the target turn's original charge in aggregate.
    """
    if isinstance(ply, bool) or not isinstance(ply, int) or ply < 0:
        raise ValueError("ply must be a nonnegative integer")
    seconds = _number(seconds, "seconds")
    if seconds <= 0:
        raise ValueError("Refund seconds must be positive")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("Record the user's reason for the clock refund")
    if not isinstance(adjustment_id, str) or not adjustment_id.strip():
        raise ValueError("A unique adjustment_id is required")
    adjustment_id = adjustment_id.strip()
    with _locked(path) as path:
        events = _read(path)
        refunds = [event["data"] for event in events if event["kind"] == "user_time_refund"]
        if any(refund["adjustment_id"] == adjustment_id for refund in refunds):
            raise ValueError("This adjustment_id has already been refunded")
        completed = next((event for event in events if event["kind"] in ("verification", "turn_ended")
                          and event["data"]["ply"] == ply), None)
        if completed is None:
            raise ValueError("Refund requires a completed turn with a recorded charge")
        charged = completed["data"]["charged_seconds"]
        already_refunded = sum(refund["seconds"] for refund in refunds if refund["ply"] == ply)
        if seconds > charged - already_refunded:
            raise ValueError("Refund exceeds the turn's remaining recorded charge")
        _append(path, events, "user_time_refund", dict(ply=ply, seconds=seconds,
                reason=reason.strip(), adjustment_id=adjustment_id, authorization="express_user_request",
                original_charge_seconds=charged, charge_event_seq=completed["seq"]))
        return _status(events)


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
        config = state["config"]
        allocation = _allocation(config, state["used"], state["turns"], critical, state["completed_own_moves"])
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
        allocation = max(active["allocation_seconds"], _allocation(state["config"], state["used"], state["turns"]-1,
                                                                  True, state["completed_own_moves"]))
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
            _elapsed_at_utc(active, submitted)
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

    If configured, a verified move is charged only through its submission. Without
    a trustworthy submission timestamp, conservatively charge through verification.
    A supplied verified_utc records the actual observation when entered later.
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
        activity = next((event for event in reversed(events) if event["kind"] in
                         ("turn_observed", "initial_candidate", "query_completed", "decision", "submission_rejected")), None)
        if verified_utc:
            if activity and activity["kind"] != "turn_observed" and verified < _utc(activity["utc"]):
                raise ValueError("Verification cannot precede recorded analysis, decision, or a rejected submission")
        charge_to_submission = events[0]["data"].get("charge_to_submission", False)
        if charge_to_submission and submitted is not None:
            if activity and activity["kind"] != "turn_observed" and submitted < _utc(activity["utc"]):
                raise ValueError("Submission cutoff cannot precede recorded analysis, decision, or a rejected submission")
        elapsed, warnings = _elapsed(active, (stamp, mono))
        if verified_utc:
            # Caller-provided actual verification is authoritative; retain uncertainty.
            elapsed = _elapsed_at_utc(active, verified)
            if (stamp-verified).total_seconds() > 1:
                warnings.append("Verification entered later using the supplied observation timestamp")
        excluded_verification = 0.0
        charged_through = verified
        if charge_to_submission and submitted is not None:
            elapsed = _elapsed_at_utc(active, submitted)
            excluded_verification = (verified-submitted).total_seconds()
            charged_through = submitted
        if submission is None:
            if submitted is None:
                warnings.append("No separate submission timestamp; charged through verification")
            _append(path, events, "submission", dict(ply=ply, move=move,
                    submitted_utc=submitted.isoformat() if submitted else verified.isoformat(),
                    inferred_from_verification=submitted is None), (stamp, mono))
        if uncertainty:
            warnings.append(uncertainty)
        award_evidence = {}
        if state["config"]["schema"] >= 2:
            completed = state["completed_own_moves"] + 1
            increment = state["config"]["increment_seconds"]
            stage = state["config"]["stage_seconds"] if completed == state["config"]["stage_moves"] else 0.0
            balance = state["config"]["total_seconds"] - state["used"] - elapsed
            award_evidence = dict(completed_own_moves=completed,
                    game_balance_before_award_seconds=balance,
                    game_overrun_before_award_seconds=max(0.0, -balance),
                    increment_awarded_seconds=increment, stage_awarded_seconds=stage,
                    game_balance_after_award_seconds=balance+increment+stage)
        _append(path, events, "verification", dict(ply=ply, move=move, verified_utc=verified.isoformat(),
                charged_through_utc=charged_through.isoformat(),
                excluded_verification_seconds=excluded_verification,
                charged_seconds=elapsed, overrun_seconds=max(0.0, elapsed-active["allocation_seconds"]),
                uncertainty=warnings, **award_evidence), (stamp, mono))
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
