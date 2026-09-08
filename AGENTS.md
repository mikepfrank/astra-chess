# Astra chess experiment

Mike is Michael P. Frank, a reversible-computing researcher and AI enthusiast.

## Durable workflows

- For an authorized live game or its resumption, read
  [skills/astra-chess-play/SKILL.md](skills/astra-chess-play/SKILL.md).
- For replay pages, historical engine scores, and the collection index, read
  [skills/astra-chess-archive/SKILL.md](skills/astra-chess-archive/SKILL.md).
- Canonical skill sources are versioned here; installed copies live in the
  user's Codex skills directory. Keep copies synchronized when changing them.

On recovery after compaction, run `python resume_chess.py` to list journals and
`python resume_chess.py --game GAME-SLUG` for the user-intended game. Reconcile
the durable journal, pending action, clock and latest query with a fresh view
of the embedded browser before making a move. A saved pending move may already
have been played, or may still be in a promotion selector. The read-only helper
does not inspect the browser, reset time, or authorize a new game.

The experiment uses this repository's from-scratch engine, without external
engines, opening books, or endgame databases. The live journal supports either
color with `init --side white|black`; White is the default. Use one hour of
cumulative own-turn time, excluding the bot's thinking. User instructions can change the experiment. Preserve timestamped
records and only refund time under explicit user authorization.

Mike subsequently selected 90 minutes for the first 40 own moves, 30 more after
move 40, and a 30-second increment per own move for future games. Before the
next trial, implement/test that policy as described in
[TIME-CONTROL-NEXT.md](TIME-CONTROL-NEXT.md); the existing fixed-total initializer
does not yet implement it. Do not apply it retrospectively to game 10.

`ENGINE.md` is the maintained interface reference; `docs/engine-design.md`
documents evaluation formulas, search semantics, goal criteria and options.
Keep the design reference synchronized with engine changes. `game.json`, `clock.jsonl`,
saved query requests/results, and any unresolved `continuation.md` are recovery
evidence; a conversation summary is not a substitute. Archive or development
requests do not start another game or publish a site.

## Repository coverage

Keep standalone replay pages and the collection index in `replays/`; the shared
display metadata is `replays/replay-metadata.json` and the interface source is
`templates/replay.template.html`. Keep early trial PGNs, saved board journals,
validation and trial notes in `early-games/GAME-DATE/`, retaining their original
filenames. The scratchpad defaults to `scratch/board.json`; bare `--state`
filenames go under `scratch/`, while explicit paths are honored. Move substantive
new evidence into a tracked game directory instead of leaving it only in
ignored scratch output. Save position/candidate
PNGs in `images/positions/` and replay screenshots in `images/replays/`.
The live helper keeps its candidate PNG in `engine-games/GAME-SLUG/images/`.
Existing analysis reports and associated artifacts remain in `engine-output/`.
Use these directories for future outputs; Netlify uploads still use a standalone
`index.html` at each project's root.

Keep new authored chess tools, skills, reusable visualization sources, game
evidence and substantive notes in this repository and commit them at completion
checkpoints. Preserve the dependency/cache/runtime exclusions in `.gitignore`.
Check task-owned assets outside the repo before assuming a clean `git status`
means coverage is complete. [REPRODUCIBILITY.md](REPRODUCIBILITY.md) records the
equipment inventory and the user's intention to prepare a public package later.
