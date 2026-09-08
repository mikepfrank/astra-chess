# Game 10: independent final record audit

Completed after play on September 8, 2026. This audit read the saved game,
queries, and ledger. It used the project's rules and the locally installed
`python-chess` rules package (`chess.__version__ == "1.11.2"`) for validation.
No external engine, opening book, tablebase, network lookup, or site evaluation
was used. This document is the audit's only file change.

## Result and record consistency

- Wally played White; Astra (Ultra) played Black.
- **0-1, checkmate by 48...Rcxd2#.**
- All **96 plies, 96 SAN strings, and 97 FENs** agree with both the project's
  rules and the independent rules validator. FEN comparison uses
  `board.fen(en_passant="fen")`, preserving FEN's double-push target convention.
- `game.pgn` parses without errors, contains the identical UCI sequence, and
  records `0-1`. The final position is checkmate, not stalemate.
- All **131 saved candidate lines** replay legally under the project's rules;
  every stored SAN string and intermediate FEN matches the replay.

The audit checks the persisted records. The parent task separately observed
the final result in Chess.com's UI; this audit did not revisit that UI.

## Search evidence and frozen source

There are **46 completed query outputs**, all ordinary material analyses,
and one additional rejected request at move 42. There are no successful
goal-probe outputs in this game. Moves 42, 43, 44, and 48 have no saved query
outputs; moves 10 and 28 have two apiece.

| Completed full-width depth | Number of queries |
| --- | ---: |
| 4 | 7 |
| 5 | 31 |
| 6 | 7 |
| 7 | 1 |

Median completed depth was **5**. Recorded core search elapsed time totals
**616.985 seconds** over **9,530,844 reported nodes**. The ledger's sum of query
wall times is **618.607841 seconds**; these are different measurements, not
additional time to add to the game clock. No query result reports a fallback.

Every output's source fingerprint matches the current source:

```text
96e9ed243d69eede25b24c4c22248753053ee162b51fd0eb4cc081f47a311174
```

The hash is SHA256 of, in order, each ASCII filename, a NUL byte, and its raw
file bytes: `rules.py`, `search.py`, `diagnostics.py` in `astra_engine/`. It covers
these engine components, not the clock, interface, browser tooling, or complete
runtime environment. Matching saved fingerprints and current bytes is not a
hermetic reconstruction of every historical process.

The recorded search settings leave optional mobility, restricted-piece,
king-exposure evaluation, and threat extensions off. Diagnostics supplied
annotations without those experimental evaluation terms being enabled.

## Independent check of 46...Bg4

The live move-46 query requested depth 10 but completed **depth 4** in a
19-second core search, reporting `mate_in_plies: 5`. Its principal variation
was `Bg4 Bd2 Rc2 h5 Rcxd2#`. A mate score and one principal variation alone
are not the independent all-defenses verification below; a terminal sequence
can also extend beyond the stated full-width depth through quiescence.

After 46...Bg4, the independent rules validator lists exactly **11 legal
White replies**. Bounded enumeration of those replies and the specified
continuation confirms mate within five plies including Bg4:

| White's move 47 | Black continuation |
| --- | --- |
| Bd8, Be7, Bf6 | 47...Rc2# |
| Bh6, Bf4, Be3, Bc1, Kg2, a6, h5 | 47...Rc2+; the only legal reply is 48.Bd2, then 48...Rcxd2# |
| Bd2 | 47...Rc2; the only legal replies are 48.Kg2, 48.a6, and 48.h5, each met by 48...Rcxd2# |

This checks every legal defense at both White turns. It uses rules-only
enumeration with a specified Black continuation, not a new external engine
evaluation. The actual continuation was **47.Bd2 Rc2 48.Kg2 Rcxd2#**.

## Clock reconciliation

| Quantity | Seconds | Minutes and seconds |
| --- | ---: | --- |
| Original allowance | 3600.000 | 60:00.000 |
| Authorized extension | 900.000 | 15:00.000 |
| Final allowance | 4500.000 | 75:00.000 |
| Final charged own time | **3951.183** | **65:51.183** |
| Final remaining time | **548.817** | **9:08.817** |
| Approved pause excluded | 895.372769 | 14:55.372769 |
| Refunds | 0.000 | 0:00.000 |

All 48 `verification.charged_seconds` values sum to **3951.183 seconds**.
There is exactly one `user_time_extension` event and no refund events. The
extension adds 900 seconds; it does not erase previously charged time.

