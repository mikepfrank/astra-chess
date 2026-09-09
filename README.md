# Astra Search Lab and chess replays

A from-scratch chess engine, inspectable search reports, a deliberative playing
workflow, and the complete archived experiment. Start with [SETUP.md](SETUP.md)
for a fresh checkout, or [PACKAGING.md](PACKAGING.md) for the local source/history
package and GitHub handoff. Core analysis needs only Python's standard library.

## Repository layout

| Directory | Contents |
| --- | --- |
| `astra_engine/` | From-scratch chess rules, evaluation, search, clocks and reports |
| [docs/](docs/engine-design.md) | Detailed engine design, evaluation formulas, goal queries and optional features |
| [early-games/](early-games/README.md) | Early trial PGNs, saved board journals, validation evidence and notes, grouped by game/date |
| `engine-games/` | Game journals, PGNs, clock ledgers and saved queries |
| `engine-output/` | Analysis reports, evaluation graphs and their supporting artifacts |
| `replays/` | Standalone replay pages, collection `index.html` and display metadata |
| `templates/` | Shared replay HTML template |
| `images/positions/` | Saved board positions and candidate-move diagrams |
| `images/replays/` | Replay screenshots |
| `skills/` | Canonical assistant play and archive procedures |
| `tests/` | Rules, tooling and browser checks |
| `scratch/` | Ignored temporary analysis, including the default scratchpad state |

Keep future replay builds and collection edits in `replays/`. The builder defaults
to `replays/replay.html`; specify an output there for other games. The scratchpad
defaults to `scratch/board.json`; bare `--state` names also go under `scratch/`.
Bare `--png` filenames go to `images/positions/`, while paths with an explicit
directory are honored. Completed early trial records belong under
`early-games/GAME-DATE/`, retaining their original filenames. The live helper's
`choose --png` stores its candidate under
`engine-games/GAME-SLUG/images/`. The documented analysis/report subdirectories
stay in place.

## Chess engine experiment

[ENGINE.md](ENGINE.md) documents **Astra Search Lab**, the from-scratch chess
engine, goal queries, visual evidence reports, and shared turn-budget workflow.
The [engine design reference](docs/engine-design.md) documents every evaluation
factor and weight, the search algorithm, all goal criteria, options and defaults,
with examples and links to their implementations.
Run `python astra_chess.py --help` for the command interface. Engine output lives
in `engine-output/`; it is separate from the published game replays below.
Version 0.2 adds faster search, a cumulative game clock, and optional threat
inspection. [ENGINE-CHANGES.md](ENGINE-CHANGES.md) records the selected defaults,
benchmarks, and verification against the preserved baseline.

The latest trial is [game 11 against Li (2000)](engine-games/li-v02-classical/experiment.md):
Astra played White and drew by insufficient material after 70.Kxe6. The
[PGN](engine-games/li-v02-classical/game.pgn), all search evidence, and
[own-time audit](engine-games/li-v02-classical/time-audit.md) are preserved.

[REPRODUCIBILITY.md](REPRODUCIBILITY.md) inventories the equipment, notes and
environment requirements retained locally, and the remaining work for a future
public package of this method.

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

The historical one-hour allowance means cumulative own-turn time, excluding the opponent's thinking.
Compaction does not silently reset it. The ledger supports explicit user credits
without deleting original charges. See `ENGINE.md` for the accounting boundary.
New trials can select `--time-control classical`: 90 minutes initially,
30 more after the 40th verified own move, and a 30-second increment after each
verified own move. Game 11 used this implemented control; earlier journals
retain their original policies. See `TIME-CONTROL-NEXT.md` for details.

## Replay collection

**[replays/index.html](replays/index.html)** is the collection's standalone home page. It links to nine
replays at their `astra-vs-*.netlify.app` addresses, including the proposed
`astra-vs-li.netlify.app` deployment for game 11. Upload just this
file to the new master Netlify project; no other files or build step are needed.

Open any HTML file in `replays/` in a browser:

- **replay.html** — the 41-move winning rematch against Sven (1100), ending in Qxh6#.
- **nelson-replay.html** — the 45-move winning rematch against Nelson (1300), ending in Rh8#.
- **wendy-replay.html** — the 36-move win against Wendy (1500), ending in Rg6#.
- **wally-replay.html** — the 33-move game against Wally (1800), won by Wally as Black with 33...Qf1# (0-1).
- **wally-rematch-replay.html** — the 47-move rematch against Wally (1800) on 2026-09-06, won by Wally after White resigned following 47...Kg6 (0-1).
- **wally-engine-replay.html** — the 40-move engine-assisted trial against Wally (1800) on 2026-09-07, won by Wally after White resigned following 40...Re1 (0-1).
- **wally-engine-v02-replay.html** — the 31-move engine-v0.2 win against Wally (1800) on 2026-09-07, ending 31. Qxf7# (1-0), with recorded engine scores below the board.
- **wally-engine-v02-black-replay.html** — the 48-move win as Black against Wally (1800), ending 48...Rcxd2# (0-1), with Black-relative recorded engine scores.
- **li-replay.html** — the 70-move draw as White against Li (2000), ending 70.Kxe6 by insufficient material (1/2-1/2), with recorded engine scores and an explicit final draw label.

