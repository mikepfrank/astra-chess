---
name: astra-chess-archive
description: Archive a completed Astra chess experiment as a standalone replay HTML page, with optional historical engine evaluations and a collection-index entry. Use this project's PGN, journal, replay template, and recorded search evidence.
---

# Astra chess archive

Produce a replay that can be uploaded as a standalone HTML page, preserving
the actual game and distinguishing recorded engine evidence from later analysis.
Archiving does not authorize starting another game or publishing a deployment.

## Sources and recovery

Locate the repository containing `ENGINE.md`, `build_replay.py`,
`replay.template.html`, `replay-metadata.json`, and `index.html`. The current
checkout is `C:/Users/MikeFrank/Documents/ChatGPT/Chess`; use the user-selected
checkout if relocated. Run commands there with a working Python executable.

Use `python resume_chess.py` to locate the intended trial, then
`python resume_chess.py --game GAME-SLUG` to read its durable state. For engine
games, `engine-games/GAME-SLUG/game.pgn`, `game.json`, `clock.jsonl`, query
request/results, and `experiment-notes.md` supply the evidence. Earlier replays
may have only a standalone PGN. Inspect the actual records rather than relying
on a remembered title, move count, or result. Do not finish a still-live journal
merely to build an archive.

## Build the replay

1. Verify the PGN's SAN, result, termination, date, players, rating, and original
   session round. Where a journal exists, match its UCI/SAN/FEN sequence. Keep
   historical PGN identities intact; presentation names belong in metadata.
2. Add the round to `replay-metadata.json` with the model and thinking level
   actually used. Titles follow `Astra (Ultra) vs. Wally` for that configuration;
   the board name is `Astra`. Do not infer all prior games used Ultra. Identify
   engine-assisted trials/version in the subtitle and index where relevant.
3. Reuse `build_replay.py` and `replay.template.html`, preserving the animation,
   clickable move list, keyboard/slider controls, board flip, and PGN download.
   The builder uses an existing rules-only dependency; the generated HTML has
   no external runtime dependencies. A resignation requires explicit
   `--ending resignation`; checkmate is validated from the final board. The
   current template supports decisive games, so handle a draw deliberately
   rather than mislabeling it as a win or resignation.

```text
python build_replay.py --pgn engine-games/GAME-SLUG/game.pgn --output GAME-replay.html --subtitle "Engine-assisted trial"
```

When historical evaluation data is available, pass `--evaluations DATA.json`.
Extract it from a verified journal with
`python export_evaluations.py --game GAME-SLUG --output DATA.json`.
This reads original searches and leaves missing values explicit. The archived
game-9 wrapper in `engine-output/wally-v02-evaluation/` reproduces its dataset.
The exporter and score overlay currently require White-player trials. For a
Black trial, first adapt and validate player identity, frame parity, result and
score perspective; do not feed Black-root scores into White-only assumptions.

## Evaluation meaning

Use the saved in-game query that actually evaluated the selected move from the
exact actual pre-move FEN and produced its actual post-move FEN. Prefer the
latest qualifying completed search in that turn's original query order. Retain
source paths/hashes, achieved depth, UCI/SAN, and score perspective. Missing or
fallback-only evidence stays explicitly missing; do not run new analysis and
present it as the original assessment.

- The label shown after White's move reports the historical search score for
  that chosen move, calculated before play. It is not a fresh post-move search.
  Positive pawn scores favor White in these White-root game records; other
  query roots require explicit perspective conversion.
- A Black-reply frame has no new evaluation unless one was actually recorded.
  Either show that absence or identify a carried value as the **previous
  White-move evaluation**, naming the move; never silently relabel it current.
- Mate encodings are not large pawn advantages. `mate_in_plies` measures from
  the pre-move query root, including the chosen move. A user-facing “mate in N”
  label must state that origin, or correctly adjust to the displayed board.
- Keep bounded goal proofs separate from numeric evaluations. In game 9,
  move 30 has a post-Qf8 checkmate proof within two plies with Black to move:
  mate on White's next turn against every defense. Move 31 is actual checkmate
  without a search score. Do not manufacture numeric values for either.
- Score changes include the intervening opponent reply and different search
  horizons. They are not isolated move-quality grades or win probabilities.

## Index, verification, and delivery

Update `index.html` with the original session game number, correct date,
model/thinking level, opponent rating, move count, result, finish, and engine
trial label. Update the collection count/description too. Preserve existing
deployment links. The established collection uses separate Netlify projects for
the index and each replay. If a new project's URL is unknown, identify any
proposed project name clearly for the user's deployment; do not claim it is live.
Use relative links when the user instead wants a combined deployment. Tell the
user which files to upload when index and replay are hosted separately.

Build and inspect the replay in the embedded sidebar browser. Check opening,
capture/castling/promotion frames present in this game, final board and result,
move navigation/playback, and narrow layout. With evaluations, check an ordinary
White move, the following Black frame, a mate/proof frame, and missing data.
Validate embedded move/FEN/evaluation alignment and run relevant repository
checks after builder/template changes. A generated page alone is not UI QA.

Review `git status`/diff, exclude runtime junk and unrelated user changes, and
commit requested machinery, reusable skills, replay/index, and game evidence
when authorized. Keep source and generated output reproducible. Open the result
in the sidebar, provide its file link, and report validation and any remaining
deployment step. The user normally handles Netlify publishing.
