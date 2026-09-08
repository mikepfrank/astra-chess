# Wendy (1500): visualization trial

White won by **36. Rg6#** on September 5, 2026.
The complete record is [codex-vs-wendy-2026-09-05.pgn](codex-vs-wendy-2026-09-05.pgn).

## Method

- Chose the displayed 1500 level, 200 above Nelson. Antonio at 1500 was locked; Wendy at 1500 was available to guests.
- Played White with no timer. Evaluation bar, threat arrows, suggestions, move feedback, and engine lines were off. No hints or takebacks were used.
- All moves were selected through the assistant's own deliberation. No engine, automated search, move generator, or advice from another agent was used for move selection.
- [board_scratchpad.py](../../board_scratchpad.py) applied only explicitly supplied square edits. Each of the 36 White moves was previewed as a PNG and inspected before play. The helper has no knowledge of chess legality or attacks.
- A helper agent wrote only [export_game_journal.py](../../export_game_journal.py), which copies the manually recorded SAN labels into a PGN file. It supplied no chess advice and did not operate the browser.

## Notable moments

- **8. d4** used the pin on Black's e5 pawn to challenge the center and bishop.
- **12. Rxe6** captured the bishop left undefended after Black castled.
- **24. Nf7+** forked the king and rook, winning the exchange.
- A candidate finish after **31...Kh5** was explicitly drawn in [wendy-line-31.png](../../images/positions/wendy-line-31.png). Wendy chose **31...Kh7**, so that hypothetical line was discarded.
- Before **33. Ne4**, [wendy-mating-net.png](../../images/positions/wendy-mating-net.png) showed the intended finish: **33...h5 34. Nxf6+ Kh6 35. Bd3**, followed by **Rg6#**. Its hypothetical intervening pawn move was ...c4; Wendy actually played ...a5, which did not affect the mate.
- At checkmate, the bishop on d3 protects the rook on g6, and the knight on f6 covers h5 and h7. Before the final move, Black still had legal pawn moves, avoiding stalemate.

## Verification after checkmate

Only after the game ended, `chess==1.11.2` was used to verify all 71 legal plies, exact canonical SAN, agreement with all 36 recorded diagram states, and the final 1-0 checkmate. No engine evaluation was run.

Final FEN: `8/8/5NRk/p1p4p/8/2PB4/P4PPP/6K1 b - - 1 36`.

Files: [wendy-board.json](wendy-board.json) contains the actual move journal; [wendy-candidate-01.png](../../images/positions/wendy-candidate-01.png) through [wendy-candidate-36.png](../../images/positions/wendy-candidate-36.png) contain the inspected candidate boards; [wendy-final.png](../../images/positions/wendy-final.png) shows the completed position.
