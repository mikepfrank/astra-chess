# User-selected staged time control

During game 10, Mike selected this policy for subsequent trials. It is now
implemented as `play_engine_game.py init --time-control classical`:

- Start with 5,400 seconds (90 minutes) of Astra's own time.
- Credit 30 seconds after every verified own move, starting with move 1.
- Credit 1,800 seconds (30 minutes) once, after the 40th verified own move.
- Exclude the bot's thinking with `--own-time-only` (the live helper's default).

This is the chosen experimental policy, not a claim that every FIDE classical
tournament uses the same control. It remains a cooperative clock: overruns are
reported and preserved, rather than enforced by the bot site.

## Starting a new trial

```text
python play_engine_game.py init --game GAME-SLUG --round ROUND --opponent-name BOT-NAME --opponent-elo RATING --time-control classical --own-time-only
```

Use the actual opponent, rating, unused game slug and original-session round.
Add `--side black` when appropriate. Initialization leaves the clock idle;
start it at the earliest observation of Astra's turn. `classical` requires
`--clock-mode game`. The CLI's `fixed` default retains the previous one-hour
setup, so select the new preset explicitly.

## Accounting and allocation

Only distinct verified own moves earn credits. Choosing a candidate, a
submission attempt, a rejection, a query, or a bot move earns no time. The
ledger derives credits from its verification events; replaying the ledger does
not award them again. The stage depends on the number of verified Astra moves,
for either color, rather than a manually entered full-move number.

The initial total is exactly 5,400 seconds. After the first verified own move,
the credited total is 5,430 seconds. After the 40th it is 8,400 seconds: the
initial allowance, 40 earned increments, and one stage grant. Remaining time
subtracts the recorded own-turn usage. No future increment or stage grant is
available before it is earned. The settled balance is checked before a move's
credits; an overrun stays recorded even if a subsequent grant makes the balance
positive.

The preset's targets are 120 seconds for an ordinary turn or 240 seconds for a
concrete critical position, including a 40-second reserve for review and move
entry. Before the stage, the helper forecasts time over the own moves still
needed to reach move 40 using only the currently credited balance. Afterward it
looks toward 20 further own moves, with a rolling minimum horizon of 12. The
forecast caps ordinary allocations; critical allocations can use twice that
forecast. Both remain capped by their targets and the available game balance.
Inspect the current `remaining_seconds` and `query_available_seconds` instead
of assuming the full target is available.

The normal first query remains 15 seconds, depth 8, three candidates and
diagnostics enabled. The 180-second cap on any individual query also remains.
Use additional search for a specific unresolved question, while retaining time
to inspect counterplay and enter the move.

With an accepted submission timestamp, verification settles that turn at
submission, excluding subsequent bot/confirmation time. Without one, charging
continues through verification and the uncertainty is recorded. Deliberation,
queries, commentary, UI entry and retries are own-turn time. Compaction and a
critical-position designation do not reset it. Refunds or extra time still
require explicit user authorization; preserve the original events.

## Historical boundary

Existing journals retain their original settings. Game 10 remains under its
original 3,600-second allowance plus the separately authorized 900-second
extension. Do not apply the new preset retrospectively, erase its initial
overrun, or treat its paused waiting interval as deliberation. The fixed-total
and per-move modes remain available for reproducing earlier experiments.
