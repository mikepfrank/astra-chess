# Wally (1800): visualization trial

Black won by **33...Qf1#** on September 5, 2026.
The complete record is `codex-vs-wally-2026-09-05.pgn`.

## Method

- Chose the displayed 1800 level, 300 above Wendy. Wally was available to guests.
- Played White with no timer. Evaluation, threats, suggestions, move feedback, and engine lines were off. No hints or takebacks were used.
- All playing decisions came from the assistant's own deliberation. No engine, automated search, move generator, or advice from another agent was used to select moves.
- `board_scratchpad.py` applied explicitly supplied square edits, with no chess rules or attack detection. All 33 White moves had an inspected PNG preview before play. Some previews included hypothetical replies; those are not the actual game record.
- A separate agent was asked to check the record only after Chess.com declared checkmate. That check uses chess rules, not an engine evaluation.

## What happened

- The game began with a classical Pirc setup. Central exchanges removed both pairs of knights, then the dark-squared bishops were exchanged.
- **21. Re5** and **22. Rfe1** established activity on the e-file. After the rook exchange, White began a kingside pawn advance with **25. g4** and **27. f5**.
- **29. fxg6** opened the f-file for Black's queen checks: **29...Qf2+ 30. Kh1 Qf3+**. The checking queen could also capture the bishop on d3.
- After **31. Kh2 Qxd3**, White was down a bishop for a pawn. I focused on **32. Qh6**, its threat against h7, and a hypothetical **...Qxg6 / Rg5** pin. I did not adequately check Black's rook counterattack.
- The actual finish was **32...Rf2+ 33. Kh1 Qf1#**. The rook on f2 protects the queen on f1 and covers the second rank; the queen covers the first rank. The captured bishop on d3 could no longer defend f1.

The previews helped keep the recorded board consistent, but did not prevent a tactical oversight. In particular, drawing a promising candidate line did not establish that all dangerous replies had been considered. This game does not establish a playing rating or isolate the effect of the visualization method.

## Verification after checkmate

Rules-only `chess==1.11.2` verified all 66 legal plies and exact canonical SAN. All 33 journal labels and end positions, all 66 individual ply piece positions, and the saved final board matched the PGN. The header, movetext, and derived checkmate result agreed on **0-1**. No engine evaluation was run.

Final FEN: `6k1/p6p/2b3PQ/1p1pR3/3P2P1/P7/1P3r2/5q1K w - - 4 34`.

## Artifacts

- `wally-board.json`: actual square edits and SAN move journal.
- `images/positions/wally-candidate-01.png` through `images/positions/wally-candidate-33.png`: inspected candidate positions.
- `images/positions/wally-final.png`: completed position.
- `codex-vs-wally-2026-09-05.pgn`: complete move record.
