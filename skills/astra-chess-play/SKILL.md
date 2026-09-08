---
name: astra-chess-play
description: Play or resume the Astra chess experiment using its local from-scratch engine, embedded browser, verified move journal, and cumulative own-turn clock. Use for an authorized live game or analysis with this machinery.
---

# Astra chess play

Use the engine as evidence for a decision: record an independent candidate,
inspect its counterplay, choose a move, and verify what actually happened.
Loading this skill does not start a game. Continue an already authorized game;
do not infer permission for the next game from an archive or development task.

## Locate and recover

Find the repository containing `ENGINE.md`, `play_engine_game.py`, and
`astra_engine/`. The existing checkout is
`C:/Users/MikeFrank/Documents/ChatGPT/Chess`; prefer a user-specified checkout
when relocated. Commands below run there with a working Python executable.
Read `ENGINE.md` for search semantics and current options. Use
`play_engine_game.py --help` rather than guessing flags.

At entry or after compaction, run the read-only recovery helper:

```text
python resume_chess.py
python resume_chess.py --game GAME-SLUG
```

It summarizes verified moves/FEN, clock, pending action, phase, source
fingerprint, and recent queries. Treat `engine-games/GAME-SLUG/game.json` and
the append-only `clock.jsonl` as durable evidence, not the conversation's
recollection. Read referenced query results or local continuation notes only
as needed. A summary cannot establish the current browser position.

Reacquire the user's embedded sidebar tab using the available browser tools
and inspect fresh UI. Never memorize tab IDs, element IDs, or coordinates.
Reconcile its move list and board with the last verified FEN **before acting**.
For a pending move, establish whether it is unplayed, partly entered (such as
a promotion chooser), accepted, or rejected. Do not repeat a move because a
tool response or context was lost. If the user completed an action, verify
that actual move before advancing the journal. An unresolved mismatch needs
reconciliation, not another click or an invented timestamp.

If an observation or UI action has not yet reached the journal, preserve its
exact UTC timestamp and partial-action state in the game's `continuation.md`.
Refresh that small note when handing off; mark resolved facts so it cannot
override newer journal/UI evidence. An interrupted active turn remains active.

## Experiment boundaries

- Use only this project's rules, hand-written evaluation, and search for move
  assistance. No external engines, opening books, endgame databases, site
  hints, takebacks, or other agents choosing moves. Recorded games are evidence,
  not search knowledge. Rules-only validation after play is separate.
- Use the embedded browser so play does not interfere with the user's desktop.
  Browser tool availability can change; discover its current supported API.
- Freeze engine rules/search/evaluation during each trial. Compare the current
  source fingerprint with saved query fingerprints on recovery; explain any
  mismatch before relying on a mixed-version experiment. Persist request/result
  files, including failures, and disclose effective options.
- The journal supports either color from the standard start. Initialize with
  `--side white` (default) or `--side black`, matching the observed browser setup.
  The saved `player_side` controls own-turn accounting; old journals default to
  White. Arbitrary FENs are supported for analysis, not live initialization.

## Clock and each turn

Before a new trial, read `TIME-CONTROL-NEXT.md`: Mike selected 90 minutes for the
first 40 own moves, 30 more after move 40, and a 30-second increment from move 1.
Implement and test this staged policy before using it; the fixed-total helper
does not yet implement stages/increments. Do not retrofit it onto game 10.

Game 10's original allowance is **3,600 seconds of Astra's own time**, excluding the bot's
thinking. It includes deliberation, queries, commentary, UI entry, and retries.
Start from the **first observation** of an own turn, retaining that timestamp
even if reconciliation or journal entry takes time. A verified move settles
at its accepted submission timestamp; missing timestamps incur conservative
charging with recorded uncertainty. A pending promotion is not yet submitted.

Aim for 60–90 seconds ordinarily, 120–180 for a concrete critical position,
with 40 seconds for review and entry. These are adjustable allocation targets;
the shared clock is the total budget. Compaction, rejected clicks, and marking
a position critical do not restart it. Only an explicit user-authorized credit
justifies a refund; use `refund_turn_time` as documented in `ENGINE.md`, with
a reason and unique ID, preserving all original charges and timestamps.

Initialize once, only for a new authorized trial with an unused slug and the
correct original-session round number:

```text
python play_engine_game.py init --game GAME-SLUG --round ROUND --opponent-name Wally --opponent-elo 1800 --game-seconds 3600 --own-time-only
```

