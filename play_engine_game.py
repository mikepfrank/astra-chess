"""Manual game journal. Never controls a browser or chooses a move.

Choose a new --game SLUG, then init, turn, candidate, query, choose, submit,
and verify. An attempted/rejected click never advances the game or resets time.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from types import SimpleNamespace

from astra_chess import write_json, run_query
from astra_engine.clock import (clock_status, create_game_clock, finish_game_clock,
                               mark_critical, observe_turn, record_event, verify_submission)
from astra_engine.rules import Position, START_FEN, square_name

ROOT = Path(__file__).resolve().parent


def now():
    return datetime.now(timezone.utc).isoformat()


def game_directory(slug):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", slug):
        raise ValueError("--game must contain only letters, numbers, - and _")
    return ROOT / "engine-games" / slug


def load(game):
    return json.loads((game / "game.json").read_text(encoding="utf-8"))


def save(game, journal):
    write_json(game / "game.json", journal)


def position(journal):
    return Position.from_fen(journal["fens"][-1])


def own_side(journal):
    """Legacy journals were all played as White; new journals state the side."""
    side = journal.get("player_side", "white")
    if side not in ("white", "black"):
        raise ValueError("Journal player_side must be white or black")
    return 0 if side == "white" else 1


def add(journal, uci):
    pos = position(journal)
    move = pos.parse_uci(uci)
    journal["san"].append(pos.san(move))
    journal["uci"].append(move.uci())
    journal["fens"].append(pos.play(move).fen())


def active_turn(game, journal):
    status = clock_status(game / "clock.jsonl")
    if position(journal).turn != own_side(journal):
        raise ValueError("Journal does not show an own turn")
    if status["active_ply"] != len(journal["uci"]):
        raise ValueError("Observe this own turn before recording decisions or queries")
    if not journal["turns"] or journal["turns"][-1]["ply"] != status["active_ply"]:
        raise ValueError("Clock and journal disagree; inspect the ledger before continuing")
    return journal["turns"][-1], status


def make_query(game, journal, args):
    turn, _ = active_turn(game, journal)
    if not turn.get("initial_candidate"):
        raise ValueError("Record an initial candidate before searching: candidate --move UCI")
    number = turn["move"]
    # Keep failed requests as evidence too, without reusing their filenames.
    n = len(list(game.glob(f"turn-{number:02d}-query-*.request.json"))) + 1
    opponent = journal["black" if own_side(journal) == 0 else "white"]
    query = {
        "label": f'{opponent} game {journal["round"]}, move {number}: ' + (args.label or turn["concern"]),
        "mode": "probe" if args.goal else "analyze", "fen": position(journal).fen(),
        "history_fens": journal["fens"][:-1], "depth": args.depth,
        "seconds": args.seconds, "candidates": args.candidates, "diagnostics": args.diagnostics,
    }
    if args.after:
        query["after"] = args.after.split(",")
    if args.root_moves:
        query["root_moves"] = args.root_moves.split(",")
    if args.goal:
        query["goal"] = json.loads(args.goal)
        query["proof_only"] = not args.witness
    elif args.proof_only or args.witness:
        raise ValueError("--proof-only/--witness require --goal")
    if args.evaluation:
        query["evaluation"] = json.loads(args.evaluation)
    if args.threat_extensions:
        query["threat_extensions"] = args.threat_extensions
    stem = game / f"turn-{number:02d}-query-{n}"
    request, output = stem.with_suffix(".request.json"), stem.with_suffix(".json")
    write_json(request, query)
    run_query(SimpleNamespace(request=request, output=output,
              html=stem.with_suffix(".html") if args.html else None,
              session=None, game_clock=game / "clock.jsonl"))
    turn["queries"].append(str(output.relative_to(ROOT)))
    save(game, journal)


def verify_move(game, journal, args):
    turn, _ = active_turn(game, journal)
    pending = journal.get("pending")
    if not pending:
        raise ValueError("No chosen move to verify")
    if args.move and args.move != pending["uci"]:
        raise ValueError("Verified move differs from chosen move; record the correct choice first")
    position(journal).parse_uci(pending["uci"])
    status = verify_submission(game / "clock.jsonl", len(journal["uci"]), pending["uci"],
                               submitted_utc=args.submitted_utc, verified_utc=args.verified_utc,
                               uncertainty=args.note)
    add(journal, pending["uci"])
    turn["submitted_utc"] = args.submitted_utc or pending.get("submitted_utc")
    turn["verified_utc"] = args.verified_utc or now()
    turn["verification_clock"] = status
    journal["pending"] = None
    save(game, journal)
    return status


def pgn(journal):
    header = {"Event": journal["event"], "Site": "https://www.chess.com/",
              "Date": journal["date"], "Round": str(journal["round"]),
              "White": journal["white"], "Black": journal["black"]}
    for side in ("white", "black"):
        if journal.get(side + "_elo") is not None:
            header[side.title() + "Elo"] = str(journal[side + "_elo"])
    header.update(Result=journal["result"], Termination=journal["termination"], TimeControl="-")
    def escaped(value):
        return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
    text = "\n".join(f'[{key} "{escaped(value)}"]' for key, value in header.items()) + "\n\n"
    for i, san in enumerate(journal["san"]):
        text += (f"{i//2+1}. " if i % 2 == 0 else "") + san + " "
    return text + journal["result"] + "\n"


def parser():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=["init", "turn", "candidate", "query", "choose", "submit",
                                       "reject", "verify", "critical", "status", "finish"])
    ap.add_argument("--game", required=True, help="Explicit new directory name under engine-games for each trial")
    ap.add_argument("--opponent", help="Observed opponent move in SAN")
    ap.add_argument("--opponent-name", default="Wally")
    ap.add_argument("--opponent-elo", type=int, default=1800)
    ap.add_argument("--side", choices=["white", "black"], default="white",
                    help="Astra's color for init; stored in the journal (default white)")
    ap.add_argument("--round", type=int, help="Required for init; original experiment game number")
    ap.add_argument("--initial")
    ap.add_argument("--concern", default="")
    ap.add_argument("--observed-utc")
    ap.add_argument("--submitted-utc")
    ap.add_argument("--verified-utc")
    ap.add_argument("--move")
    ap.add_argument("--note", default="")
    ap.add_argument("--label", default="")
    ap.add_argument("--seconds", type=float, default=15)
    ap.add_argument("--depth", type=int, default=8)
    ap.add_argument("--candidates", type=int, default=3)
    ap.add_argument("--root-moves")
    ap.add_argument("--after")
    ap.add_argument("--goal")
    proof = ap.add_mutually_exclusive_group()
    proof.add_argument("--proof-only", action="store_true", help="Default for a goal: all time on adversarial proof")
    proof.add_argument("--witness", action="store_true", help="Also search cooperative examples for a goal")
    ap.add_argument("--diagnostics", action=argparse.BooleanOptionalAction, default=True)
    ap.add_argument("--evaluation", help="Optional evaluation flags as a JSON object")
    ap.add_argument("--threat-extensions", type=int, default=0)
    ap.add_argument("--html", action="store_true")
    ap.add_argument("--result")
    ap.add_argument("--termination", default="normal")
    ap.add_argument("--png", action="store_true")
    ap.add_argument("--critical", action="store_true")
    ap.add_argument("--clock-mode", choices=["game", "move"], default="game")
    ap.add_argument("--time-control", choices=["fixed", "classical"], default="fixed",
                    help="New-game clock: fixed legacy allowance, or 90min/40 +30min with 30s per verified own move")
    ap.add_argument("--game-seconds", type=float, default=3600)
    ap.add_argument("--move-seconds", type=float, default=120)
    ap.add_argument("--reserve", type=float, default=40)
    ap.add_argument("--own-time-only", action=argparse.BooleanOptionalAction, default=True,
                    help="Settle verified moves at submission, excluding opponent/confirmation time (default)")
    return ap


def main(argv=None):
    args = parser().parse_args(argv)
    game = game_directory(args.game)
    clock = game / "clock.jsonl"
    if args.command == "init":
        if args.round is None or args.round < 1:
            raise ValueError("init requires a positive --round")
        if game.exists():
            raise ValueError("Game directory already exists; choose a new --game to preserve earlier evidence")
        policy = dict(mode=args.clock_mode, total_seconds=args.game_seconds,
                      move_seconds=args.move_seconds, reserve_seconds=args.reserve,
                      charge_to_submission=args.own_time_only)
        if args.time_control == "classical":
            if args.clock_mode != "game":
                raise ValueError("The classical time control requires --clock-mode game")
            policy.update(total_seconds=5400, increment_seconds=30, stage_moves=40,
                          stage_seconds=1800, ordinary_seconds=120, critical_seconds=240)
        status = create_game_clock(clock, **policy)
        players = dict(white="Astra (Ultra)", black=args.opponent_name, black_elo=args.opponent_elo)
        if args.side == "black":
            players = dict(white=args.opponent_name, white_elo=args.opponent_elo, black="Astra (Ultra)")
        save(game, dict(event="Astra Search Lab trial", date=datetime.now(timezone.utc).strftime("%Y.%m.%d"),
             round=args.round, player_side=args.side, **players,
             result="*", uci=[], san=[], fens=[START_FEN], turns=[], pending=None,
             clock_file="clock.jsonl", clock_policy=status))
        print(json.dumps(status, indent=2))
        return
    if not clock.exists():
        raise ValueError("This game has no append-only clock; historical games are preserved. Initialize a new --game")
    journal = load(game)
    if args.command != "status" and journal["result"] != "*":
        raise ValueError("Game has finished; its evidence is immutable through this helper")
    if args.command == "turn":
        if journal.get("pending"):
            raise ValueError("Verify the previous submitted move before observing the next turn")
        if clock_status(clock)["active_ply"] is not None:
            raise ValueError("An own turn is active; use candidate/query/critical without resetting it")
        if args.opponent:
            pos = position(journal)
            if pos.turn == own_side(journal):
                raise ValueError("Journal does not expect an opponent move")
            matches = [m for m in pos.legal_moves() if pos.san(m).rstrip("+#") == args.opponent.rstrip("+#")]
            if len(matches) != 1:
                raise ValueError("Observed SAN must identify exactly one legal move: " + args.opponent)
            add(journal, matches[0].uci())
        pos = position(journal)
        if pos.turn != own_side(journal):
            raise ValueError("Expected Astra's side to move; provide the observed opponent SAN")
        if args.initial:
            pos.parse_uci(args.initial)
        observed = args.observed_utc or now()
        status = observe_turn(clock, len(journal["uci"]), observed_utc=observed,
                              initial_candidate=args.initial, concern=args.concern, critical=args.critical)
        journal["turns"].append(dict(move=pos.fullmove, ply=len(journal["uci"]), observed_utc=observed,
                                  initial_candidate=args.initial, concern=args.concern, queries=[]))
        save(game, journal)
        print(pos.ascii())
        print(json.dumps(status, indent=2))
    elif args.command == "candidate":
        turn, _ = active_turn(game, journal)
        if turn.get("initial_candidate"):
            raise ValueError("Initial candidate already recorded; use choose for a revised decision")
        if not args.move:
            raise ValueError("candidate requires --move UCI")
        move = position(journal).parse_uci(args.move)
        record_event(clock, "initial_candidate", move=move.uci())
        turn["initial_candidate"] = move.uci()
        save(game, journal)
    elif args.command == "query":
        make_query(game, journal, args)
    elif args.command == "choose":
        turn, status = active_turn(game, journal)
        if not args.move:
            raise ValueError("choose requires --move UCI")
        pos = position(journal)
        move = pos.parse_uci(args.move)
        record_event(clock, "decision", move=move.uci(), note=args.note)
        journal["pending"] = dict(uci=move.uci(), san=pos.san(move))
        turn.update(selected_move=move.uci(), selected_san=pos.san(move), assessment=args.note,
                    changed_candidate=move.uci() != turn.get("initial_candidate"), decision_clock=status)
        save(game, journal)
        child = pos.play(move)
        print(pos.san(move))
        print(child.ascii())
        print(json.dumps(status, indent=2))
        if args.png:
            from board_scratchpad import render
            number = f"{pos.fullmove}." if pos.turn == 0 else f"{pos.fullmove}..."
            render({"board": {square_name(i): pc for i, pc in enumerate(child.board) if pc != "."},
                    "last_edits": [move.uci()]}, game / "images" / "candidate.png", f"{number} {pos.san(move)} — candidate")
    elif args.command in ("submit", "reject"):
        active_turn(game, journal)
        pending = journal.get("pending")
        if not pending:
            raise ValueError("Choose a legal move before recording submission or rejection")
        if args.command == "submit":
            submitted = args.submitted_utc or now()
            status = record_event(clock, "submission", move=pending["uci"], submitted_utc=submitted, note=args.note)
            pending["submitted_utc"] = submitted
        else:
            status = record_event(clock, "submission_rejected", move=pending["uci"], note=args.note)
            # Rejected choice is discarded; elapsed time and prior evidence remain.
            journal["pending"] = None
        save(game, journal)
        print(json.dumps(status, indent=2))
    elif args.command == "verify":
        print(json.dumps(verify_move(game, journal, args), indent=2))
    elif args.command == "critical":
        print(json.dumps(mark_critical(clock, args.concern or args.note), indent=2))
    elif args.command == "status":
        print(position(journal).ascii())
        print(json.dumps(clock_status(clock), indent=2))
    elif args.command == "finish":
        if args.result not in ("1-0", "0-1", "1/2-1/2"):
            raise ValueError("Final result required")
        if journal.get("pending"):
            raise ValueError("Pending chosen move is unverified; verify it or reject it before finishing")
        if args.opponent:
            pos = position(journal)
            if pos.turn == own_side(journal) or clock_status(clock)["active_ply"] is not None:
                raise ValueError("Final opponent move requires a verified own move and no active own clock")
            matches = [m for m in pos.legal_moves() if pos.san(m).rstrip("+#") == args.opponent.rstrip("+#")]
            if len(matches) != 1:
                raise ValueError("Observed SAN must identify exactly one legal move: " + args.opponent)
            add(journal, matches[0].uci())
        status = finish_game_clock(clock, args.result, reason=args.termination)
        journal.update(result=args.result, termination=args.termination, final_clock=status)
        save(game, journal)
        text = pgn(journal)
        (game / "game.pgn").write_text(text, encoding="utf-8")
        print(text)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, TypeError, KeyError) as error:
        parser().exit(2, f"Error: {error}\n")
