# Game 11: Li (2000), Astra White

Authorized trial on September 8, 2026 in the embedded Chess.com browser.
Opponent rating 2000 was observed in the bot selector. All site assistance
(evaluation, engine, suggestions, threats, feedback) was disabled.

Machinery checkpoint: `b613424`. Rules/search/evaluation frozen throughout the
trial, using the existing v0.2 engine without external engines, books or
tablebases. Each saved query includes the engine fingerprint and options.

Classical own-time clock: 5400 seconds initially, 30 seconds after each verified
own move, 1800 seconds after own move 40. Normal/critical turn targets 120/240
seconds; 40 seconds reserved for manual review and UI entry. Actual accepted
submission timestamps exclude the bot/confirmation interval. No refunds planned.

Workflow: independent candidate and concern, initial 15-second search with
depth ceiling 8 and three candidates, counterplay/board review, focused
follow-up when needed, manually chosen and browser-verified move. Default
diagnostics enabled; optional features recorded individually when used.

## Result

**Draw, 1/2-1/2, after 70.Kxe6**, with only the two kings remaining.
Chess.com's visible final dialog confirmed insufficient material. Astra played
White throughout; Li's displayed bot rating was 2000. The game started on
September 8 and ended at 02:09:59 UTC on September 9 (still September 8 locally).

The [PGN](game.pgn), [journal](game.json), [clock ledger](clock.jsonl), all
query request/result pairs, and [final browser observation](browser-final-observation.json)
are preserved here. The 139 SAN plies transcribed from the final visible browser
move list match the journal exactly. The journal records an initial candidate,
concern, selected move, and explanatory assessment for each of the 70 own turns.
These are durable turn notes, not a verbatim export of every chat message.
The [final audit](final-audit.md) records independent rules checks of the game
and all candidate lines, plus clock and frozen-source verification.

## What the engine contributed

The engine was useful for concrete tactics and move-order checks. These examples
are from searches made during play, not a retrospective stronger-engine review.
Scores below are heuristic pawn units from White's perspective.

| Decision | Evidence and effect |
| --- | --- |
| 9.Qxd4 | The depth-5 query validated the queen recapture (+0.13) against 9.Nxd4 (-1.03), where `c5 Nde2 Nxe4` loses a central pawn. |
| 20.b3 | My provisional `Qg7+` would hang the queen to `Kxg7`. The focused depth-6 comparison scored it -8.79; b3 was +0.56. This was a straightforward error in my own initial deliberation that the engine caught. |
| 25.a4 | Fresh board inspection caught a different error: I had carried `Rb5` over from a prior variation that assumed Black had played ...a5. In the actual position, the pawn was still on a6 and could take that rook. The current search favored a4. |
| 43.Rh7 and 44.Re7+ | An arbitrary-future-position query after `Rh7 Ke3` found that grabbing h4 loses immediately to `Ra1#`. I used Re7+ instead when ...Ke3 actually occurred. This was the clearest demonstration of the future-position interface preventing a mating oversight. |
| 55.h4 | The engine corrected my initial Kg3 idea. Black's king and rook both attacked g5; h4 added a second defender. The depth-7 comparison was +3.16 for h4 versus +1.93 for Kg3. |

Relevant evidence: [move 20 comparison](turn-20-query-2.json),
[move 43 hypothetical query](turn-43-query-2.json), and
[move 55 comparison](turn-55-query-1.json). The query files include the exact
starting FEN, moves, intermediate positions, score, depth, options, and fingerprint.
The move-43 example was a normal search from a hypothetical position, not a
goal-mode all-defenses proof.

## Where the conversion stalled

After 51.Rxh4+, I had rook and two connected kingside pawns against rook.
Li kept the king active and used lateral rook checks and a third-rank cut-off
to restrict my king. I did not establish a forcing route to promotion. Several
rook maneuvers preserved positive evaluations without producing durable progress.
At move 58 I preferred a rook interposition to a slightly higher-scoring king
retreat, but Li declined the exchange and returned to the checking position.

