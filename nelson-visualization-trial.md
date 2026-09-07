# Nelson rematch: visualization trial

Result: White won with **45.Rh8#** against Nelson (displayed rating 1300).
Game record: `codex-vs-nelson-rematch-2026-09-05.pgn`.

## Method

- The user reported selecting Ultra for this rematch.
- Move choices and threat checks were made through the assistant's own deliberation, without an engine, automated search, move generator, or hint.
- A helper agent built only the diagram renderer. It provided no chess advice.
- `board_scratchpad.py` applies explicitly supplied square edits to a copied position and draws letter pieces. It does not know chess rules or identify attacks.
- Move 1 was previewed as a manually written text board. Moves 2 through 45 were previewed and inspected as PNG diagrams before being played. Additional candidate and continuation diagrams were drawn where useful.
- Actual moves were read from the Chess.com interface and recorded separately from hypothetical edits. Previewing did not change the game or the recorded current position.

## Concrete observation

Before move 13, the assistant considered **Nxg6**, mistakenly treating the f7 pawn as pinned to the king. Inspecting `candidate-13.png` made the error apparent: the bishop on c4 points through d5, e6, and f7 toward g8; Black's king was on e8. Thus **13...fxg6** would capture the knight. The candidate was rejected and **13.Nf3** was played, with `candidate-13-safe.png` showing the selected position.

The finish was also drawn before it was played:

`42.Kf6 Kg8 43.Re8+ Kh7 44.Ne6 Kh6 45.Rh8#`

The outcome is encouraging, and the rejected move is a specific example of an error caught during visual inspection. One game does not isolate the effects of the thinking setting, visualization, the more deliberate checking routine, or Nelson's different moves.

## Verification after the game

A chess rules library was used only after checkmate to verify all 89 plies, the final 1-0 checkmate result, and agreement between the 45 recorded diagram snapshots and the legal game positions. It also confirmed that the rejected `13.Nxg6 fxg6` continuation is legal. No engine evaluation was run.

## Diagram files

- `nelson-rematch-board.json`: final position and actual move journal.
- `candidate-02.png` through `candidate-45.png`: candidate positions; `candidate-13.png` is the rejected candidate, with the actual move in `candidate-13-safe.png`.
- `candidate-finish.png`: the explicitly supplied final continuation.
- `board-current.png`: completed game position.

The current JSON records the completed game. To experiment with another game, initialize a separate state file with the renderer's `--state` option.
