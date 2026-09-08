# Wally (1800): rematch with opponent-threat review

Wally won by resignation after **47...Kg6** on September 6, 2026. Chess.com confirmed **0-1, Wally Won by resignation**. No promotion was played before resignation.

## Method

- Played White as a guest, with no timer, entirely through the embedded sidebar browser. No native desktop browser controls were used during this rematch.
- Evaluation bar, threat arrows, suggestion arrows, move feedback, and engine lines were off. No hints or takebacks were used.
- Move choices came from the assistant's own deliberation. No chess engine, automated move generation, search, or other agent's chess advice was used during play.
- The existing diagram-only [board_scratchpad.py](../../board_scratchpad.py) applied explicitly supplied square edits. It has no legality checks, attack detection, or evaluation.
- Each of the 47 White moves had an inspected image before execution. Extra images show the hypothetical continuation after 22.Nf5 and a rejected 45.Ra8 candidate. Only committed edits belong to the actual game.
- The added discipline was to inspect opponent checks, captures, exposed lines, and loose pieces in candidate positions before moving. This remained a manual review, and was imperfect.

## What happened

- The Pirc opening diverged from the first Wally game at **6...a6**. White developed, closed the center with **11.d5**, and exchanged the kingside bishops with **14.Bxh6 Bxh6 15.Qxh6**. Black recovered a pawn with **15...Nxc2**.
- **22.Nf5 gxf5 23.Qxf6** exchanged the remaining knights. Following **24.f4 Rxe4 25.Bxe4 fxe4 26.Qxd4**, White had two rooks against a rook and bishop, with equal pawn counts.
- Queens came off through **29...Qd4 30.Qxd4 Rxd4**. White then used both rooks to remove the advanced e-pawn and exchanged rooks. After **35...Bxe4**, the material was rook versus bishop, with four pawns each.
- White's king advanced on the kingside, while Black's connected queenside pawns advanced. The rook maneuvers did not adequately contain that pawn group.
- The preview of **45.Ra8** exposed that a8 was on the bishop's e4-d5-c6-b7-a8 diagonal. That candidate was rejected before any browser move, and **45.Ra7** was played instead.
- The late defensive plan still failed: **45...d2 46.Rd7 Bd3** placed the bishop between the rook and the promotion square. I recognized the block but mistakenly treated the pawn as still contained while considering a king approach. The immediate promotion threat was the missed consequence.
- **47.Rh7+ Kg6** did not resolve the problem. White resigned. There was no takeback and no additional game was started.

These are descriptions of the moves and the observed failure, not engine assessments of the best alternatives or the exact first losing move. The experiment supports a narrower lesson: a visual preview can catch a concrete geometry error, but it does not guarantee sound evaluation of the resulting position. Promotion threats and defensive interpositions need explicit review too.

## Record and verification

The Chess.com move list showed 47 complete move pairs, ending in `47. Rh7+ Kg6`. The PGN records resignation with result `0-1`; the standard `Termination "normal"` category includes resignation.

Rules-only python-chess 1.11.2 validation passed after resignation: all 94 plies are legal and use canonical SAN; all 47 journal entries, all 96 explicit edits (including castling rook edits), every intermediate position, and the final board match. The report is [wally-rematch-validation.json](wally-rematch-validation.json). No engine analysis was used.

Final FEN: `8/7R/6k1/1p3p2/2p2P1P/3b3K/1P1p2P1/8 w - - 4 48`.

## Artifacts

- [codex-vs-wally-rematch-2026-09-06.pgn](codex-vs-wally-rematch-2026-09-06.pgn): complete game record.
- [wally-rematch-board.json](wally-rematch-board.json): committed square edits and exact SAN journal.
- [wally-rematch-candidate-01.png](../../images/positions/wally-rematch-candidate-01.png) through [wally-rematch-candidate-47.png](../../images/positions/wally-rematch-candidate-47.png): candidate diagrams; number 45 is the rejected a8 candidate.
- [wally-rematch-candidate-45b.png](../../images/positions/wally-rematch-candidate-45b.png): inspected a7 candidate that was actually played.
- [wally-rematch-candidate-22-line.png](../../images/positions/wally-rematch-candidate-22-line.png): hypothetical capture continuation, not an extra part of the game.
- [wally-rematch-final.png](../../images/positions/wally-rematch-final.png): board at resignation.
