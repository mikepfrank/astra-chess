"""Validate the saved PGN and embed its positions in an offline replay page.

Build dependency: chess==1.11.2 (rules and notation only; no chess engine).
The generated HTML has no dependencies or network requests.
"""
from pathlib import Path
import argparse
from datetime import datetime
import html
import io
import json
import math
import sys

ROOT = Path(__file__).resolve().parent
REPLAY_DIR = ROOT / "replays"
sys.path.insert(0, str(ROOT / ".replay-deps"))
import chess
import chess.pgn


def replay_output_path(path):
    """Bare output names belong to replays; explicit directories are honored."""
    path = Path(path)
    return REPLAY_DIR / path if not path.is_absolute() and path.parent == Path(".") else path


def normalized_fen(fen):
    """Compare full positions while accepting FEN's two en-passant conventions.

    The engine emits the raw double-push square; python-chess normally omits it
    when no legal en-passant capture exists. All other FEN fields still match.
    """
    board = chess.Board(fen)
    if not board.is_valid():
        raise ValueError(f"Invalid evaluation FEN: {fen}")
    return board.fen()


def attach_evaluations(frames, path, *, player_side=None):
    """Attach audited choices in the recorded player's score perspective."""
    source = json.loads(path.read_text(encoding="utf-8"))
    side = source.get("player_side", "white")
    if (side not in ("white", "black")
            or source.get("score_perspective", side) != side
            or player_side is not None and side != player_side):
        raise ValueError("Evaluation player side or score perspective disagrees with the replay")
    own, opponent = side.title(), "Black" if side == "white" else "White"
    rows = source.get("rows")
    if not isinstance(rows, list):
        raise ValueError("Evaluation data must contain a rows list")
    for frame in frames:
        frame["evaluation"] = None
    seen = set()
    for row in rows:
        ply = row.get("ply")
        if type(ply) is not int or not 0 <= ply < len(frames) - 1 or ply in seen:
            raise ValueError(f"Invalid or duplicate evaluation pre-move ply: {ply}")
        seen.add(ply)
        before, after = frames[ply], frames[ply + 1]
        move = after["move"]
        if (move["color"] != side or row.get("move") != move["number"]
                or row.get("uci") != move["uci"] or row.get("san") != move["san"]):
            raise ValueError(f"Evaluation move does not match the replay at ply {ply + 1}")
        for field, frame in (("pre_move_fen", before), ("post_move_fen", after)):
            if normalized_fen(row[field]) != normalized_fen(frame["fen"]):
                raise ValueError(f"Evaluation {field} does not match at ply {ply + 1}")
        kind = row.get("score_kind")
        cp, pawns, mate = (row.get(k) for k in ("score_cp", "score_pawns", "mate_in_plies"))
        depth = row.get("completed_depth")
        move_label = f"{move['number']}{'.' if side == 'white' else '…'} {move['san']}"
        record = {"kind": kind, "forMove": move_label, "source": row.get("source"),
                  "scoreCp": None, "depth": depth, "mateMovesRemaining": None}
        if depth is not None and (type(depth) is not int or depth < 0):
            raise ValueError(f"Invalid evaluation depth for {move_label}")
        if kind == "search_estimate":
            if (type(cp) not in (int, float) or not math.isfinite(cp) or abs(cp) >= 29000
                    or type(pawns) not in (int, float) or not math.isfinite(pawns)
                    or not math.isclose(pawns, cp / 100, abs_tol=1e-9)
                    or mate is not None or not depth):
                raise ValueError(f"Invalid numeric search estimate for {move_label}")
            record.update(scoreCp=cp, label=f"{cp / 100:+.2f} pawns",
                          detail=f"For {move_label} · Pre-move search · Depth {depth} plies · Positive favors {own}",
                          note="Calculated before this move to assess its continuation; not a fresh evaluation of the displayed board.")
        elif kind == "search_mate":
            if (type(mate) is not int or mate == 0 or not depth or pawns is not None
                    or type(cp) is not int or abs(cp) < 29000 or (cp > 0) != (mate > 0)
                    or (mate > 0 and mate % 2 != 1) or (mate < 0 and mate % 2 != 0)):
                raise ValueError(f"Invalid mate search result for {move_label}")
            # Root distance includes the player's move now on the board. Count the
            # mating side's remaining turns, rather than displaying 299.95 pawns.
            remaining = (abs(mate) - 1 + (mate < 0)) // 2
            if remaining == 0 and not after["mate"]:
                raise ValueError(f"Mate-in-one search disagrees with the board for {move_label}")
            mating_side = opponent if mate < 0 else own
            record.update(mateMovesRemaining=remaining,
                          label="Checkmate" if after["mate"] else f"{mating_side + ' mates' if mate < 0 else 'Mate'} in {remaining}",
                          detail=f"For {move_label} · {mating_side} moves remaining · Search depth {depth} plies",
                          note=f"{mating_side} moves remaining from this displayed position. The search counted {abs(mate)} plies from before {move_label}, including that move.")
        elif kind == "forced_mate_proof":
            proof = row.get("proof") or {}
            horizon = proof.get("horizon_plies_from_post_move_position")
            proof_depth = proof.get("completed_depth")
            if (cp is not None or pawns is not None or mate is not None
                    or proof.get("status") != "forced" or proof.get("side_to_move") != after["turn"]
                    or type(horizon) is not int or horizon < 2
                    or type(proof_depth) is not int or not 2 <= proof_depth <= horizon):
                raise ValueError(f"Invalid forced mate proof for {move_label}")
            # Iterative proof may finish before the requested horizon. With
            # The opponent moves first; the player can mate only on an even ply.
            record.update(mateMovesRemaining=proof_depth // 2, label=f"Mate in {proof_depth // 2}",
                          detail=f"For {move_label} · {own} moves remaining, at most · Goal proof, {proof_depth} plies after this move",
                          note=f"{own} moves remaining, at most. The saved goal probe checked every legal {opponent} defense from this displayed position. No numeric score was recorded.")
        elif kind == "not_recorded":
            if any(value is not None for value in (cp, pawns, mate, depth, row.get("proof"))):
                raise ValueError(f"Missing evaluation contains a score or proof for {move_label}")
            record.update(label="No recorded evaluation",
                          detail=f"For {move_label} · No qualifying saved search result",
                          note=f"This {own} move was verified in the game, but no saved search returned an evaluation for this choice from its actual starting position. No score has been filled in.")
        elif kind == "actual_checkmate":
            if not after["mate"] or any(value is not None for value in (cp, pawns, mate, depth)):
                raise ValueError(f"Actual checkmate entry disagrees with the board for {move_label}")
            record.update(label="Checkmate", detail=f"{move_label} · {own} wins",
                          note="The recorded game ended here. No engine search score was needed for the final move.")
        else:
            raise ValueError(f"Unknown evaluation kind for {move_label}: {kind}")
        after["evaluation"] = record
    return {"perspective": side, "recordedChoices": len(rows),
            "description": f"Historical engine results for Astra's chosen moves. Positive favors {own}. Scores were calculated before each {own} move; {opponent} moves have no recorded evaluation.",
            "mateConvention": f"Mate labels count the mating side's moves remaining from the displayed board. Search-root mate distances include the chosen {own} move."}