Add `--side black` to play Black. Wait for and record the first White move with
`turn --opponent SAN --observed-utc UTC`; initialization does not start the clock.
Check board orientation visually before entering moves. Query scores favor the
query root's side, so a positive score on a Black turn favors Black.

For each newly observed own turn:

1. Record the observed opponent SAN and earliest UTC time with `turn`. Omit
   `--opponent` only for White's initial turn. Set `--initial UCI` and a concrete
   `--concern`, or immediately use `candidate --move UCI` before searching.
   On an already active turn, use `candidate`, `query`, or `critical`, not `turn`.
2. Start with `query --seconds 15 --depth 8 --candidates 3`; diagnostics are on
   by default. Read completed depth, fallback status, candidate replies, and
   diagnostic coverage. A depth ceiling is not an achieved depth.
3. Inspect prospective ASCII/FEN boards, or use the scratchpad/`--png` when a
   picture helps. Scratchpad state defaults to `scratch/board.json`; bare
   `--state` names go under `scratch/`, and explicit directories are honored.
   Use this separate scratch state instead of modifying completed early board
   journals in `early-games/GAME-DATE/`. Save scratchpad PNGs in `images/positions/`: a bare scratchpad
   `--png candidate.png` filename is routed there, while an explicit directory
   such as `--png scratch/candidate.png` is honored. Review the **opponent's**
   checks, captures, threats, newly opened files/diagonals, loose pieces,
   restricted escapes, and promotion
   possibilities after each serious candidate. A clean diagnostic is not a
   safety certificate. A principal variation covers one continuation.
4. Spend additional time only on a concrete unresolved question. `critical`
   changes allocation without resetting elapsed time. Use a deeper query with
   `--root-moves` to compare selected own moves while leaving all opponent
   replies available, or a focused goal probe. Experimental evaluation flags
   and `--threat-extensions 1`/`2` are optional; assess their cost and record use.
5. Use `choose --move UCI --note "..."`, explaining whether the engine changed
   the initial idea and what it revealed. Inspect the printed resulting board.
   Add `--png` for `engine-games/GAME-SLUG/images/candidate.png`. This writes a
   pending choice; it does not play it.
6. Enter that move in the browser. Capture actual submission time after any
   promotion selection, then inspect fresh UI. Record `submit` if useful and
   call `verify --submitted-utc UTC --verified-utc UTC` **only after the move is
   observed as accepted**. The helper checks legality, not the real browser.
   An actual rejection uses `reject --note "..."`; uncertainty requires fresh
   observation before rejection, verification, or retry. Keep the same clock.
   If a human completed the move and its submission time is unknown, omit
   `--submitted-utc`: use `verify --verified-utc UTC --note "Human completed
   the move; exact submission time unavailable"`. Do not call `submit` with
   its default current timestamp to stand in for the missing human action.
   If that same observation also reveals the opponent's reply, retain the same UTC
   for the next `turn --opponent SAN --observed-utc UTC` after verification.
7. Observe the actual bot reply before choosing the next move. Verify a final
   own move before `finish --result RESULT --termination checkmate`; a final opponent
   move can be passed to `finish --opponent SAN`. Use the observed result.

Every command above also takes `--game GAME-SLUG`. Keep UI timestamps and
journal updates close together, and avoid recording stale observations as new.

## Focused questions and arbitrary positions

The live helper's `query --after UCI,UCI --goal JSON` branches hypothetically
without changing the game. A `--goal` defaults to adversarial proof-only;
`--witness` additionally seeks cooperative examples. For an arbitrary FEN,
write an `astra_chess.py query` JSON request and attach the **same live clock**
with `--game-clock engine-games/GAME-SLUG/clock.jsonl`. Preserve authentic
`history_fens` when available; a lone FEN cannot establish prior repetitions.

Consult `ENGINE.md` for atomic capture/avoid-capture, castle, check, mate, and
stalemate goals. Capture targets identify the piece initially on a square.
`forced` proves the bounded goal against every defense; a
`cooperative_witness` does not. `unknown`, timeout, and a rejected query are
not proof. Safety goals hold only through their tested horizon. Query again
from the actual reply instead of treating a representative proof line as
the opponent's prescribed moves.

At game end preserve the PGN, journal, queries, fingerprint, final clock, and
specific examples of help or failure. Separate heuristic scores, finite proofs,
and actual results. One result does not establish a playing rating or win rate.
For a requested replay, use the companion `astra-chess-archive` skill.
