# Run Astra Search Lab from a fresh checkout

This repository preserves an experiment combining an assistant's deliberation
with a small chess engine written from scratch. The engine generates candidate
lines and bounded goal proofs; the assistant inspects them and operates the
embedded chess board. It does not play a browser game unattended by itself.

The engine imports no external chess engine, opening book or endgame database.
Saved games are experimental evidence, not search knowledge.

## Start with the local tools

Use Python 3.12 to reproduce the tested environment (3.12.14 on Windows).
The engine, journal, clocks, recovery, evaluation export and ASCII diagrams
require only Python's standard library. From the extracted source folder or
cloned repository:

```text
python astra_chess.py --help
python resume_chess.py
python resume_chess.py --game wally-v02-black
python astra_chess.py query --request engine_examples/mate-in-one.json --output scratch/mate.json --html scratch/mate.html
```

The first three commands are read-only. The example runs a small local search
and writes an inspectable report under ignored `scratch/`; it does not start a
game. Open `scratch/mate.html` in a browser. See [ENGINE.md](ENGINE.md) for
arbitrary FENs, candidate limits, goals, recorded history and clock semantics.

Any replay HTML in `replays/` can be opened directly without installing
anything. These complete replay pages work offline. The collection `replays/index.html`
links to separate online deployments; the historical evaluation chart alone
uses D3 from a CDN and needs network access.

## Rebuild and validate replays

Create an isolated environment. Activation is optional; on Windows, replace
`python` below with `.venv\Scripts\python.exe` after creating it. On macOS/Linux,
use `.venv/bin/python`.

```text
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-replay.txt
.venv\Scripts\python.exe -m unittest discover -s tests
```

The second and third lines above are Windows commands. The only required test
and replay-build package is `chess==1.11.2`, used for rules/notation and independent
validation. The search engine never imports it. Existing installations under
`.replay-deps/` remain supported, but are not included in this package.

With the environment's Python, rebuild the latest replay:

```text
python export_evaluations.py --game wally-v02-black --output scratch/black-scores.json
python build_replay.py --pgn engine-games/wally-v02-black/game.pgn --output scratch/black-replay.html --subtitle "Engine v0.2 trial / Astra as Black" --evaluations scratch/black-scores.json
python serve_replay.py --page scratch/black-replay.html --port 8774
```

Open `http://127.0.0.1:8774/black-replay.html`. The server serves only the chosen
page on loopback. The source data and previous replay rebuild commands are in
[README.md](README.md).

For optional PNG diagrams, install `requirements-visuals.txt` (Pillow 12.3.0).
`board_scratchpad.py` supports ASCII without it. Its state defaults to
`scratch/board.json`, and bare `--state` filenames go under `scratch/`; an explicit
directory is honored. Archived early PGNs, board journals and trial notes live
under `early-games/GAME-DATE/`. Use a separate scratch state for experiments so
those completed records remain intact; preserve substantive new evidence in a
tracked game directory when finished.
Bare scratchpad `--png` filenames are saved under `images/positions/`; a path with an
explicit directory, such as `scratch/candidate.png`, is honored as supplied.
Keep reusable position images in `images/positions/` and replay screenshots in
`images/replays/`. Existing query/report artifacts remain in `engine-output/`.
The live helper's `choose --png` writes its candidate to the game's own
`engine-games/GAME-SLUG/images/` subdirectory.

## Optional browser checks

The recorded browser-test environment used Node.js 24.19.0 and Playwright 1.62.1.
`package.json` pins Playwright for these tests; Node is not an engine dependency.
For a new environment with package/browser downloads available:

```text
npm install
npx playwright install chromium
npm run test:replays
npm run test:reports
```

Or use an existing Edge installation without downloading another browser:

```text
node tests/test_replay_scores.cjs playwright msedge
node tests/test_replay_black.cjs playwright msedge
node tests/test_report.cjs playwright msedge
```

The replay checks exercise the offline pages. The separate historical-chart
check, `node engine-output/wally-v02-evaluation/check_visual.cjs playwright msedge`,
requires access to its declared D3 CDN. Browser channel availability depends on
the host; these instructions do not imply a completed macOS/Linux GUI trial.

## Use the assistant workflow

Open this repository in an assistant session with shell access and a supported
embedded browser. The recorded configuration was Astra with Ultra deliberation;
model and reasoning-option availability depend on the host session. These are
experimental settings, not a bundled model or a guaranteed strength rating.

The project's [AGENTS.md](AGENTS.md) routes live-game and archive work to the
two versioned skills in `skills/`. Ask the assistant to read the relevant
`SKILL.md` before a trial. For persistent installation, copy the two complete
skill directories to the host's configured Codex skills directory (the original
host used `~/.codex/skills/`), preserving their `agents/` files. Prefer this
checkout's paths over historical machine-specific fallback paths in the notes.

Before any live game, agree on the opponent, color and time control, verify the
actual embedded board, and use a new journal slug. Browser APIs and tab IDs must
be rediscovered in the new session. There are no account credentials or browser
control plugins bundled here. Compaction recovery reconciles saved state with
fresh UI; it must not repeat an uncertain move or silently reset the clock.

**Before the next trial:** implement and test the staged 90/40 + 30, +30s policy
in [TIME-CONTROL-NEXT.md](TIME-CONTROL-NEXT.md). It is selected for future play
but not implemented in the current fixed-total clock. Game 10's separate
extension and historical charges must remain as recorded.

## Preserve evidence when moving the repository

`.gitattributes` prevents line-ending conversion of engine source and recorded
evidence whose fingerprints refer to raw bytes. Do not rewrite old hashes to
conceal a source or record change. Saved UTC/monotonic timestamps, original
absolute paths and Git authorship are historical context, not portable active
clock state. Completed games may be replayed; do not resume their clocks.

See [PACKAGING.md](PACKAGING.md) for source/history archives and tomorrow's
GitHub handoff, and [REPRODUCIBILITY.md](REPRODUCIBILITY.md) for the inventory.
