# Game 10 replay archive

The requested standalone page is `replays/wally-engine-v02-black-replay.html`. It
embeds all 96 legal plies and 97 positions, matching the verified journal and
PGN. Astra (Ultra) plays Black, Wally (1800) plays White, and the ending is
48...Rcxd2#, 0-1. The date follows the recorded PGN: September 8, 2026.

The default board orientation places Astra at the bottom. Flipping the board
changes orientation and player-row placement, while preserving White/Black
move columns, ratings, result, and the original PGN download.

The historical export contains 48 verified Black choices: 42 numeric search
estimates, two mate forecasts, three explicit missing values (moves 42-44),
and actual checkmate on move 48. Black-root scores retain their sign and are
labeled **Positive favors Black**. White-move frames remain unscored. No
new engine search was run. After 46...Bg4 and 47...Rc2, labels count Black's
remaining moves from the displayed board: **Mate in 2**, then **Mate in 1**.
Original search roots counted five and three plies including those moves.

Validation:

- All 139 Python tests passed, including color/parity, position, identity,
  missing-value, positive/negative mate perspective, and legacy White checks.
- Existing White and new Black offline browser checks passed. The Black test
  covers initial orientation, player labels/ratings, flip, both castlings,
  captures, keyboard/slider/playback, mate frames, PGN contents, and 390px layout.
- The replay made no external runtime requests. Desktop/mobile screenshots
  are saved in `engine-output/wally-v02-black-evaluation/`.
- The embedded sidebar was inspected at the opening, an ordinary scored Black
  move, the mate forecast, and the final checkmate.
- Rebuilding the HTML and extracting the JSON reproduced both files exactly.
- The archive skill's installed and repository copies match and both passed
  Codex's official validator.

The collection index now has eight games and preserves its seven existing
deployment links. Its new link uses the **proposed**, not published here,
Netlify project `astra-vs-wally-engine-v02-black`. Upload a copy of the replay
named `index.html` as that project's root page; separately redeploy the
collection `replays/index.html` to `astra-plays-chess`. Build/preview commands are in
`README.md`. No Netlify deployment or new game was performed.
