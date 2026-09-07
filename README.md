# Chess game replays

## Chess engine experiment

[ENGINE.md](ENGINE.md) documents **Astra Search Lab**, the from-scratch chess
engine, goal queries, visual evidence reports, and shared turn-budget workflow.
Run `python astra_chess.py --help` for the command interface. Engine output lives
in `engine-output/`; it is separate from the published game replays below.
Version 0.2 adds faster search, a cumulative game clock, and optional threat
inspection. [ENGINE-CHANGES.md](ENGINE-CHANGES.md) records the selected defaults,
benchmarks, and verification against the preserved baseline.

## Persistent playing and archive procedures

The versioned skills [astra-chess-play](skills/astra-chess-play/SKILL.md) and
[astra-chess-archive](skills/astra-chess-archive/SKILL.md) capture the live-game
and replay workflows. Copies are installed under the user's Codex skills
directory for discovery. `AGENTS.md` also routes project work to these sources,
so recovery does not depend on retaining this conversation in context.

```text
python resume_chess.py
python resume_chess.py --game wally-engine-v02
```

The first command lists saved journals without selecting or starting a game.
The second reads the verified position, pending choice, clock, and most recent
saved search, including whether its source fingerprint matches the current
engine. It neither observes the browser nor advances a move. On resumption,
reconcile a fresh embedded-browser view before any click; a pending promotion
or move may already have been completed by the user. Preserve unresolved UI
timestamps in the game's `continuation.md` until the journal has caught up.

One hour means cumulative own-turn time, excluding the opponent's thinking.
Compaction does not silently reset it. The ledger supports explicit user credits
without deleting original charges. See `ENGINE.md` for the accounting boundary.

## Replay collection

**index.html** is the collection's standalone home page. It links to seven
replays at their `astra-vs-*.netlify.app` addresses, including the proposed
game-9 deployment below. Upload just this
file to the new master Netlify project; no other files or build step are needed.

Open any HTML file in a browser:

- **replay.html** — the 41-move winning rematch against Sven (1100), ending in Qxh6#.
- **nelson-replay.html** — the 45-move winning rematch against Nelson (1300), ending in Rh8#.
- **wendy-replay.html** — the 36-move win against Wendy (1500), ending in Rg6#.
- **wally-replay.html** — the 33-move game against Wally (1800), won by Wally as Black with 33...Qf1# (0-1).
- **wally-rematch-replay.html** — the 47-move rematch against Wally (1800) on 2026-09-06, won by Wally after White resigned following 47...Kg6 (0-1).
- **wally-engine-replay.html** — the 40-move engine-assisted trial against Wally (1800) on 2026-09-07, won by Wally after White resigned following 40...Re1 (0-1).
- **wally-engine-v02-replay.html** — the 31-move engine-v0.2 win against Wally (1800) on 2026-09-07, ending 31. Qxf7# (1-0), with recorded engine scores below the board.

All seven replay files are self-contained and work offline. No login, network connection,
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
81 for the first engine-assisted Wally trial (80 plies), and 62 for the v0.2 win (61 plies).
The opponent, rating, date, move count, result, and download filename come
from the record. Non-checkmate endings are specified explicitly when rebuilding.

`replay-metadata.json` supplies display names and thinking levels by the PGN's
`Round` number. Replay titles use **Astra (thinking level) vs. opponent**, while
the board's player label is simply **Astra**. The recorded levels are High for
game 1 (Sven loss), Extra High for games 2–3 (Sven rematch and Nelson loss), and
Ultra for games 4–9 (Nelson rematch, Wendy, and the four Wally games). The seven
HTML archives cover games 2 and 4–9. Source PGNs and filenames remain
unchanged.

```text
python -m pip install --target .replay-deps chess==1.11.2
python build_replay.py
python build_replay.py --pgn codex-vs-nelson-rematch-2026-09-05.pgn --output nelson-replay.html --subtitle "Rematch / Visualization trial"
python build_replay.py --pgn codex-vs-wendy-2026-09-05.pgn --output wendy-replay.html --subtitle "Visualization trial"
python build_replay.py --pgn codex-vs-wally-2026-09-05.pgn --output wally-replay.html --subtitle "Visualization trial"
python build_replay.py --pgn codex-vs-wally-rematch-2026-09-06.pgn --output wally-rematch-replay.html --subtitle "Rematch / Visualization trial" --ending resignation
python build_replay.py --pgn engine-games/wally-2026-09-07/astra-vs-wally-engine-2026-09-07.pgn --output wally-engine-replay.html --subtitle "Engine-assisted trial" --ending resignation
python export_evaluations.py --game wally-engine-v02 --output engine-output/wally-v02-evaluation/data.json
python build_replay.py --pgn engine-games/wally-engine-v02/game.pgn --output wally-engine-v02-replay.html --subtitle "Engine v0.2 trial" --evaluations engine-output/wally-v02-evaluation/data.json
```

The Python dependency is only needed to rebuild. It is not bundled into the page
and does not evaluate positions or choose moves.

`export_evaluations.py` uses only the standard library and saved query evidence;
it does not run new searches. It selects the latest completed search that
evaluated the actual chosen move from the exact actual starting position.
Pending choices are excluded, missing scores stay missing, and mate encodings
are not converted to pawn scores. `--evaluations` adds these records to a replay.
White frames identify the original pre-move search; Black frames say no new
evaluation was recorded. Mate labels count the mating side's moves remaining
from the displayed board: move 29 shows **Mate in 2**, move 30 **Mate in 1**,
and move 31 **Checkmate**. The original chart's root distance for move 29 included
the move itself, so its "mate in 3" described the same line from one ply earlier.

The chart dataset, reproducible extraction wrapper, inline source
`visualization.html`, built `preview.html`, and visual checks are retained in
`engine-output/wally-v02-evaluation/`. `build_visual.py` embeds its local dataset
without relying on a thread-specific filesystem path. The chart preview uses
CDN-hosted plotting resources; the game-replay HTML itself remains fully offline.

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

The game-8 index entry uses `https://astra-vs-wally-engine.netlify.app/`, the proposed
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

Game 9's replay is `wally-engine-v02-replay.html`. Its index link uses the
**proposed** Netlify project `astra-vs-wally-engine-v02`. Deploy this replay as
that project's `index.html`, then upload the updated collection `index.html`
to `astra-plays-chess`. If you choose a different project name, change that one
index link. The local build does not create or publish the Netlify project.
Game-9 PGN, search evidence and clock are in `engine-games/wally-engine-v02/`.

The current archive/recovery changes pass **110 Python tests** with
`python -m unittest discover -s tests`. Offline headless-browser checks in
`tests/test_replay_scores.cjs` cover navigation, scores, mate labels, promotion,
mobile layout, PGN download and compatibility with an older replay. Both
skills pass Codex's official skill validator. An independent read-only recovery
exercise checked the interrupted-promotion case without changing the real game.
