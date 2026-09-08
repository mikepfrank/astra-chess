# Game 10: Wally versus Astra, Black trial

User authorized a new Wally (1800) game and selected Black in the embedded
Chess.com browser. Astra (Ultra) plays Black with the same v0.2 rules/search/
evaluation as game 9. No external engines, books, databases, hints or takebacks.
Other agents assisted only with color-aware journal development, not moves.

Pre-game machinery commit: `2f1b49c`. Five Black tests plus 33 clock/recovery
regressions passed. Engine sources unchanged; expected search fingerprint:
`96e9ed243d69eede25b24c4c22248753053ee162b51fd0eb4cc081f47a311174`.

Default queries: 15 seconds, depth ceiling 8, three candidates, diagnostics on;
optional evaluation terms and threat extensions off unless explicitly recorded.
Positive query scores favor Black. One hour cumulative own-turn time excludes
Wally's thinking and ends at accepted submissions. No refunds authorized for
this game. Setup/development occurred before Play and before the own clock.

This is a repeat trial with a changed color, not a controlled same-color repeat.
Archive/export score code currently assumes White and must be adapted before
generating this game's scored replay. Preserve queries and journal meanwhile.

## Evidence from play so far

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
  expired before checkmate, so this is an unfinished favorable position, not
  another recorded win. See continuation.md for the pause and exact boundary.
- The reserve allocator progressively curtailed searches, eventually rejecting
  move 42 despite several total minutes remaining. Its minimum 12 remaining
  turns and fixed 40-second reserve need reconsideration after this trial.
- UI entry initially required API troubleshooting; all own-turn retries were
  charged. Later entries used observed DOM locators in the embedded browser.
- Invalid helper commands for a mistyped Python path and wrong rear-rook
  source square were rejected; no illegal browser move was submitted, and
  original observation times were retained. No time refund was applied.
