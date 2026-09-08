"""Export historical evaluations for verified player moves; never run search.

Use --game SLUG --output PATH from any directory. Input is the saved journal
and its recorded query results under this repository. Requires only Python's
standard library. A pending choice is not part of the verified move sequence.
"""

from pathlib import Path
import argparse
import hashlib
import json
import re


ROOT = Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def extract(game_slug, *, root=ROOT):
    """Return the replay evaluation schema for a saved manual-journal game."""
    require(isinstance(game_slug, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", game_slug),
            "Game slug must contain only letters, numbers, - and _")
    root = Path(root).resolve()

    def relative(path):
        return path.relative_to(root).as_posix()

    def source_path(name):
        path = (root / Path(name.replace("\\", "/"))).resolve()
        require(path.is_relative_to(root), "Query source must remain inside the repository")
        return path

    game_path = root / "engine-games" / game_slug / "game.json"
    game = read(game_path)
    player_side = game.get("player_side", "white")
    require(player_side in ("white", "black"), "Journal player_side must be white or black")
    opponent_side = "black" if player_side == "white" else "white"
    own_parity = 0 if player_side == "white" else 1
    winning_result = "1-0" if player_side == "white" else "0-1"
    require(len(game["san"]) == len(game["uci"]) and len(game["fens"]) == len(game["uci"]) + 1,
            "Journal UCI, SAN and FEN sequence lengths disagree")
    rows = []
    used = {game_path}
    seen = set()
    for turn in game["turns"]:
        ply = turn["ply"]
        require(type(ply) is int and ply >= 0 and ply % 2 == own_parity,
                f"Expected nonnegative {player_side.title()}-turn journal plies")
        # Choices and even submission attempts do not establish an accepted move.
        if ply >= len(game["uci"]) or not turn.get("verified_utc"):
            continue
        require(ply not in seen, f"Duplicate verified own turn at ply {ply}")
        seen.add(ply)
        chosen = turn["selected_move"]
        require(chosen == game["uci"][ply] and turn["selected_san"] == game["san"][ply],
                f"Selected move disagrees with verified journal at ply {ply}")
        before, after = game["fens"][ply:ply + 2]
        require(len(before.split()) == 6 and before.split()[1] == player_side[0]
                and len(after.split()) == 6 and after.split()[1] == opponent_side[0],
                f"Expected {player_side.title()} pre-move and {opponent_side.title()} post-move FEN at ply {ply}")
        require(turn["move"] == int(before.split()[5]),
                f"Turn number disagrees with pre-move FEN at ply {ply}")
        row = {
            "move": turn["move"],
            "ply": ply,
            "san": turn["selected_san"],
            "uci": chosen,
            # Preserve the existing White-game row schema and chart evidence.
            "preceding_black_san" if player_side == "white" else "preceding_opponent_san": game["san"][ply - 1] if ply else None,
            "following_black_san" if player_side == "white" else "following_opponent_san": game["san"][ply + 1] if ply + 1 < len(game["san"]) else None,
            "pre_move_fen": before,
            "post_move_fen": after,
            "score_cp": None,
            "score_pawns": None,
            "mate_in_plies": None,
            "completed_depth": None,
            "score_kind": "not_recorded",
            "source": None,
            "query_seconds": None,
            "query_timed_out": None,
            "chosen_rank": None,
            "top_recommendation": None,
            "proof": None,
            "assessment": turn["assessment"],
            "initial_candidate": turn["initial_candidate"],
            "audit": [],
        }

        # Journal query order is the original chronological query order. A later
        # query replaces an earlier match only if it really evaluated this move.
        for name in turn["queries"]:
            query_path = source_path(name)
            query = read(query_path)
            used.add(query_path)
            if query.get("kind") != "analysis":
                continue
            if query.get("start_fen") != before or query.get("turn") != player_side:
                row["audit"].append({"source": relative(query_path), "excluded": "different starting position or side"})
                continue
            if query.get("completed_depth", 0) < 1 or query.get("fallback", False):
                row["audit"].append({"source": relative(query_path), "excluded": "no completed search iteration"})
                continue
            matches = [candidate for candidate in query["candidates"] if candidate["root_move"] == chosen]
            if not matches:
                row["audit"].append({"source": relative(query_path), "excluded": "chosen move absent from returned candidates"})
                continue
            require(len(matches) == 1, f"Duplicate selected root move in {relative(query_path)}")
            candidate = matches[0]
            require(candidate["fens"][:2] == [before, after]
                    and candidate["uci"][:1] == [chosen]
                    and candidate["san"][:1] == [row["san"]],
                    f"Selected candidate timeline disagrees with actual move in {relative(query_path)}")
            require(candidate["score_is_exact_for_search"] is True
                    and candidate["depth"] == query["completed_depth"],
                    f"Selected candidate is not an exact completed-depth result in {relative(query_path)}")
            top = min(query["candidates"], key=lambda c: c["rank"])
            mate = candidate["mate_in_plies"]
            row.update({
                "score_cp": candidate["score_cp"],
                "score_pawns": candidate["score_cp"] / 100 if mate is None else None,
                "mate_in_plies": mate,
                "completed_depth": query["completed_depth"],
                "score_kind": "search_mate" if mate is not None else "search_estimate",
                "source": relative(query_path),
                "query_seconds": query["elapsed_seconds"],
                "query_timed_out": query["timed_out"],
                "chosen_rank": candidate["rank"],
                "top_recommendation": {
                    "san": top["san"][0], "uci": top["root_move"],
                    "score_cp": top["score_cp"], "mate_in_plies": top["mate_in_plies"],
                },
                "principal_variation_san": candidate["san"],
            })
            row["audit"].append({"source": relative(query_path), "matched": "exact actual pre-move FEN, selected root move, and actual post-move FEN"})

        # A proof after the selected move has different semantics from a numeric
        # minimax evaluation. Preserve it separately rather than inventing cp.
        for name in turn["queries"]:
            query_path = source_path(name)
            query = read(query_path)
            if query.get("kind") != "goal_probe":
                continue
            request_path = query_path.with_name(query_path.stem + ".request.json")
            request = read(request_path)
            used.add(request_path)
            if (query.get("start_fen") == after
                    and request.get("fen") == before
                    and request.get("after") == [chosen]
                    and query.get("goal") == {"type": "checkmate", "side": player_side}
                    and query.get("proof_status") == "forced"):
                row["proof"] = {
                    "source": relative(query_path),
                    "request_source": relative(request_path),
                    "status": "forced",
                    "horizon_plies_from_post_move_position": query["horizon_plies"],
                    "completed_depth": query["proof_completed_depth"],
                    "side_to_move": opponent_side,
                }
                if row["source"] is None:
                    row["source"] = relative(query_path)
                    row["score_kind"] = "forced_mate_proof"
                row["audit"].append({"source": relative(query_path), "matched": "goal proof starts at exact actual post-move FEN; request starts at exact pre-move FEN and applies only the chosen move"})

        if ply == len(game["uci"]) - 1 and game.get("termination") == "checkmate":
            require(row["san"].endswith("#") and game["result"] == winning_result,
                    f"Final {player_side.title()} move conflicts with recorded checkmate result")
            # Keep any contemporaneous search as evidence. With no numeric
            # search, the observed terminal result supplies the label directly.
            if row["score_cp"] is None:
                row["score_kind"] = "actual_checkmate"
                row["source"] = relative(game_path)
            row["audit"].append({"source": relative(game_path), "matched": "last verified move and recorded checkmate termination"})
        rows.append(row)

    result = {
        "title": f"{game['white']} vs. {game['black']} — game {game['round']} evaluation history",
        "game_source": relative(game_path),
        "white": game["white"], "black": game["black"],
        "player_side": player_side,
        "score_perspective": player_side,
        "date": game["date"], "result": game["result"],
        "semantics": {
            "primary_series": "The most recent completed in-game search that returned the move actually chosen, from the exact actual position before that move. The score estimates the continuation beginning with the chosen move; it is not a fresh search performed after the move.",
            "perspective": f"{player_side.title()} ({game[player_side]}); positive favors {player_side.title()}.",
            "units": "100 centipawns = one pawn equivalent. These are this simple engine's heuristic values, not win probabilities or an external engine's assessments.",
            "depth": "Completed nominal search depth in plies, including the chosen root move. Quiescence can extend the line. Depth and time limits varied across moves.",
            "mate_scores": "When mate_in_plies is non-null, score_cp is an internal mate encoding, not a material advantage; score_pawns is null. Mate distance is measured from the pre-move search root, including the chosen move.",
            "missing_numeric_values": "A verified move with no qualifying completed search has no numeric evaluation. A goal proof or observed checkmate does not invent a numeric value. Pending moves are omitted; missing values are never filled using later scores or new searches.",
            "proof": f"A recorded forced checkmate goal proof starts at the actual post-move position with {opponent_side.title()} to move. Its horizon counts further plies from that board and covers every legal defense; it is separate from a numeric search evaluation.",
            "interpretation": f"Changes combine the effect of intervening {opponent_side.title()} moves with search horizon and evaluation effects; they are not isolated measures of the quality of {player_side.title()}'s moves.",
            "new_searches_run": False,
        },
        "rows": rows,
        "source_sha256": {relative(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(used)},
    }
    return result


def write_export(game_slug, output_path):
    result = extract(game_slug)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Exported {len(result['rows'])} verified {result['player_side'].title()} moves to {output_path}")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", required=True, help="Directory slug under engine-games")
    parser.add_argument("--output", required=True, type=Path, help="Output JSON path")
    args = parser.parse_args(argv)
    try:
        write_export(args.game, args.output)
    except (OSError, ValueError, TypeError, KeyError) as error:
        parser.exit(2, f"Error: {error}\n")


if __name__ == "__main__":
    main()