All nine replay files are self-contained and work offline. No login, network connection,
external fonts, or chess engine is required. Each includes its complete PGN.

Board pieces use original inline SVG drawings with explicit light/dark fills and
outlines. This avoids device font differences and the pawn's Unicode emoji
variant, which can render as a black emoji on iPhone even when CSS requests a
white piece. The drawings are embedded in each page; no extra files need uploading.

- Click a move, use Previous / Next, or scrub the position slider.
- Play / Pause animates the recorded sequence; Speed controls the interval.
- Left / Right step through moves; Home / End jump to the endpoints.
- Space toggles playback when focus is outside a button or form control.
- Flip board changes the viewing side. Download PGN saves the original record.
- Backward navigation restores captures, castling, and promotion correctly.
- The board respects the system's reduced-motion preference.

## Source and rebuild

`templates/replay.template.html` contains the interface. `build_replay.py` reads the saved
PGN, validates every legal move with `chess==1.11.2`, and embeds all positions
(including the starting position): 82 for Sven, 90 for Nelson, 72 for Wendy
(71 plies), 67 for Wally (66 plies), 95 for the Wally rematch (94 plies), and
81 for the first engine-assisted Wally trial (80 plies), 62 for the v0.2 White win
(61 plies), 97 for the v0.2 Black win (96 plies), and 140 for the Li draw (139 plies).
The opponent, rating, date, move count, result, and download filename come
from the record. Automatic terminal endings, including insufficient material
and stalemate, are detected and checked against the PGN result. Resignations,
agreed draws, and claim-based draws require an explicit supported `--ending`.

`replays/replay-metadata.json` supplies display names and thinking levels by the PGN's
`Round` number. Replay titles use **Astra (thinking level) vs. opponent**, while
the board's player label is simply **Astra**. The recorded levels are High for
game 1 (Sven loss), Extra High for games 2–3 (Sven rematch and Nelson loss), and
Ultra for games 4–11 (Nelson rematch, Wendy, the five Wally games, and Li). The nine
HTML archives cover games 2 and 4–11. Early source PGNs, board journals and trial
notes are grouped under `early-games/` by game/date. Original PGN contents and
filenames remain unchanged. With no arguments, the builder reads
`early-games/sven-rematch-2026-09-05/codex-vs-sven-rematch-2026-09-05.pgn`.

```text
python -m pip install --target .replay-deps chess==1.11.2
python build_replay.py
python build_replay.py --pgn early-games/nelson-rematch-2026-09-05/codex-vs-nelson-rematch-2026-09-05.pgn --output replays/nelson-replay.html --subtitle "Rematch / Visualization trial"
python build_replay.py --pgn early-games/wendy-2026-09-05/codex-vs-wendy-2026-09-05.pgn --output replays/wendy-replay.html --subtitle "Visualization trial"
python build_replay.py --pgn early-games/wally-2026-09-05/codex-vs-wally-2026-09-05.pgn --output replays/wally-replay.html --subtitle "Visualization trial"
python build_replay.py --pgn early-games/wally-rematch-2026-09-06/codex-vs-wally-rematch-2026-09-06.pgn --output replays/wally-rematch-replay.html --subtitle "Rematch / Visualization trial" --ending resignation
python build_replay.py --pgn engine-games/wally-2026-09-07/astra-vs-wally-engine-2026-09-07.pgn --output replays/wally-engine-replay.html --subtitle "Engine-assisted trial" --ending resignation
python export_evaluations.py --game wally-engine-v02 --output engine-output/wally-v02-evaluation/data.json
python build_replay.py --pgn engine-games/wally-engine-v02/game.pgn --output replays/wally-engine-v02-replay.html --subtitle "Engine v0.2 trial" --evaluations engine-output/wally-v02-evaluation/data.json
python export_evaluations.py --game wally-v02-black --output engine-output/wally-v02-black-evaluation/data.json
python build_replay.py --pgn engine-games/wally-v02-black/game.pgn --output replays/wally-engine-v02-black-replay.html --subtitle "Engine v0.2 trial / Astra as Black" --evaluations engine-output/wally-v02-black-evaluation/data.json
python export_evaluations.py --game li-v02-classical --output engine-output/li-v02-evaluation/data.json
python build_replay.py --pgn engine-games/li-v02-classical/game.pgn --output replays/li-replay.html --subtitle "Engine v0.2 trial / Classical clock" --evaluations engine-output/li-v02-evaluation/data.json
```

The Python dependency is only needed to rebuild. It is not bundled into the page
and does not evaluate positions or choose moves.

