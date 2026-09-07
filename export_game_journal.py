"""Export manually recorded SAN labels to PGN without chess analysis.

Example:
  python export_game_journal.py game-board.json game.pgn --opponent Nelson \
      --rating 1300 --result 1-0 --header Date=2026.09.05 --header Round=4

SAN labels are copied literally, including their move numbers. Supply labels
without a final game-result token; --result appends that token. This script
does not import the scratchpad or any chess library, or validate chess moves.
"""

import argparse
import json
import re
from pathlib import Path


RESULTS = ("1-0", "0-1", "1/2-1/2", "*")


def header_assignment(value):
    name, separator, text = value.partition("=")
    if not separator or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name):
        raise argparse.ArgumentTypeError("Expected a header as Tag=Value")
    if "\n" in text or "\r" in text:
        raise argparse.ArgumentTypeError("Header values must be a single line")
    return name, text


def quote_header(value):
    if "\n" in value or "\r" in value:
        raise ValueError("Header values must be a single line")
    return value.replace("\\", "\\\\").replace('"', '\\"')


def export_pgn(state, headers, result, width=80):
    """Wrap between journal entries, leaving every SAN string unchanged."""
    journal = state.get("journal")
    if not isinstance(journal, list) or not journal:
        raise ValueError("Expected a nonempty journal list")
    labels = []
    for index, entry in enumerate(journal, start=1):
        label = entry.get("san") if isinstance(entry, dict) else None
        if not isinstance(label, str) or not label.strip():
            raise ValueError(f"Journal entry {index} has no nonempty SAN text")
        labels.append(label)

    lines, line = [], ""
    for label in [*labels, result]:
        if line and len(line.rsplit("\n", 1)[-1]) + 1 + len(label) > width:
            lines.append(line)
            line = label
        else:
            line = f"{line} {label}" if line else label
    lines.append(line)
    tags = "\n".join(f'[{name} "{quote_header(value)}"]'
                     for name, value in headers.items())
    return tags + "\n\n" + "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("state", type=Path, help="Scratchpad JSON journal to read")
    parser.add_argument("output", type=Path, help="PGN file to create")
    parser.add_argument("--opponent", required=True, help="Black player name")
    parser.add_argument("--rating", help="Black player's displayed rating")
    parser.add_argument("--result", required=True, choices=RESULTS)
    parser.add_argument("--header", action="append", default=[], type=header_assignment,
                        metavar="TAG=VALUE", help="Set a PGN header; repeat as needed")
    parser.add_argument("--width", type=int, default=80,
                        help="Preferred line width; SAN labels are never split (default: 80)")
    parser.add_argument("--force", action="store_true", help="Replace an existing output PGN")
    args = parser.parse_args()
    try:
        if args.width < 1:
            raise ValueError("--width must be positive")
        if args.state.resolve() == args.output.resolve():
            raise ValueError("Input journal and output PGN must be different files")
        state = json.loads(args.state.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            raise ValueError("Expected a JSON object containing a journal")
        headers = {
            "Event": "Chess.com Bot Game", "Site": "https://www.chess.com/",
            "Date": "????.??.??", "Round": "-", "White": "Codex (Guest)",
            "Black": args.opponent, "Result": args.result,
        }
        headers.update(args.header)
        # Dedicated CLI fields take precedence over generic header assignments.
        headers["Black"], headers["Result"] = args.opponent, args.result
        if args.rating is not None:
            headers["BlackElo"] = args.rating
        pgn = export_pgn(state, headers, args.result, args.width)
        with args.output.open("w" if args.force else "x", encoding="utf-8", newline="\n") as output:
            output.write(pgn)
        print(f"PGN: {args.output.resolve()} ({len(state['journal'])} journal entries)")
    except (OSError, ValueError) as error:
        parser.exit(2, f"Error: {error}\n")


if __name__ == "__main__":
    main()