The main decision for review is **62.Re6**. I deliberately chose it to support
g6, offering h4 if necessary. The [focused depth-8 comparison](turn-62-query-2.json)
preferred keeping both pawns with Rd4 (+3.18), while rating Re6 +2.46. I overrode
that preference because the latter gave me a concrete plan. I inspected the
displayed continuation but did not run a separate child-position query after
the obvious immediate capture **62...Kxh4** before committing.

Li took that pawn. The [next focused query](turn-63-query-2.json), again completing
depth 8 from its new root, reduced the evaluation to +0.25 and exposed a
defensive rook-and-king coordination plan. Li chose a different actual defense,
...Rg3+ followed by ...Rg5 and ...Kh5, and eventually removed g6. I then chose
safe liquidation. The finish was `68.Kf6 Rxg6+ 69.Ke5 Rxe6+ 70.Kxe6`.

This is evidence of both an overoptimistic strategic override and a search-horizon
limitation. It does **not** prove that the position before move 62 was objectively
won, or establish the exact move at which a theoretical win disappeared. No
external engine or tablebase has been used to settle that question. The earlier
+3-ish numbers should not be mistaken for winning probabilities or proofs.

## Clock and search cost

The [timing audit](time-audit.md) records:

| Quantity | Time |
| --- | --- |
| Initial allowance | 90:00 |
| Earned stage credit after move 40 | 30:00 |
| Earned increments, 70 x 30 seconds | 35:00 |
| Total earned allowance | 155:00 |
| Charged own time | **109:56.720** |
| Final remaining time | **45:03.280** |
| First 40 own moves | 59:20.552 |
| Recorded query wall time, 91 queries | 23:07.817 |

There were no refunds, extensions, excluded pauses, or overall clock overruns.
The mean own turn was 1:34.2 and median 1:21.1. Sixteen turns exceeded 120 seconds;
the full audit distinguishes these intervals from engine-query time. Move 49
was longest at 5:58.423, spanning a context recovery during the active turn;
its full observation-to-submission interval remained charged. Moves 41-50
consumed 27:41.2, the slowest ten-move block.

Queries accounted for about 21% of the charged time. The remaining 79% includes
deliberation, commentary, UI work, orchestration, and interruptions. The logs
do not separately measure those costs, so they cannot all be attributed to
browser latency or to thinking. The cooperative clock starts at the first
recorded observation of my turn and stops at accepted submission; it does not
independently timestamp the exact instant Li completed a move.

All 91 searches used the same engine fingerprint:

```text
96e9ed243d69eede25b24c4c22248753053ee162b51fd0eb4cc081f47a311174
```

Diagnostics were enabled. Optional mobility, restricted-piece and king-exposure
evaluation terms, and threat extensions, remained off. Completed depths ranged
from 4 to 9; requested ceilings were often higher. There were no fallback results
or query errors. Most searches stopped at their time budget after completing
earlier iterations, which is normal iterative-deepening behavior.

## Improvements worth discussing

1. **Probe the obvious defensive capture before a strategic sacrifice.** The
   existing future-position interface was highly effective at move 43. Applying
   it to `62.Re6 Kxh4` would have exposed the evaluation collapse before the move.
   Comparing only root candidates and their representative lines was insufficient.
2. **Require evidence of progress in quiet endgames.** Distinguish maintaining
   a material-based score from advancing the king, improving the pawn blockade,
   or establishing a favorable exchange. Repeated high-scoring shuffles should
   trigger a specific defensive-resource investigation, not an impatient sacrifice.
3. **Reserve deeper searches for such concrete questions.** A search from the
   relevant child position can be more informative than simply increasing every
   root search's ceiling. This trial does not show that a faster implementation
   alone would solve the endgame-planning problem.
4. **Tighten the non-search workflow.** Query time was a minority of total own
   time. More concise deliberation and prompt journal entry should help keep
   ordinary turns near their targets while retaining the same verification steps.

These are proposed lessons, not new engine changes applied during the game.
The trial supplies one draw against a 2000-rated bot, not an estimate of Astra's
playing rating or a controlled measurement of the method's win rate.
