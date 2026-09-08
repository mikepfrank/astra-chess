# Game 10: Wally versus Astra, Black trial

User authorized a new Wally (1800) game and selected Black in the embedded
Chess.com browser. Astra (Ultra) plays Black with the same v0.2 rules/search/
evaluation as game 9. No external engines, books, databases, hints or takebacks.
Other agents assisted only with journal/clock development and record audits,
not move selection.

Pre-game machinery commit: `2f1b49c`. Five Black tests plus 33 clock/recovery
regressions passed. Engine sources unchanged; expected search fingerprint:
`96e9ed243d69eede25b24c4c22248753053ee162b51fd0eb4cc081f47a311174`.

Default queries: 15 seconds, depth ceiling 8, three candidates, diagnostics on;
optional evaluation terms and threat extensions off unless explicitly recorded.
Positive query scores favor Black. One hour cumulative own-turn time excludes
Wally's thinking and ends at accepted submissions. No refunds authorized for
this game. Setup/development occurred before Play and before the own clock.

This is a repeat trial with a changed color, not a controlled same-color repeat.
The archive/export score code was subsequently adapted for Black while building
this game's requested scored replay; original queries and journal are retained.

## Evidence from play

- 10...Nxd4 was the clearest tactical assist: my initial idea Bc5 was too early.
  Search found Nxd4 first, exploiting Qxd4 Bc5 pin to Kg1. A focused comparison
  completed depth 6, scoring Nxd4 +3.54 and Bc5 +0.14 for Black. Wally chose
  Nxd5; exd5 and a safe retreat after Rf2 preserved two extra knights for a pawn.
- 15...Bc5 pinned the rook on f2; this time I proposed the idea independently
  and the engine confirmed Bxf2+ after Bxd5, winning the exchange.
- 18...Qxd1 was a deliberate choice to simplify (+6.31) despite the deeper
  search preferring Qb6+ (+7.18). Both at completed depth 6. This reduced
  immediate risk but did not produce a fast conversion.
- 31...Rdc8 and 32...Nb5 increased c-file pressure; Wally's 33.Bxa5 left Rc1
  undefended, and 33...Rxc1 won his last rook.
- The engine repeatedly preferred modest material gains or retreating knight
  lines. I also spent too long deliberating in the winning endgame. The hour
  expired before checkmate, prompting a documented pause before move 45.
  The user then authorized extra time; the completed result is recorded below.
- The reserve allocator progressively curtailed searches, eventually rejecting
  move 42 despite several total minutes remaining. Its minimum 12 remaining
  turns and fixed 40-second reserve need reconsideration after this trial.
- UI entry initially required API troubleshooting; all own-turn retries were
  charged. Later entries used observed DOM locators in the embedded browser.
- Invalid helper commands for a mistyped Python path and wrong rear-rook
  source square were rejected; no illegal browser move was submitted, and
  original observation times were retained. No time refund was applied.

## Completion after the authorized extension

The user authorized playing out with reasonable additional time. I selected
a 15-minute extension, appended transparently to the original allowance.
The documented pause preserved 3690.855 seconds already used; resumption
excluded only 895.372769 seconds of paused waiting/setup. Existing events and
the original overrun were retained. Clock-only changes gave resumed/subsequent
turns 120-second targets; the rules, search, and evaluation stayed frozen.

45...Rd1 was my initial candidate and the depth-5 search confirmed it at
+17.05. After 46.Bg5, I initially favored 46...Rc2+, but a 20-second request
(completed depth 4, with quiescence) found **46...Bg4**, a mate score in five
plies. This was a concrete additional assist: the bishop covers f3/e2/h3 and
coordinates the rooks, instead of chasing material with another rook check.
After 47.Bd2, a fresh search confirmed 47...Rc2, mate in three plies. Wally
chose 48.Kg2; I checked the actual escapes and played **48...Rcxd2#**.
Chess.com confirmed checkmate and **0-1**. The complete 96-ply record is saved.
The move-47 decision note's awkward "Rxc2-d2" denotes the rook on c2 capturing
the bishop on d2; the legal move, journal, and final SAN are `c2d2` / `Rcxd2#`.

Final own time was **65:51.183**, with **9:08.817** left in the extended
75-minute allowance. All 48 settled turns total the same charge. Queries
consumed **10:18.608 (15.7%)**; the other **55:32.575** includes deliberation,
commentary, commands and UI work, which the logs cannot separate precisely.
Median turn was **74.411 seconds**. The largest charge was move 45 at 208.516
seconds, combining its pre-pause charge and resumed work, with waiting excluded.
Moves 44, 1, and 28 each took about 165 seconds. See `time-audit.md` for the
per-turn evidence and limitations; the through-44 report preserves the earlier
audit cutoff.

This win as Black follows the prior v0.2 win as White, providing another
successful data point. It does not isolate a color effect or establish a rating.
The conversion still exposed inefficient deliberation and an allocator that
starved late searches. The user selected a future 90/40 + 30, +30s control;
`TIME-CONTROL-NEXT.md` records that policy for implementation before a new game.
No rules/search/evaluation improvements were introduced midgame.
