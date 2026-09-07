# Wally engine-assisted trial — 7 September 2026

Wally (1800) won by resignation after **40...Re1**. The embedded Chess.com tab confirmed “Wally Won” and “by resignation” at 17:32:14 UTC. Astra played White. No moves from the local journal were entered after Black's fortieth move.

The complete game is in `astra-vs-wally-engine-2026-09-07.pgn`. `game.json` preserves the actual SAN, UCI, and FEN sequence, initial candidate choices, decisions, observations, and query references. Each query result includes its candidate lines and board positions. `audit.md` records the mechanical verification and timing statistics.

## Method actually used

- Only the embedded Chess.com browser was controlled. No site hints, undo, game review, external engine, opening book, or endgame database assisted play. The site's post-game analysis began automatically after resignation.
- The unchanged, local Astra Search Lab engine supplied bounded alpha-beta analyses. Most calls requested 3–4 seconds and depth 5. Additional calls sometimes restricted White's candidate moves while preserving all legal Black defenses. No goal-probe calls were used in this game.
- Before the first query of each White turn, an initial candidate and concern were recorded. Subsequent candidate boards were printed as ASCII and inspected. No additional future-position PNGs were generated during this game.
- The first opening comparison was not independent: the earlier engine demonstration was already familiar. Later initial choices were also naturally influenced by prior engine advice. This is a qualitative collaboration trial, not a controlled measurement of unaided versus assisted skill.
- No other agents advised on play. An independent agent audited the saved journal only after resignation.

## Concrete observations

1. **Move 9: a useful defensive correction.** The first candidate was h3. The targeted result showed `h3 Bxf3 Qxf3 Nxd4`, losing a pawn. A subsequent comparison supported `d5`, which was played. This was a concrete tactical objection, beyond a small positional score difference.
2. **Moves 20–22: a serious shared failure.** The engine displayed the coming `...c5–c4` idea without recognizing the full consequence soon enough. The bishop on d3 had no adequate retreat: the White knight occupied e2, and the c2 pawn blocked its other rear diagonal. After 21...c4, the next searches finally showed the piece loss. White played 22.Ra7 cxd3 23.Rxd3 and was down a bishop for a pawn. I also missed the missing retreat squares while reviewing the earlier line. The exact earliest losing move has not been established by a deeper post-game analysis.
3. **Move 25: useful damage limitation.** A targeted comparison rejected the initial Ng3 plan because the displayed rook exchanges and `...Qxb3` made the deficit worse. Rxd8 was played instead.
4. **Move 36: an engine-found opportunity.** My initial candidate was b5. The engine proposed Qc2 (or Qe2), attacking the rook on d1 and bishop on d2. White played 36.Qc2 Rf1 37.Qxd2, recovering the bishop. Black then took e4 with tempo. The engine's briefly positive score did not establish a lasting advantage.
5. **Move 39: confirmation of an independently noticed trap.** Before the query, I noted that accepting `...Rh1+` with Kxh1 allowed `...Nxf2+`, forking the king and queen. The engine confirmed that line and selected Kg2. This was confirmation, not a threat first discovered by the engine.
6. **Moves 39–41: another search-horizon limitation.** The assessment worsened from about -0.94 at White's move 39, to -4.56 at move 40, to approximately -11 after 40...Re1 as the attack came within view. At the final position, `41.Nf4 Ng5#` was explicitly found. The engine's best displayed alternative, `41.Qe2 Qg4+ 42.Kg2 Rxe2`, lost the queen. White resigned instead of submitting a forty-first move.

Scores above are this experimental engine's own pawn-unit evaluations, not independently calibrated assessments or Chess.com evaluations. An engine suggestion replacing an initial candidate is not by itself evidence that the replacement improved the position.

## Timing and evidence limitations

The intended limit was 60 seconds per turn, including a maximum 12 seconds of engine work. Actual click-submission timing exceeded a minute on several turns. Some overruns came from additional deliberation or queries; some browser operations took 20–30 seconds. Setup, the initial automatic approval-review rejection, and the first-move verification caused particularly large first-turn overhead. These costs must not be hidden by reporting engine time alone.

Move 17's clock began with a confirmation read at 17:05:11.958 UTC, although `...b5` was already visible in the preceding tool result at approximately 17:04:55 UTC. Thus its recorded observation-to-submission duration omits roughly 17 seconds. Other observation timestamps were taken after the browser accessibility read, not necessarily at the instant the bot made its move. Resignation confirmation had further UI latency and is separate from the 40 submitted moves.

One malformed query on move 9 (`root_moves: c?`) failed before searching and was corrected. It consumed time but produced no result; the corrected request reused that query's filename. The journal therefore counts successful searches, not every command attempted.

## What this suggests for a next version

The engine was useful for concrete candidate comparison and did find a material-recovery opportunity. It was not reliable enough to prevent the decisive mistakes in this game. This single loss does not measure whether win probability improved.

The most relevant next changes would be to make threat handling at the search boundary less optimistic, include simple piece mobility and king-exposure terms, and make deeper searches affordable. A capture-only continuation can treat a position as quiet even when a piece is trapped or a non-capturing move creates a mating threat. Extending such positions needs careful testing because adding many quiet moves can make search much slower.

Improved move ordering and lower-cost candidate ranking, followed if needed by a faster implementation, could increase completed depth within the same total turn budget. Simply raising a requested depth does not help when the time limit is reached first. The saved bishop-trap and final-attack positions are useful regression examples. These are proposals; the engine was not modified during or after this game.
