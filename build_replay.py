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
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / ".replay-deps"))
import chess
import chess.pgn


def build(pgn_path, output_path, subtitle=None, ending=None):
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
    title_player = display_names["white"]
    if player_metadata:
        display_names["white"] = player_metadata["model"]
        title_player = f"{player_metadata['model']} ({player_metadata['thinkingLevel']})"
    title = f"{title_player} vs. {display_names['black']}"
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
            "displayNames": display_names, "outcome": outcome}
    embedded = json.dumps(data, separators=(",", ":"), ensure_ascii=True).replace("<", "\\u003c")
    template = (ROOT / "replay.template.html").read_text(encoding="utf-8")
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
    output_path.write_text(output, encoding="utf-8")
    print(f"Validated {len(frames)-1} legal plies; recorded result {result} by {ending}.")
    print(f"Wrote {len(frames)} positions and {len(output):,} characters to {output_path.name}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pgn", type=Path, default=ROOT / "codex-vs-sven-rematch-2026-09-05.pgn")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--subtitle", help="Label before the game date")
    parser.add_argument("--ending", choices=("checkmate", "resignation"),
                        help="Required for a resignation; checkmate is detected from the board")
    args = parser.parse_args()
    output_path = args.output or ROOT / ("replay.html" if args.pgn.name == "codex-vs-sven-rematch-2026-09-05.pgn" else f"{args.pgn.stem}-replay.html")
    build(args.pgn, output_path, args.subtitle, args.ending)