The excluded interval is precisely
`2026-09-08T01:41:35.130231+00:00` through
`2026-09-08T01:56:30.503000+00:00`, a difference of **895.372769 seconds**.
It is tied to the documentary pause boundary at ledger sequence 312 and
recorded in the extension at sequence 313. The cumulative charged time
exceeds the original one-hour allowance by **351.183 seconds**. Accordingly,
this was a completed win with an authorized extension, not a win within the
original hour.

A separate sum of each turn's UTC observation-to-submission interval is
4846.565 seconds. Subtracting the approved pause gives 3951.192231 seconds,
**0.009231 seconds more** than the ledger. This equals the magnitude of the
extension's documented `boundary_sample_difference_seconds` (-0.009231),
arising from the pause boundary's UTC/monotonic samples. No unexplained large
clock discrepancy was found.

The cooperative clock starts from the first recorded observation of an
opponent move and stops at the supplied accepted-move submission timestamp.
Opponent time, later verification, and unseen observation latency are outside
those intervals. The ledger therefore does not independently measure the
instant Wally completed a move. The approved pause also includes the recorded
setup interval before resumption. These limitations should accompany timing
comparisons with earlier games.

## Reproducing the checks

The checks were ephemeral Python scripts run from the repository root using
the bundled Python executable with `-B` (no bytecode writes). The following
core script reproduces record, candidate, fingerprint, and bounded mate checks.
The `.replay-deps` dependency is used only for this post-game rules audit.

```python
import hashlib
import io
import json
import sys
from pathlib import Path
from astra_engine.rules import Position, START_FEN

p = Path("engine-games/wally-v02-black")
g = json.loads((p / "game.json").read_text())
pos = Position.from_fen(START_FEN)
for i, uci in enumerate(g["uci"]):
    assert pos.fen() == g["fens"][i]
    move = pos.parse_uci(uci)
    assert pos.san(move) == g["san"][i]
    pos = pos.play(move)
assert pos.fen() == g["fens"][-1]
assert pos.in_check() and not pos.legal_moves()

sys.path.insert(0, ".replay-deps")
import chess
import chess.pgn
assert chess.__version__ == "1.11.2"
b = chess.Board()
for i, uci in enumerate(g["uci"]):
    assert b.fen(en_passant="fen") == g["fens"][i]
    move = chess.Move.from_uci(uci)
    assert move in b.legal_moves and b.san(move) == g["san"][i]
    b.push(move)
assert b.fen(en_passant="fen") == g["fens"][-1]
assert b.is_checkmate() and b.result() == "0-1"
pg = chess.pgn.read_game(io.StringIO((p / "game.pgn").read_text()))
assert not pg.errors
assert [m.uci() for m in pg.mainline_moves()] == g["uci"]
assert pg.headers["Result"] == g["result"] == "0-1"

queries = [json.loads(f.read_text())
           for f in p.glob("turn-*-query-*.json")
           if ".request." not in f.name]
digest = hashlib.sha256()
for name in ("rules.py", "search.py", "diagnostics.py"):
    digest.update(name.encode("ascii") + b"\0" +
                  (Path("astra_engine") / name).read_bytes())
assert {q["engine"]["source_sha256"] for q in queries} == {
    digest.hexdigest()}
for q in queries:
    for line in q.get("candidates", q.get("lines", [])):
        pos = Position.from_fen(line["fens"][0])
        assert len(line["fens"]) == len(line["uci"]) + 1
        for i, uci in enumerate(line["uci"]):
            move = pos.parse_uci(uci)
            assert pos.san(move) == line["san"][i]
            pos = pos.play(move)
            assert pos.fen() == line["fens"][i + 1]

def is_mating_move(board, uci):
    move = chess.Move.from_uci(uci)
    if move not in board.legal_moves:
        return False
    board.push(move)
    answer = board.is_checkmate()
    board.pop()
    return answer

b = chess.Board(g["fens"][92])  # Immediately after 46...Bg4.
white_replies = list(b.legal_moves)
assert len(white_replies) == 11
for white in white_replies:
    b.push(white)
    if not is_mating_move(b, "c8c2"):
        rc2 = chess.Move.from_uci("c8c2")
        assert rc2 in b.legal_moves
        b.push(rc2)
        defenses = list(b.legal_moves)
        assert defenses  # In particular, this is not stalemate.
        for defense in defenses:
            b.push(defense)
            assert is_mating_move(b, "c2d2")
            b.pop()
        b.pop()
    b.pop()
print("All record, source, candidate, and bounded mate checks passed.")
```

This game and audit supply another data point, not a controlled estimate of
playing strength or causal evidence for any particular engine improvement.
