# Equipment and reproducibility inventory

Mike intends to package this method for others to try in their own Astra
sessions, potentially through GitHub. That is a future packaging task. For now,
keep all authored chess equipment, source data and substantive experiment notes
in this local repository, including sources initially created in a thread's
visualization directory. Commit them at completion checkpoints.

## What is preserved

| Component | Repository sources |
| --- | --- |
| From-scratch rules, evaluation, search and optional diagnostics | `astra_engine/`, `astra_chess.py`, `engine_examples/` |
| Manual game journal, cumulative own-turn clock and recovery | `play_engine_game.py`, `astra_engine/clock.py`, `resume_chess.py` |
| Per-turn timing audit and future time-control policy | `audit_game_time.py`, `TIME-CONTROL-NEXT.md`, saved game timing reports |
| Prospective board visualization and query reports | `board_scratchpad.py`, `astra_engine/report.py`, `astra_engine/report.template.html` |
| Playing and archive procedures | `AGENTS.md`, `skills/astra-chess-play/`, `skills/astra-chess-archive/`, `ENGINE.md` |
| Design rationale and measured improvements | `IMPROVEMENT-PROPOSAL.md`, `ENGINE-CHANGES.md`, benchmark scripts and `engine-benchmarks/` |
| Game evidence and observations | `engine-games/`, source PGNs, saved board journals, and the `*-visualization-trial.md` notes |
| Replay build and collection | `build_replay.py`, `replay.template.html`, `replay-metadata.json`, `index.html`, replay HTML files |
| Historical evaluation extraction and graph | `export_evaluations.py`, `engine-output/wally-v02-evaluation/`, `engine-output/wally-v02-black-evaluation/` |
| Validation | `tests/`, retained browser-check images and experiment audits |

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

## What a later public package still needs

Provide clean-checkout setup and skill-install instructions, explain how to
select the model/thinking level and browser integration, and test the documented
workflow in a separate session. Review machine-specific fallback paths and
report portability limits explicitly; the historical chart's browser check
currently selects Edge directly. Package the authored code, procedures,
examples and evidence without bundling installed dependencies or treating saved
games as opening/endgame knowledge.

The current starting point is commit `c1ac0eb`: the complete scored game-9
archive and recovery machinery passed 110 Python tests, plus offline replay UI
checks. Both skills passed the official validator. An independent read-only
recovery exercise reconciled a pending promotion with an observed accepted
promotion and opponent reply, without repeating the move or inventing its
submission timestamp. Subsequent changes should retain comparable evidence.
