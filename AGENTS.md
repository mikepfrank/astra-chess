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
engines, opening books, or endgame databases. Current live-game defaults are
Astra as White and one hour of cumulative own-turn time, excluding the bot's
thinking. User instructions can change the experiment. Preserve timestamped
records and only refund time under explicit user authorization.

`ENGINE.md` is the maintained interface reference. `game.json`, `clock.jsonl`,
saved query requests/results, and any unresolved `continuation.md` are recovery
evidence; a conversation summary is not a substitute. Archive or development
requests do not start another game or publish a site.

## Repository coverage

Keep new authored chess tools, skills, reusable visualization sources, game
evidence and substantive notes in this repository and commit them at completion
checkpoints. Preserve the dependency/cache/runtime exclusions in `.gitignore`.
Check task-owned assets outside the repo before assuming a clean `git status`
means coverage is complete. [REPRODUCIBILITY.md](REPRODUCIBILITY.md) records the
equipment inventory and the user's intention to prepare a public package later.
