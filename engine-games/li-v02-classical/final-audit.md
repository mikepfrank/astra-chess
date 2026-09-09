# Game 11: final record and clock audit

Read-only checks were performed after play with the project's rules and the
existing local `chess==1.11.2` rules package. No external engine, book, tablebase,
site evaluation, or network analysis was used. Separate audit agents checked
record/rules consistency and clock/query accounting; they did not select moves
or contribute analysis during play. These checks establish record consistency,
not optimal play or the accuracy of heuristic scores.

## Actual game and candidate records

- All **139 actual plies**, their SAN strings, and **140 FENs** agree between
  the journal, Astra rules, and the independent rules package. FEN comparison
  preserves the double-push en-passant target convention.
- The complete legal-move sets agree in all 140 actual positions.
- The PGN parses without errors and matches the journal's moves, players,
  result, and termination. `TimeControl "-"` reflects the site's untimed game;
  the unilateral classical clock is documented in `game.json`, `clock.jsonl`,
  and `experiment.md`.
- The final FEN is `8/8/4K3/7k/8/8/8/8 b - - 0 70`. Both rule implementations
  confirm insufficient material after **70.Kxe6**; no earlier automatic
  game-ending condition occurred.
- The root task separately observed the final board and Chess.com's draw
  dialog. All 139 SAN plies copied from that visible move list in
  `browser-final-observation.json` match the journal exactly.
- **91 query request/result pairs** agree on requests, roots, and history,
  including the two hypothetical prefix plies in the move-43 child query.
- **248 candidate lines**, comprising **1,601 plies and 1,849 positions**, replay
  legally in both rule implementations. Their SAN and FENs match. The six
  reported terminal endings were verified: one mate and five insufficient-material
  draws.

## Frozen engine and effective search

Every result reports engine 0.2 and this source fingerprint:

```text
96e9ed243d69eede25b24c4c22248753053ee162b51fd0eb4cc081f47a311174
```

It matches current source and trial-start commit `b613424`. The fingerprint
covers `rules.py`, `search.py`, and `diagnostics.py`, hashing each filename,
a NUL byte, and its raw source bytes in that order. It does not fingerprint
the entire environment or browser integration.

There were 49 single-query turns and 21 two-query turns. Completed depths were:

| Depth | Queries |
| --- | ---: |
| 4 | 4 |
| 5 | 23 |
| 6 | 22 |
| 7 | 31 |
| 8 | 10 |
| 9 | 1 |

The median completed depth was 6. Requested ceilings ranged from 4 to 14;
90 searches reached their deadline while retaining completed iterations.
No result reported fallback, error, or query-budget overrun. The sole depth-9
result was `turn-41-query-2.json`.

The queries report **20,780,390 nodes**, including **17,608,762 quiescence nodes**.
Reported search elapsed totals **1,384.407 seconds**; the ledger's wider query
envelope totals **1,387.817124 seconds**. These are overlapping measurements,
not additional charges. All query intervals fall inside charged own turns.

Diagnostics were enabled and reported complete throughout. Optional mobility,
restricted-piece and king-exposure evaluation, and threat extensions, remained
off. There were 24 root-restricted queries, including the hypothetical-position
analysis after `Rh7 Ke3`; no goal-mode searches were made. Reserve clipping
reduced the requested budgets on moves 16, 23, and the first query of move 49.

## Clock reconciliation

| Item | Seconds |
| --- | ---: |
| Initial allowance | 5,400.000 |
| Increments earned by 70 verified own moves | 2,100.000 |
| Stage credit earned once after move 40 | 1,800.000 |
| Total earned allowance | 9,300.000 |
| Charged own time | **6,596.720** |
| Remaining | **2,703.280** |

Every turn's charge exactly matches its supplied first-observation-to-accepted-
submission timestamps. There are no refunds, extensions, pauses, or cumulative
game-budget overruns. The stage credit was applied once at event 305, after
40.Rxf7. The first 40 own moves used 3,560.552 seconds; move 40 had 3,009.448
seconds remaining before its credits and 4,839.448 afterward.

Turn-allocation overruns occurred on moves 8 (+1.450 seconds), 24 (+8.299),
33 (+13.564), 36 (+22.852), 43 (+6.626), and 49 (+118.423). They were planning-
target overruns, not cumulative clock violations. The two longest turns were
49.a5 at 358.423 seconds and 43.Rh7 at 246.626 seconds. Move 49 includes about
218 seconds between the second query's end and the decision event; the ledger
alone cannot establish the cause. The root task observed a context recovery
during that turn, and did not refund any part of it.

First observation through final submission spans **7,856.939 seconds**
(2:10:56.939). The **1,260.219 seconds** between own-turn intervals were excluded.
Those gaps include bot, observation, and recording latency; they cannot all be
identified as pure bot thinking. Even including every such gap would leave
1,443.061 seconds under the earned allowance. Late journal entry did not reset
the clock: supplied earlier observation times remained the charging boundary.

The generated [time audit](time-audit.md) provides turn and ten-move-block
breakdowns with source snapshot hashes. Reproduce that report from the repository
root with:

```text
python audit_game_time.py --game li-v02-classical --output-prefix engine-games/li-v02-classical/time-audit
```
