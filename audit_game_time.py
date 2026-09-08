"""Read-only timing audit of settled own turns in an Astra game ledger.

The ledger's charged_seconds is authoritative. Timestamp intervals describe
where time accumulated, not why: no tool-latency attribution is inferred.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics


ROOT = Path(__file__).resolve().parent


def utc(value):
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("Audit timestamps must include a time zone")
    return stamp.astimezone(timezone.utc)


def seconds(start, end):
    return (utc(end) - utc(start)).total_seconds()


def excluding_pauses(start, end, pauses):
    """Subtract only explicit approved intervals, normalized and unioned."""
    lo, hi = utc(start), utc(end)
    merged = []
    for first, last in sorted((utc(first), utc(last)) for first, last in pauses):
        if last < first:
            raise ValueError("A recorded pause ends before it starts")
        if merged and first <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(last, merged[-1][1]))
        else:
            merged.append((first, last))
    excluded = sum(max(0, (min(hi, last) - max(lo, first)).total_seconds()) for first, last in merged)
    return (hi - lo).total_seconds() - excluded


def summarize(rows):
    charged = sum(row["charged_seconds"] for row in rows)
    queries = sum(row["query_wall_seconds"] for row in rows)
    refunds = sum(row["refunded_seconds"] for row in rows)
    return {
        "turn_count": len(rows),
        "charged_seconds": charged,
        "refunded_seconds": refunds,
        "net_charged_seconds": charged - refunds,
        "query_wall_seconds": queries,
        "nonquery_remainder_seconds": charged - queries,
        "query_share_percent": 100 * queries / charged if charged else 0,
        "query_count": sum(row["query_count"] for row in rows),
        "query_errors": sum(row["query_errors"] for row in rows),
        "observation_to_record_seconds": sum(row["observation_to_record_seconds"] for row in rows),
        "decision_to_charge_endpoint_seconds": sum(row["decision_to_charge_endpoint_seconds"] or 0 for row in rows),
        "turns_with_decision_timestamps": sum(row["decision_utc"] is not None for row in rows),
        "excluded_verification_seconds": sum(row["excluded_verification_seconds"] for row in rows),
        "excluded_pause_seconds": sum(row["excluded_pause_seconds"] for row in rows),
        "mean_charged_seconds": charged / len(rows) if rows else None,
        "median_charged_seconds": statistics.median(row["charged_seconds"] for row in rows) if rows else None,
        "turns_over_90_seconds": sum(row["charged_seconds"] > 90 for row in rows),
        "turns_over_120_seconds": sum(row["charged_seconds"] > 120 for row in rows),
    }


def audit(events, game, through_move=None):
    """Return JSON-compatible evidence without consulting or changing live time."""
    if not events or events[0].get("kind") != "game_started":
        raise ValueError("Expected an Astra clock ledger")
    if any(event.get("seq") != index for index, event in enumerate(events)):
        raise ValueError("Clock ledger sequence is incomplete or out of order")
    side = game.get("player_side", "white")
    if side not in ("white", "black"):
        raise ValueError("Invalid player_side")
    grouped = {}
    refunds = {}
    for event in events[1:]:
        data = event.get("data", {})
        ply = data.get("ply")
        if ply is not None:
            grouped.setdefault(ply, []).append(event)
        if event["kind"] == "user_time_refund":
            refunds[ply] = refunds.get(ply, 0) + data["seconds"]
    rows = []
    unsettled = []
    for ply, turn_events in sorted(grouped.items()):
        observed = [event for event in turn_events if event["kind"] == "turn_observed"]
        if not observed:
            continue
        if len(observed) != 1:
            raise ValueError(f"Repeated turn observation for ply {ply}")
        move_number = ply // 2 + 1
        closed = [event for event in turn_events if event["kind"] in ("verification", "turn_ended")]
        if not closed:
            unsettled.append({"ply": ply, "move_number": move_number})
            continue
        if len(closed) != 1:
            raise ValueError(f"Repeated turn settlement for ply {ply}")
        if through_move is not None and move_number > through_move:
            continue
        if ply % 2 != (1 if side == "black" else 0):
            raise ValueError(f"Ply {ply} does not match player_side {side}")
        start_event, end_event = observed[0], closed[0]
        start, end = start_event["data"], end_event["data"]
        observed_utc = start["observed_utc"]
        # Verification may be entered much later. Never substitute its entry
        # time when an actual charge endpoint was saved in the ledger.
        endpoint = end.get("charged_through_utc", end.get("verified_utc", end_event["utc"]))
        elapsed_wall = seconds(observed_utc, endpoint)
        if elapsed_wall < 0:
            raise ValueError(f"Negative settled wall interval at ply {ply}")
        pauses = [(event["data"]["paused_utc"], event["data"]["resumed_utc"])
                  for event in turn_events if event["kind"] == "user_time_extension"
                  and start_event["seq"] <= event["seq"] < end_event["seq"]]
        active_wall = excluding_pauses(observed_utc, endpoint, pauses)
        decisions = [event for event in turn_events if event["kind"] == "decision"
                     and start_event["seq"] <= event["seq"] < end_event["seq"]]
        decision = decisions[-1] if decisions else None
        completed_queries = [event for event in turn_events if event["kind"] == "query_completed"
                             and start_event["seq"] <= event["seq"] < end_event["seq"]]
        query_seconds = sum(event["data"]["elapsed_seconds"] for event in completed_queries)
        san = game.get("san", [])[ply] if ply < len(game.get("san", [])) else None
        row = {
            "move_number": move_number,
            "ply": ply,
            "move": f"{move_number}{'...' if side == 'black' else '.'} {san or '(turn ended)'}",
            "san": san,
            "observed_utc": observed_utc,
            "observation_recorded_utc": start_event["utc"],
            "decision_utc": decision["utc"] if decision else None,
            "charged_through_utc": endpoint,
            "settlement_recorded_utc": end_event["utc"],
            "charge_event_seq": end_event["seq"],
            "settlement_kind": end_event["kind"],
            "charged_seconds": end["charged_seconds"],
            "refunded_seconds": refunds.get(ply, 0),
            "net_charged_seconds": end["charged_seconds"] - refunds.get(ply, 0),
            "settled_wall_seconds": elapsed_wall,
            "chargeable_wall_seconds": active_wall,
            "excluded_pause_seconds": elapsed_wall - active_wall,
            "charged_minus_active_wall_seconds": end["charged_seconds"] - active_wall,
            "query_count": len(completed_queries),
            "query_errors": sum(bool(event["data"].get("error")) for event in completed_queries),
            "query_wall_seconds": query_seconds,
            "nonquery_remainder_seconds": end["charged_seconds"] - query_seconds,
            "observation_to_record_seconds": excluding_pauses(observed_utc, start_event["utc"], pauses),
            "record_to_decision_seconds": excluding_pauses(start_event["utc"], decision["utc"], pauses) if decision else None,
            "decision_to_charge_endpoint_seconds": excluding_pauses(decision["utc"], endpoint, pauses) if decision else None,
            "charge_endpoint_to_record_seconds": seconds(endpoint, end_event["utc"]),
            "excluded_verification_seconds": end.get("excluded_verification_seconds", 0),
            "uncertainty": start.get("uncertainty", []) + end.get("uncertainty", []),
        }
        rows.append(row)
    blocks = []
    for decade in sorted({(row["move_number"] - 1) // 10 for row in rows}):
        block_rows = [row for row in rows if (row["move_number"] - 1) // 10 == decade]
        blocks.append({"move_range": [block_rows[0]["move_number"], block_rows[-1]["move_number"]],
                       **summarize(block_rows)})
    return {
        "schema": 1,
        "player_side": side,
        "through_move_requested": through_move,
        "last_settled_move_included": rows[-1]["move_number"] if rows else None,
        "initial_allowance_seconds": events[0]["data"].get("total_seconds"),
        "excluded_unsettled_turns": unsettled,
        "totals": summarize(rows),
        "ten_move_blocks": blocks,
        "top_ten_by_charge": sorted(rows, key=lambda row: (-row["charged_seconds"], row["ply"]))[:10],
        "turns": rows,
        "caveats": [
            "Only settled own turns are included. Unsettled elapsed time is not estimated, even when a documentary pause note is present.",
            "The saved charged_seconds is authoritative. User refunds are shown separately and are never inferred from notes.",
            "Timestamp stages exclude only explicit user_time_extension pause/resumption intervals; these exclusions are reported separately from refunds.",
            "Query time is completed query wall time recorded by the clock, including orchestration and failed queries; it is not pure search CPU time.",
            "The nonquery remainder includes model deliberation, commentary, command overhead and UI work; their exact individual costs are not logged.",
            "Observation-to-recording includes any work before journal entry, including deliberation; it is not a tool-latency measurement.",
            "The last decision-to-charge-endpoint interval includes move entry and any further review or interruptions; it is not solely browser latency.",
            "Timestamp stage intervals and query time overlap and must not be added together. UTC offset differences are normalized.",
            "Late verification entry is not extra charged time when an earlier submitted timestamp is the saved charge endpoint. Some late entry work may fall within the next own turn.",
            "An explicit through-move cutoff excludes later settled turns. This report never reads the current live clock or changes any journal.",
        ],
    }


def duration(value):
    if value is None:
        return "unavailable"
    sign = "-" if value < 0 else ""
    minutes, secs = divmod(abs(value), 60)
    return f"{sign}{int(minutes)}:{secs:04.1f}"


def markdown(report):
    totals = report["totals"]
    lines = ["# Astra own-turn time audit", "",
             f"Settled moves through **{report['last_settled_move_included']}**, playing **{report['player_side']}**. "
             f"{totals['turn_count']} own turns; **{duration(totals['charged_seconds'])}** raw charged time "
             f"and **{duration(totals['net_charged_seconds'])}** after recorded refunds.", "",
             f"Completed queries consumed **{duration(totals['query_wall_seconds'])}** "
             f"({totals['query_share_percent']:.1f}% of charged time, {totals['query_count']} queries). "
             f"The remaining **{duration(totals['nonquery_remainder_seconds'])}** is not individually attributed.", "",
             f"Explicitly excluded pause/resumption intervals within these settled turns: "
             f"**{duration(totals['excluded_pause_seconds'])}**.", "",
             f"Mean move: **{duration(totals['mean_charged_seconds'])}**; median: "
             f"**{duration(totals['median_charged_seconds'])}**. "
             f"{totals['turns_over_90_seconds']} turns exceeded 90 seconds; "
             f"{totals['turns_over_120_seconds']} exceeded 120 seconds.", "",
             "## Largest charges", "",
             "Intervals overlap with query time; do not add the columns.", "",
             "| Move | Charged | Queries | Observation to entry | Decision to submission/end |",
             "|---|---:|---:|---:|---:|"]
    for row in report["top_ten_by_charge"]:
        lines.append(f"| {row['move']} | {duration(row['charged_seconds'])} | "
                     f"{duration(row['query_wall_seconds'])} | {duration(row['observation_to_record_seconds'])} | "
                     f"{duration(row['decision_to_charge_endpoint_seconds'])} |")
    lines += ["", "## Ten-move blocks", "",
              "These are mechanical blocks, not inferred opening/middlegame/endgame boundaries.", "",
              "| Moves | Charged | Query wall | Other remainder | Mean per move |",
              "|---|---:|---:|---:|---:|"]
    for block in report["ten_move_blocks"]:
        lo, hi = block["move_range"]
        lines.append(f"| {lo}-{hi} | {duration(block['charged_seconds'])} | {duration(block['query_wall_seconds'])} | "
                     f"{duration(block['nonquery_remainder_seconds'])} | {duration(block['mean_charged_seconds'])} |")
    lines += ["", "## Evidence and limits", ""]
    lines.extend(f"- {caveat}" for caveat in report["caveats"])
    lines += ["", f"Total observation-to-entry interval: {duration(totals['observation_to_record_seconds'])}. "
              f"Total last-decision-to-charge-endpoint interval: {duration(totals['decision_to_charge_endpoint_seconds'])} "
              f"across {totals['turns_with_decision_timestamps']} turns with a recorded decision.", ""]
    if "sources" in report:
        lines += ["Source snapshot SHA-256:", "", "```json", json.dumps(report["sources"], indent=2), "```", ""]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", required=True, help="Game slug under engine-games, or a game directory")
    parser.add_argument("--through-move", type=int, help="Include settled own moves up to this full move number")
    parser.add_argument("--output-prefix", type=Path, required=True, help="Write PREFIX.json and PREFIX.md")
    args = parser.parse_args(argv)
    if args.through_move is not None and args.through_move < 1:
        parser.error("--through-move must be positive")
    folder = Path(args.game)
    if not folder.is_dir():
        folder = ROOT / "engine-games" / args.game
    raw_clock = (folder / "clock.jsonl").read_bytes()
    raw_game = (folder / "game.json").read_bytes()
    events = [json.loads(line) for line in raw_clock.decode("utf-8").splitlines() if line.strip()]
    report = audit(events, json.loads(raw_game), args.through_move)
    report["sources"] = {
        "game": folder.name,
        "clock_sha256": hashlib.sha256(raw_clock).hexdigest(),
        "game_sha256": hashlib.sha256(raw_game).hexdigest(),
        "last_clock_seq_in_snapshot": events[-1]["seq"],
    }
    args.output_prefix.parent.mkdir(parents=True, exist_ok=True)
    for suffix, content in ((".json", json.dumps(report, indent=2, ensure_ascii=False) + "\n"),
                            (".md", markdown(report))):
        target = args.output_prefix.with_suffix(suffix)
        if target.resolve() in {(folder / "game.json").resolve(), (folder / "clock.jsonl").resolve()}:
            raise ValueError("Output must not overwrite a source journal")
        target.write_text(content, encoding="utf-8")
        print(target)
    print(json.dumps(report["totals"], indent=2))


if __name__ == "__main__":
    main()
