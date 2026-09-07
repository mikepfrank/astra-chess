# Chess game replays

## Chess engine experiment

[ENGINE.md](ENGINE.md) documents **Astra Search Lab**, the from-scratch chess
engine, goal queries, visual evidence reports, and shared turn-budget workflow.
Run `python astra_chess.py --help` for the command interface. Engine output lives
in `engine-output/`; it is separate from the published game replays below.
Version 0.2 adds faster search, a cumulative game clock, and optional threat
inspection. [ENGINE-CHANGES.md](ENGINE-CHANGES.md) records the selected defaults,
benchmarks, and verification against the preserved baseline.

## Replay collection

**index.html** is the collection's standalone home page. It links to the six
existing replays at their `astra-vs-*.netlify.app` addresses. Upload just this
file to the new master Netlify project; no other files or build step are needed.

Open any HTML file in a browser:

- **replay.html** — the 41-move winning rematch against Sven (1100), ending in Qxh6#.
- **nelson-replay.html** — the 45-move winning rematch against Nelson (1300), ending in Rh8#.
- **wendy-replay.html** — the 36-move win against Wendy (1500), ending in Rg6#.
- **wally-replay.html** — the 33-move game against Wally (1800), won by Wally as Black with 33...Qf1# (0-1).
- **wally-rematch-replay.html** — the 47-move rematch against Wally (1800) on 2026-09-06, won by Wally after White resigned following 47...Kg6 (0-1).
- **wally-engine-replay.html** — the 40-move engine-assisted trial against Wally (1800) on 2026-09-07, won by Wally after White resigned following 40...Re1 (0-1).

All six files are self-contained and work offline. No login, network connection,
external fonts, or chess engine is required. Each includes its complete PGN.

- Click a move, use Previous / Next, or scrub the position slider.
- Play / Pause animates the recorded sequence; Speed controls the interval.
- Left / Right step through moves; Home / End jump to the endpoints.
- Space toggles playback when focus is outside a button or form control.
- Flip board changes the viewing side. Download PGN saves the original record.
- Backward navigation restores captures, castling, and promotion correctly.
- The board respects the system's reduced-motion preference.

## Source and rebuild

`replay.template.html` contains the interface. `build_replay.py` reads the saved
PGN, validates every legal move with `chess==1.11.2`, and embeds all positions
(including the starting position): 82 for Sven, 90 for Nelson, 72 for Wendy
(71 plies), 67 for Wally (66 plies), 95 for the Wally rematch (94 plies), and
81 for the engine-assisted Wally trial (80 plies).
The opponent, rating, date, move count, result, and download filename come
from the record. Non-checkmate endings are specified explicitly when rebuilding.

`replay-metadata.json` supplies display names and thinking levels by the PGN's
`Round` number. Replay titles use **Astra (thinking level) vs. opponent**, while
the board's player label is simply **Astra**. The recorded levels are High for
game 1 (Sven loss), Extra High for games 2–3 (Sven rematch and Nelson loss), and
Ultra for games 4–8 (Nelson rematch, Wendy, and the three Wally games). The six
existing HTML archives cover games 2 and 4–8. Source PGNs and filenames remain
unchanged.

```text
python -m pip install --target .replay-deps chess==1.11.2
python build_replay.py
python build_replay.py --pgn codex-vs-nelson-rematch-2026-09-05.pgn --output nelson-replay.html --subtitle "Rematch / Visualization trial"
python build_replay.py --pgn codex-vs-wendy-2026-09-05.pgn --output wendy-replay.html --subtitle "Visualization trial"
python build_replay.py --pgn codex-vs-wally-2026-09-05.pgn --output wally-replay.html --subtitle "Visualization trial"
python build_replay.py --pgn codex-vs-wally-rematch-2026-09-06.pgn --output wally-rematch-replay.html --subtitle "Rematch / Visualization trial" --ending resignation
python build_replay.py --pgn engine-games/wally-2026-09-07/astra-vs-wally-engine-2026-09-07.pgn --output wally-engine-replay.html --subtitle "Engine-assisted trial" --ending resignation
```

The Python dependency is only needed to rebuild. It is not bundled into the page
and does not evaluate positions or choose moves.

For a local sidebar preview, run `python serve_replay.py` and open
http://127.0.0.1:8765/replay.html. The server binds only to loopback and serves
only the selected replay page. To preview Nelson alongside Sven:

```text
python serve_replay.py --page nelson-replay.html --port 8766
```

Open http://127.0.0.1:8766/nelson-replay.html. To preview Wendy on another port:

```text
python serve_replay.py --page wendy-replay.html --port 8767
```

Open http://127.0.0.1:8767/wendy-replay.html. To preview Wally on another port:

```text
python serve_replay.py --page wally-replay.html --port 8768
```

Open http://127.0.0.1:8768/wally-replay.html. To preview the Wally rematch on another port:

```text
python serve_replay.py --page wally-rematch-replay.html --port 8769
```

Open http://127.0.0.1:8769/wally-rematch-replay.html. To share any replay, upload just
its HTML file to a static host.

The new index entry uses `https://astra-vs-wally-engine.netlify.app/`, the proposed
project name following the existing naming pattern. To publish it with Netlify
Drop, deploy a copy of `wally-engine-replay.html` named `index.html` as that
project's root page. Deploy the collection's root `index.html` separately to
`astra-plays-chess`. No deployment is performed by the local build.

Preview the new replay with:

```text
python serve_replay.py --page wally-engine-replay.html --port 8772
```

The game journal, all engine queries, experiment observations, and audit are in
`engine-games/wally-2026-09-07/`. The repository baseline preserves the current
engine behavior and historical experiment artifacts. Legacy mutable turn clocks,
server logs, Python caches, and the locally installed replay dependency are
excluded. New append-only game-clock ledgers are retained as experiment evidence.
