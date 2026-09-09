# Equipment and reproducibility inventory

This method is preserved in the
[GitHub repository](https://github.com/mikepfrank/astra-chess) for others to inspect
and try in their own Astra sessions. Source/history packages can be generated
with [SETUP.md](SETUP.md), [PACKAGING.md](PACKAGING.md), pinned optional dependencies
and `package_repo.py`.
Keep all authored chess equipment, source data and substantive experiment notes
in this repository, including sources initially created in a thread's
visualization directory. Commit them at completion checkpoints.

## Classical clock implementation (September 8, 2026)

New trials can select `play_engine_game.py init --time-control classical`:
5,400 seconds initially, a 30-second increment after each verified own move,
and 1,800 seconds after the 40th verified own move. Ordinary/critical targets
are 120/240 seconds with a 40-second review and entry reserve. The ledger
records any pre-credit overrun and never spends future credits in advance.
Legacy clock defaults and saved game 9/10 ledgers remain unchanged. All 157
Python tests passed, including staged-clock and White/Black journal integration
checks. Both play-skill copies match and pass validation. The rules, search and
evaluation remained unchanged throughout game 11 against Li (2000), which ended
in a draw after 70.Kxe6. The [game record and assessment](engine-games/li-v02-classical/experiment.md)
preserve all 91 query request/result pairs, the final browser observation, and
the classical ledger. Charged own time was 6596.720 seconds; 2703.280 seconds
remained, with no refunds, extensions, or overall clock overruns.

Game 11's standalone archive is `replays/li-replay.html`, with all 70 historical
scores in `engine-output/li-v02-evaluation/data.json`. The builder/template now
validate drawn endings and label the final result correctly; existing decisive
archives retain their outcomes and position data. All 168 Python tests and four
offline replay browser suites passed. The nine-game index proposes the separate
Netlify project `astra-vs-li`; publishing remains Mike's step.

## What is preserved

The session contains 11 games and [nine replay pages](README.md#replay-collection),
covering rounds 2 and 4–11. The four engine-assisted trials are:

| Game | Opponent | Astra's side | Result | Evidence |
| --- | --- | --- | --- | --- |
| 8 | Wally (1800) | White | Loss, resignation after 40...Re1 | [Trial notes](engine-games/wally-2026-09-07/experiment-notes.md) |
| 9 | Wally (1800) | White | Win, 31.Qxf7# | [Trial notes](engine-games/wally-engine-v02/experiment-notes.md) |
| 10 | Wally (1800) | Black | Win, 48...Rcxd2# | [Trial notes](engine-games/wally-v02-black/experiment-notes.md) |
| 11 | Li (2000) | White | Draw, insufficient material after 70.Kxe6 | [Trial notes](engine-games/li-v02-classical/experiment.md) |

All four used Astra (Ultra). Game 8 used the original engine; games 9–11 used
v0.2, with the staged classical own-time control first used in game 11.

| Component | Repository sources |
| --- | --- |
| From-scratch rules, evaluation, search and optional diagnostics | `astra_engine/`, `astra_chess.py`, `engine_examples/` |
| Manual game journal, cumulative own-turn clock and recovery | `play_engine_game.py`, `astra_engine/clock.py`, `resume_chess.py` |
| Per-turn timing audit and implemented time-control policy | `audit_game_time.py`, `TIME-CONTROL-NEXT.md`, saved game timing reports |
| Prospective board visualization and query reports | `board_scratchpad.py`, `images/positions/`, `astra_engine/report.py`, `astra_engine/report.template.html` |
| Playing and archive procedures | `AGENTS.md`, `skills/astra-chess-play/`, `skills/astra-chess-archive/`, `ENGINE.md` |
| Design rationale and measured improvements | `IMPROVEMENT-PROPOSAL.md`, `ENGINE-CHANGES.md`, benchmark scripts and `engine-benchmarks/` |
| Evaluation/search specification and options | `docs/engine-design.md`, checked against the implemented source and linked from `ENGINE.md` |
| Game evidence and observations | `early-games/GAME-DATE/` for early PGNs, saved board journals, validation and trial notes; `engine-games/` for engine-assisted trials |
| Replay build and collection | `build_replay.py`, `templates/replay.template.html`, `replays/replay-metadata.json`, `replays/index.html`, `replays/*-replay.html`, `replays/replay.html` |
| Historical evaluation extraction and graph | `export_evaluations.py`; game 9's graph/data in `engine-output/wally-v02-evaluation/`; scored-replay data in `engine-output/wally-v02-black-evaluation/` and `engine-output/li-v02-evaluation/` |
| Validation | `tests/`, `images/replays/`, retained browser-check images under `engine-output/`, and experiment audits |
| Portable source/history packaging | `package_repo.py`, `SETUP.md`, `PACKAGING.md`, requirements files, `package.json`, `.gitattributes` |

The installed copies of the two chess skills under the user's Codex skills
directory match their versioned sources. The thread's
`wally-evaluation-history.html` is also preserved as
`engine-output/wally-v02-evaluation/visualization.html`; it is not the sole copy
of the graph. Both comparisons were checked byte-for-byte on September 7, 2026.

Installed dependencies, Python caches, lock files, server logs and disposable
test output are excluded. Old process-local `clock.json` files are runtime
state, not the source of recorded timing evidence. New append-only
`clock.jsonl` ledgers, including explicit credits, are retained. Do not place
substantive notes only in an ignored log or an external scratch directory.

## Environment and dependencies

The following dated checkpoints retain their original counts and test results;
the current game/archive inventory is above.

The September 8 asset reorganization moved 185 top-level HTML/PNG files without
changing their bytes: nine pages to `replays/`, one template to `templates/`,
173 position diagrams to `images/positions/`, and two screenshots to
`images/replays/`. Builder, preview, future-image defaults, documentation and
installed skills use the new paths. All 145 Python tests and both offline replay
browser suites passed afterward. Published Netlify URLs are unchanged.

The follow-up cleanup grouped six early PGNs, four board journals, one validation
JSON and four visualization-trial notes into six `early-games/GAME-DATE/`
directories. The records retain their original filenames; note references use
the relocated paths. Shared display metadata now lives at
`replays/replay-metadata.json`. New scratchpad work defaults to the ignored
`scratch/board.json`, and bare `--state` filenames go under `scratch/` as well;
explicit paths remain available. This keeps ordinary experiments from changing
an archived game's board journal. Preserve substantive new evidence in a tracked
game directory when the experiment is complete.

All 146 Python tests passed after this follow-up, including the relocated PGN
rules checks and scratch-state isolation test. Both canonical and installed
skills passed the official validator and their hashes match.

The iPhone pawn-color report exposed a platform-font dependency in the replay:
both sides used U+265F, recolored by CSS. That character has an
[emoji presentation](https://unicode.org/emoji/charts/emoji-variants.html), so
iOS font/emoji fallback is the likely cause of the reported all-black pawns.
The template now embeds original SVG drawings for all six piece types, with
explicit White/Black fills and outlines, and all eight replay pages were rebuilt.
Their saved PGNs, positions, results and per-move evaluation records match the
previous archives. Older replays now also inherit the current template's explicit
White-side default and evaluation explanatory wording.

All 146 Python tests and all three offline replay browser suites passed after
the SVG update. Checks included 390-by-844 mobile/touch emulation, visible SVG
geometry, pawn contrast, promotion/rewind, flipping, scores and playback. The
screenshots in `images/replays/` were inspected and the new replay opened in the
embedded browser. These checks used Edge. Mike subsequently redeployed all eight
pages and confirmed that they display correctly on his iPhone. All drawings are
inline, so each replay still deploys as a single HTML file.

The verified development environment on September 7, 2026 used Python 3.12.14,
Node.js 24.19.0 and Playwright 1.62.1 with an existing Edge installation for
headless checks. These are observed versions, not an asserted minimum support
matrix.

Game 10 added an explicit pause/resumption extension to the clock and a
read-only timing audit. The complete Python suite passed **128 tests** after
these additions. The installed play skill was synchronized and both its
canonical and installed copies passed the official validator. Search/rules/
evaluation sources remained unchanged throughout that trial.

- The engine, query interface, clock, recovery helper and evaluation exporter
  run with Python's standard library. No external chess engine, opening book
  or endgame database is required or permitted by the current experiment.
- Replay building and optional independent rules checks use `chess==1.11.2`
  under `.replay-deps/`. This dependency supplies rules/notation, not move
  evaluation. Rebuild commands are in `README.md`.
- Optional PNG board rendering used Pillow 12.3.0. The default ASCII/FEN inspection
  and HTML reports do not depend on those PNGs.
- The scored replay HTML is self-contained and works offline. The separate
  interactive evaluation graph uses pinned D3 7.9.0 from its declared CDN.
  Its inline source and already-built preview are both versioned. Rewrapping
  the fragment used the installed visualize skill's renderer.
- Official skill validation used the skill-creator validator with
  `PyYAML==6.0.2` in `.skill-deps/`. Skill consumption does not need PyYAML.
- Live play needs Astra, a compatible embedded-browser control integration,
  and a Chess.com bot session. Those services are environment requirements,
  not repository code. Reacquire the browser's supported API instead of relying
  on saved element IDs or coordinates.

## Publication and remaining environment work

Setup and skill-use instructions are now in `SETUP.md`; the source archive and
Git-history bundle are generated from a clean commit and exclude dependencies.
The optional chart checker now accepts a browser channel instead of requiring
Edge. Fresh-source validation is recorded in `PACKAGING-VALIDATION.md`.

The configured `origin` is `https://github.com/mikepfrank/astra-chess.git`, and
the published branch is `main`. See [PACKAGING.md](PACKAGING.md) for subsequent
pushes and source/history packages. No `LICENSE` file has been added. An actual
live game in another assistant session/OS remains a separate experiment. Historical machine paths
are retained in notes and old ledgers; relocated workflows use the actual
checkout and rediscover the embedded browser API. Saved games are evidence,
not opening/endgame knowledge. The staged clock described above was implemented
before game 11; earlier trial ledgers retain their original controls.

Git previously normalized Windows line endings in saved records on archive,
changing their SHA-256 hashes. `.gitattributes` now preserves exact engine and
evidence bytes. This changes how Git stores those files, not the recorded
positions, timestamps, original hash claims or engine behavior.

The original recovery checkpoint is commit `c1ac0eb`: the complete scored game-9
archive and recovery machinery passed 110 Python tests, plus offline replay UI
checks. Both skills passed the official validator. An independent read-only
recovery exercise reconciled a pending promotion with an observed accepted
promotion and opponent reply, without repeating the move or inventing its
submission timestamp. Subsequent changes should retain comparable evidence.
