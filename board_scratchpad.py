"""Diagram-only chess scratchpad. No rules, legality checks, or move analysis.

Commands: init, commit e2e4 [g1f3 ...], preview e2e4 [...], show.
Use --state PATH for another JSON file, --png PATH for a diagram, and
commit --san TEXT to record a manually supplied journal label. Castling is
two explicit edits; any special capture must be represented by explicit edits.
"""

import argparse
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
POSITION_IMAGES = ROOT / "images" / "positions"
FILES = "abcdefgh"
SQUARES = {f + r for f in FILES for r in "12345678"}
START = {f + r: p for r, pieces in (("1", "RNBQKBNR"), ("2", "PPPPPPPP"),
                                   ("7", "pppppppp"), ("8", "rnbqkbnr"))
         for f, p in zip(FILES, pieces)}


def position_image_path(path):
    """Keep default/bare diagram names out of the repository's top level."""
    path = Path(path)
    return POSITION_IMAGES / path if not path.is_absolute() and path.parent == Path(".") else path


def read_state(path):
    state = json.loads(path.read_text(encoding="utf-8"))
    board = state["board"]
    if not isinstance(board, dict) or any(
        sq not in SQUARES or p not in "PNBRQKpnbrqk" or len(p) != 1
        for sq, p in board.items()
    ):
        raise ValueError("Invalid diagram board data")
    return state


def apply_edits(state, edits):
    result = copy.deepcopy(state)
    board = result["board"]
    for edit in edits:
        edit = edit.lower()
        if len(edit) not in (4, 5) or edit[:2] not in SQUARES or edit[2:4] not in SQUARES:
            raise ValueError(f"Expected an explicit square edit, for example e2e4: {edit}")
        if len(edit) == 5 and edit[4] not in "qrbn":
            raise ValueError("Optional fifth character must be q, r, b, or n")
        source, target = edit[:2], edit[2:4]
        if source not in board:
            raise ValueError(f"No diagram piece at {source}")
        piece = board.pop(source)
        if len(edit) == 5:
            piece = edit[4].upper() if piece.isupper() else edit[4]
        board[target] = piece
    result["last_edits"] = [e.lower() for e in edits]
    return result


def save(state, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def font(size, bold=False):
    from PIL import ImageFont

    candidates = [Path("C:/Windows/Fonts") / ("arialbd.ttf" if bold else "arial.ttf"),
                  Path("/usr/share/fonts/truetype/dejavu") /
                  ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default(size=size)


def render(state, output, title):
    try:
        from PIL import Image, ImageDraw
    except ModuleNotFoundError as error:
        if error.name != "PIL":
            raise
        raise ValueError(
            "PNG rendering requires Pillow; install it with python -m pip install Pillow==12.3.0"
        ) from error

    cell, left, top = 70, 42, 48
    image = Image.new("RGB", (644, 666), "#f1f3f5")
    draw = ImageDraw.Draw(image)
    label_font, piece_font = font(19), font(32, True)
    draw.text((322, 20), title, font=font(19, True), fill="#20252b", anchor="mm")
    origins = {e[:2] for e in state.get("last_edits", [])}
    targets = {e[2:4] for e in state.get("last_edits", [])}
    for row in range(8):
        for col in range(8):
            square = FILES[col] + str(8 - row)
            x, y = left + col * cell, top + row * cell
            color = "#ecdcc2" if (row + col) % 2 == 0 else "#749185"
            draw.rectangle((x, y, x + cell - 1, y + cell - 1), fill=color)
            if square in origins | targets:
                mark = "#dc9b27" if square in targets else "#428dcc"
                draw.rectangle((x + 2, y + 2, x + cell - 3, y + cell - 3),
                               outline=mark, width=4)
            piece = state["board"].get(square)
            if piece:
                white = piece.isupper()
                draw.ellipse((x + 11, y + 11, x + 59, y + 59),
                             fill="#fffdf6" if white else "#242931",
                             outline="#242931" if white else "#fffdf6", width=2)
                draw.text((x + 35, y + 35), piece.upper(), font=piece_font,
                          fill="#242931" if white else "#fffdf6", anchor="mm")
        draw.text((23, top + row * cell + 35), str(8 - row), font=label_font,
                  fill="#30363c", anchor="mm")
    for col, file_name in enumerate(FILES):
        draw.text((left + col * cell + 35, 625), file_name, font=label_font,
                  fill="#30363c", anchor="mm")
    draw.text((322, 649), "K king   Q queen   R rook   B bishop   N knight   P pawn",
              font=font(14), fill="#30363c", anchor="mm")
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)
    print(f"PNG: {output}")


def ascii_board(state):
    for rank in "87654321":
        print(rank + "  " + " ".join(state["board"].get(f + rank, ".") for f in FILES))
    print("   a b c d e f g h\nUppercase = White; lowercase = Black")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("init", "commit", "preview", "show"))
    parser.add_argument("edits", nargs="*")
    parser.add_argument("--state", type=Path, default=ROOT / "nelson-rematch-board.json")
    parser.add_argument("--png", type=Path, help="Diagram path; bare filenames go under images/positions/")
    parser.add_argument("--san", help="Manually supplied journal text; never parsed")
    parser.add_argument("--force", action="store_true", help="Allow init to replace state")
    args = parser.parse_args()
    state_path = args.state.resolve()
    try:
        if args.command == "init":
            if state_path.exists() and not args.force:
                raise ValueError("State already exists; use --force to reinitialize")
            if args.edits:
                raise ValueError("init takes no square edits")
            state = {"board": START.copy(), "journal": [], "last_edits": []}
            save(state, state_path)
        else:
            state = read_state(state_path)
            if args.command in ("commit", "preview"):
                if not args.edits:
                    raise ValueError(f"{args.command} needs one or more explicit edits")
                state = apply_edits(state, args.edits)
                if args.command == "commit":
                    entry = {"edits": state["last_edits"]}
                    if args.san:
                        entry["san"] = args.san
                    state.setdefault("journal", []).append(entry)
                    save(state, state_path)
            elif args.edits:
                raise ValueError("show takes no square edits")
        print(f"State: {state_path}" + (" (preview; unchanged)" if args.command == "preview" else ""))
        ascii_board(state)
        output = args.png
        if args.command == "preview" and output is None:
            output = POSITION_IMAGES / "board-preview.png"
        if output:
            render(state, position_image_path(output).resolve(), "Preview" if args.command == "preview" else "Current board")
    except (OSError, ValueError, KeyError) as error:
        parser.exit(2, f"Error: {error}\n")


if __name__ == "__main__":
    main()
