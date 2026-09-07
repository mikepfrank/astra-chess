# Game 9: Astra (Ultra) with engine v0.2 vs. Wally

Played September 7, 2026, in the embedded Chess.com browser. Astra played White
and won by **31. Qxf7#**, confirmed by Chess.com's Checkmate and 1-0 display.
The complete record is in `game.pgn`; `game.json` records every move, position,
initial candidate, chosen move and assessment. Request/result pairs preserve
the actual searches, including the rejected request on move 23.

## Method and observations

The from-scratch Python engine supplied candidate lines; Astra inspected those
lines and prospective ASCII boards and selected moves. No external chess engine,
opening book, tablebase, site hint, undo or live-game assistance from another
agent was used. Development agents worked only on clock accounting. A separate
agent audited the record after the game ended.

Experimental evaluation terms and threat extensions remained off. Candidate
position diagnostics were enabled. There were 32 completed material searches
and one completed goal probe, plus one goal request rejected before searching.
Material searches completed depths 4 through 6, with median depth 5.
The query ledger records 416.198 seconds of query wall time in total.

Concrete instances of engine help, as recorded before the moves were played:

- **12. Nxc6:** my initial candidate was c3, attacking the rook. The engine found
  the knight capture that forked Black's queen on d8 and rook on b4. Black's
  intervening attacks on my queen required further care before winning material.
- **23. dxc5:** I initially considered retreating my attacked queen to a7. The
  engine showed that the attacking knight could simply be captured by the
  d-pawn while maintaining the attack on Black's queen. A subsequent attempted
  queen-capture goal probe exceeded the turn's remaining search allowance and
  was rejected; that request provided no proof.
- **29. Rg8+:** my initial plan was Qa7. The engine found a forced-mate score
  for moving the rook to g8 with check and clearing the queen's eighth-rank path.
- **30. Qf8:** an explicit goal probe from the hypothetical position after Qf8
  established checkmate within two further plies against every legal Black
  reply. It completed 70 proof nodes, with status `forced`. Wally played dxc5;
  31. Qxf7# was then checked directly for check and absence of legal replies.

There were also judgment calls where I chose development or simpler conversion
over the engine's small numerical preferences. In particular, 27. b8=Q was
selected over first capturing another pawn: ...Rxb8 28. Rxb8+ removed Black's
last rook and simplified the finish.

This game supplies concrete evidence of useful tactical assistance. It does
not isolate the effect of speed improvements, time allocation, visualization,
or Wally's mistakes. The position was already overwhelmingly favorable before
the mating proof. One win does not establish a rating or a reliable win rate.

## Clock

The agreed allowance was 3,600 seconds for Astra's own turns, excluding Wally's
thinking. Turns started at the first observed opponent reply and settled at
the accepted move's submission timestamp once the move was verified. Exact
server-side move-completion times were unavailable; the ledger records the
observation and submission times and their uncertainties.

During move 27, context compaction and two automatic approval rejections
interrupted selection of a promotion piece. The user selected the queen and
expressly requested restoring the clock to the start of that turn. The entire
recorded turn-27 charge was therefore credited, with the original events kept:

- Start-of-move-27 balance: **1,586.099 seconds (26:26.099)**.
- Raw accumulated charge: **2,720.022 seconds (45:20.022)**.
- Authorized move-27 credit: **493.456 seconds (8:13.456)**.
- Adjusted total used: **2,226.566 seconds (37:06.566)**.
- Remaining: **1,373.434 seconds (22:53.434)**.

The credit is a single `user_time_refund` event referencing ply 52 and its
original charge. Raw timestamps, overruns, query costs and failed attempts
remain in the append-only ledger. Later turns were charged normally.

## Verification

All 61 plies, their SAN and all 62 FENs were replayed after the game using both
the project's rules and the already-installed python-chess rules library.
Both agreed with the PGN and the final checkmate result. The latter was used
only for post-game rules validation, not for play or analysis.
All 93 saved candidate/proof representative lines also replay legally with
matching SAN and FEN. An independent rules-only enumeration of the 14 legal
Black replies after 30. Qf8 confirmed that each permits immediate White mate;
the mating move varies with the defense.

Clock changes passed the complete 90-test suite. Search, rules, diagnostics and
evaluation were not modified during the game; clock-only changes implemented
the user's own-time boundary and explicit interruption credit.
The source fingerprint for rules/search/diagnostics matches all 33 query
snapshots and the final files:
`96e9ed243d69eede25b24c4c22248753053ee162b51fd0eb4cc081f47a311174`.