def build(pgn_path, output_path, subtitle=None, ending=None, evaluations=None):
    output_path = replay_output_path(output_path)
    pgn = pgn_path.read_text(encoding="utf-8")
    game = chess.pgn.read_game(io.StringIO(pgn))
    if game is None or game.errors:
        raise ValueError(f"Invalid PGN: {getattr(game, 'errors', None)}")
    board = game.board()
    identities = {sq: f"{piece.symbol()}-{chess.square_name(sq)}"
                  for sq, piece in board.piece_map().items()}

    def position(move=None):
        return {
            "fen": board.fen(),
            "turn": "white" if board.turn else "black",
            "check": chess.square_name(board.king(board.turn)) if board.is_check() else None,
            "mate": board.is_checkmate(),
            "pieces": [
                {"id": identities[sq], "square": chess.square_name(sq),
                 "color": "white" if piece.color else "black", "type": piece.symbol().lower()}
                for sq, piece in sorted(board.piece_map().items())
            ],
            "move": move,
        }

    frames = [position()]
    for move in game.mainline_moves():
        if move not in board.legal_moves:
            raise ValueError(f"Illegal move {move.uci()} at {board.fen()}")
        san = board.san(move)
        piece = board.piece_at(move.from_square)
        capture_square = move.to_square
        if board.is_en_passant(move):
            capture_square += -8 if board.turn else 8
        captured = board.piece_at(capture_square)
        info = {
            "san": san, "number": board.fullmove_number,
            "color": "white" if board.turn else "black", "type": piece.symbol().lower(),
            "from": chess.square_name(move.from_square), "to": chess.square_name(move.to_square),
            "uci": move.uci(), "captured": captured.symbol().lower() if captured else None,
            "promotion": chess.piece_symbol(move.promotion) if move.promotion else None,
            "castle": board.is_castling(move),
        }
        moving_id = identities.pop(move.from_square)
        identities.pop(capture_square, None)
        identities[move.to_square] = moving_id
        if board.is_castling(move):
            rank = chess.square_rank(move.from_square)
            kingside = chess.square_file(move.to_square) > chess.square_file(move.from_square)
            rook_from = chess.square(7 if kingside else 0, rank)
            rook_to = chess.square(5 if kingside else 3, rank)
            identities[rook_to] = identities.pop(rook_from)
        board.push(move)
        if set(identities) != set(board.piece_map()):
            raise AssertionError(f"Piece identities diverged after {san}")
        frames.append(position(info))

    result = game.headers["Result"]
    if result not in ("1-0", "0-1"):
        raise ValueError("This replay template expects a completed decisive game")
    if board.is_checkmate():
        if board.result() != result or ending not in (None, "checkmate"):
            raise ValueError("Recorded result or ending disagrees with the checkmate position")
        ending = "checkmate"
    elif ending != "resignation" or board.is_game_over():
        raise ValueError("A non-terminal final position requires an explicit --ending resignation")
    for frame in frames:
        if len({p["id"] for p in frame["pieces"]}) != len(frame["pieces"]):
            raise AssertionError("Duplicate piece identities")

    display_names = {color: game.headers[color.title()].removesuffix(" (Guest)")
                     for color in ("white", "black")}
    metadata = json.loads((ROOT / "replay-metadata.json").read_text(encoding="utf-8"))
    player_metadata = metadata.get(game.headers["Round"])
    player_side = player_metadata.get("playerSide", "white") if player_metadata else "white"
    if player_side not in ("white", "black"):
        raise ValueError("Replay metadata playerSide must be white or black")
    opponent_side = "black" if player_side == "white" else "white"
    title_player = display_names[player_side]
    if player_metadata:
        display_names[player_side] = player_metadata["model"]
        title_player = f"{player_metadata['model']} ({player_metadata['thinkingLevel']})"
    title = f"{title_player} vs. {display_names[opponent_side]}"
    date = datetime.strptime(game.headers["Date"], "%Y.%m.%d")
    date_label = f"{date.strftime('%B')} {date.day}, {date.year}"
    winner = "White" if result == "1-0" else "Black"
    loser = "Black" if winner == "White" else "White"
    outcome = {
        "reason": ending, "label": ending.title(), "winner": winner.lower(),
        "description": f"{winner} won by {ending}",
        "detail": (f"{loser} resigned · {winner} wins" if ending == "resignation"
                   else f"Checkmate · {winner} wins"),
    }

    data = {"headers": dict(game.headers), "pgn": pgn, "frames": frames,
            "displayNames": display_names, "outcome": outcome, "playerSide": player_side}
    if evaluations is not None:
        data["evaluations"] = attach_evaluations(frames, evaluations, player_side=player_side)
    embedded = json.dumps(data, separators=(",", ":"), ensure_ascii=True).replace("<", "\\u003c")
    template = (ROOT / "templates" / "replay.template.html").read_text(encoding="utf-8")
    assert template.count("__REPLAY_DATA__") == 1
    substitutions = {
        "__TITLE__": title,
        "__ROUND__": game.headers["Round"].zfill(2),
        "__SUBTITLE__": f"{subtitle or 'Rematch'} · {date_label}",
        "__RESULT__": result.replace("-", "–"),
        "__ENDING__": outcome["label"],
        "__RESULT_DESCRIPTION__": outcome["description"],
        "__PLIES__": str(len(frames) - 1),
        "__MOVES__": str(frames[-1]["move"]["number"]),
        "__PGN_FILENAME__": pgn_path.name,
    }
    output = template
    for key, value in substitutions.items():
        output = output.replace(key, html.escape(value, quote=True))
    output = output.replace("__REPLAY_DATA__", embedded)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(output, encoding="utf-8")
    print(f"Validated {len(frames)-1} legal plies; recorded result {result} by {ending}.")
    print(f"Wrote {len(frames)} positions and {len(output):,} characters to {output_path.name}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pgn", type=Path, default=ROOT / "codex-vs-sven-rematch-2026-09-05.pgn")
    parser.add_argument("--output", type=Path, help="Output page; bare filenames go under replays/")
    parser.add_argument("--subtitle", help="Label before the game date")
    parser.add_argument("--ending", choices=("checkmate", "resignation"),
                        help="Required for a resignation; checkmate is detected from the board")
    parser.add_argument("--evaluations", type=Path,
                        help="Audited evaluation-history JSON; shows recorded player-move scores")
    args = parser.parse_args()
    output_path = args.output or REPLAY_DIR / ("replay.html" if args.pgn.name == "codex-vs-sven-rematch-2026-09-05.pgn" else f"{args.pgn.stem}-replay.html")
    build(args.pgn, output_path, args.subtitle, args.ending, args.evaluations)