`export_evaluations.py` uses only the standard library and saved query evidence;
it does not run new searches. It selects the latest completed search that
evaluated the actual chosen move from the exact actual starting position.
Pending choices are excluded, missing scores stay missing, and mate encodings
are not converted to pawn scores. `--evaluations` adds these records to a replay.
Astra-move frames identify the original pre-move search; opponent frames say no
new evaluation was recorded. Positive scores favor the recorded player's color,
explicitly labeled in the replay. Mate labels count the mating side's moves
remaining from the displayed board: in game 9, move 29 shows **Mate in 2**,
move 30 **Mate in 1**, and move 31 **Checkmate**. The original chart's root distance for move 29 included
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
python serve_replay.py --page replays/nelson-replay.html --port 8766
```

Open http://127.0.0.1:8766/nelson-replay.html. To preview Wendy on another port:

```text
python serve_replay.py --page replays/wendy-replay.html --port 8767
```

Open http://127.0.0.1:8767/wendy-replay.html. To preview Wally on another port:

```text
python serve_replay.py --page replays/wally-replay.html --port 8768
```

Open http://127.0.0.1:8768/wally-replay.html. To preview the Wally rematch on another port:

```text
python serve_replay.py --page replays/wally-rematch-replay.html --port 8769
```

Open http://127.0.0.1:8769/wally-rematch-replay.html. To share any replay, upload just
its HTML file to a static host. Local directory names do not change the hosted
page's name: deploy each standalone replay as the project's root `index.html`.

The game-8 index entry uses `https://astra-vs-wally-engine.netlify.app/`, the proposed
project name following the existing naming pattern. To publish it with Netlify
Drop, deploy a copy of `replays/wally-engine-replay.html` named `index.html` as that
project's root page. Deploy the collection's `replays/index.html` separately to
`astra-plays-chess`. No deployment is performed by the local build.

Preview the new replay with:

```text
python serve_replay.py --page replays/wally-engine-replay.html --port 8772
```

The game journal, all engine queries, experiment observations, and audit are in
`engine-games/wally-2026-09-07/`. The repository baseline preserves the current
engine behavior and historical experiment artifacts. Legacy mutable turn clocks,
server logs, Python caches, and the locally installed replay dependency are
excluded. New append-only game-clock ledgers are retained as experiment evidence.

Game 9's replay is `replays/wally-engine-v02-replay.html`. Its index link uses the
**proposed** Netlify project `astra-vs-wally-engine-v02`. Deploy this replay as
that project's `index.html`, then upload the updated collection `replays/index.html`
to `astra-plays-chess`. If you choose a different project name, change that one
index link. The local build does not create or publish the Netlify project.
Game-9 PGN, search evidence and clock are in `engine-games/wally-engine-v02/`.

Game 10's replay is `replays/wally-engine-v02-black-replay.html`. Astra plays Black;
the board initially puts Black at the bottom and keeps the recorded White/Black
identities, ratings, 0-1 result and PGN intact. Round 10's `playerSide: "black"`
in `replays/replay-metadata.json` drives presentation. The exporter uses the journal's
`player_side` and retains Black-root scores without reversing their sign.
Flipping the board does not change those scores. Black moves 42-44 have no
recorded evaluation; 46/47 show **Mate in 2/Mate in 1**, and 48 shows **Checkmate**.

Its index link uses the **proposed** Netlify project
`astra-vs-wally-engine-v02-black`. Upload the replay HTML as that project's
root `index.html`, then redeploy the collection's separate `replays/index.html` to
`astra-plays-chess`. Change the new collection link if choosing another name.
No deployment is performed by the local build. For the embedded preview:

```text
python serve_replay.py --page replays/wally-engine-v02-black-replay.html --port 8774
```

Black-specific offline browser checks are in `tests/test_replay_black.cjs`;
the exported scores and desktop/mobile checks are preserved in
`engine-output/wally-v02-black-evaluation/`. Neither the exporter nor the
archive build runs a new engine search.

The current tools pass **168 Python tests** with
`python -m unittest discover -s tests`. Offline headless-browser checks in
`tests/test_replay_scores.cjs` cover navigation, scores, mate labels, promotion,
mobile layout, PGN download and compatibility with an older replay. Both
the legacy browser suite and `tests/test_replay_black.cjs` pass offline.
The Black suite additionally checks color-aware player rows and score semantics.
`tests/test_replay_pieces.cjs` checks all nine pages at mobile dimensions,
including SVG geometry, distinct pawn colors, board flips, and promotion/rewind.
`tests/test_replay_li.cjs` checks the drawn ending, all 70 recorded scores,
navigation, castling/captures, PGN download, mobile layout, and the nine-game index.
All four suites pass with the installed Edge browser. Current replay screenshots
go under `images/replays/`; previous engine-output screenshots remain preserved.
Both skills pass Codex's official skill validator. An independent read-only recovery
exercise checked the interrupted-promotion case without changing the real game.
