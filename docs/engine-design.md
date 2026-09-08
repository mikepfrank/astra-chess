# Astra Search Lab: evaluation, search, and goal queries

This reference describes the implemented Python engine, version 0.2, reviewed
against its source on September 8, 2026. It explains what contributes to a score,
what a goal result establishes, and which features cost extra search time.
[ENGINE.md](../ENGINE.md) remains the command/workflow guide;
[ENGINE-CHANGES.md](../ENGINE-CHANGES.md) contains the historical measurements.

The engine uses its own chess rules, move generation, hand-written evaluation,
and search. It has no opening book, endgame database, external engine, network
analysis, learned weights, or imported piece-square tables. Core operation needs
only Python's standard library. Recorded games are examples and test inputs;
search does not consult them for move advice.

## Contents

- [Scores and the complete default evaluation](#scores-and-the-complete-default-evaluation)
- [Optional evaluation terms](#optional-evaluation-terms)
- [Core candidate-search algorithm](#core-candidate-search-algorithm)
- [Goal-oriented queries](#goal-oriented-queries)
- [Optional diagnostics and threat extensions](#optional-diagnostics-and-threat-extensions)
- [Request fields and defaults](#request-fields-and-defaults)
- [Examples and interpreting results](#examples-and-interpreting-results)
- [Other facilities and limitations](#other-facilities-and-limitations)
- [Source map](#source-map)

## Scores and the complete default evaluation

Ordinary scores are in **centipawns (cp)**: 100 cp is one nominal pawn. Positive
analysis scores favor the player to move at the **query's starting position**,
including when that player is Black. A displayed continuation does not change
this perspective. These are heuristic search estimates, not win probabilities,
ratings, or an independently established value of the position.

The static `evaluate(position)` function scores the current board from its
side-to-move perspective. Negamax changes the sign at each ply to make its
returned candidate scores consistent with the query root. An analysis result
usually evaluates a searched continuation, not just the immediate board after
the candidate move.

### Coordinates and phase

For each square, `f` and `r` are zero-based file/rank coordinates: a1 is `(0,0)`.
The following quantities are calculated from geometry and current material:

| Symbol | Definition |
| --- | --- |
| `C` | Centralization: `7 - abs(f - 3.5) - abs(r - 3.5)`. It is 0 in a corner and 6 on d4/e4/d5/e5. |
| `A` | Advancement from the piece owner's back rank: `r` for White, `7 - r` for Black. |
| `P` | Pawn advancement beyond its starting rank: `max(0, A - 1)`. |
| `NPM` | Combined material value of both sides' knights, bishops, rooks and queens; excludes pawns and kings. |
| `E` | Endgame weight: `clamp((4400 - NPM) / 4400, 0, 1)`. Zero favors middlegame king placement; one favors endgame placement. |

`E` is not based on move number. It remains zero while `NPM >= 4400`, then
increases as pieces leave the board. The engine has no separate opening phase.

### Material

| Piece | Base value (cp) |
| --- | ---: |
| Pawn | 100 |
| Knight | 320 |
| Bishop | 335 |
| Rook | 500 |
| Queen | 900 |
| King | 0 in static material accounting |

The king's zero material value does not make it expendable: legal move generation
forbids leaving it in check, and search handles checkmate separately.

### Positional adjustments

The following adjustments are added to each piece owner's material value.
White's totals are added and Black's subtracted before choosing the final
side-to-move sign.

| Factor | Exact adjustment and condition |
| --- | --- |
| Pawn advancement and center | `+5*P + 2*C` per pawn. |
| Doubled/multiple pawns | `-11` for **each** pawn on a file containing more than one friendly pawn. Two pawns incur -22 total; three incur -33. |
| Isolated pawn | `-9` if neither adjacent file contains any friendly pawn, regardless of those pawns' ranks. |
| Passed pawn | `+(5 + 4*E)*P²` if no enemy pawn lies ahead on its file or either adjacent file. Enemy pawns behind it do not disqualify it. |
| Blocked passed pawn | Additional `-(12 + 4*A)` if the square immediately ahead of a passed pawn is occupied by **any** piece. This is not a general blocked-pawn penalty. |
| Knight center | `+11*C - 25`. |
| Knight on back rank | Additional `-8` when `A == 0`. |
| Bishop center | `+5*C - 10`. |
| Bishop on back rank | Additional `-6` when `A == 0`. |
| Rook file | If there is no friendly pawn on the file: `+13` if an enemy pawn remains there, otherwise `+22`. These are alternatives, not cumulative bonuses. |
| Rook on seventh rank | `+18` when `A == 6`: White's seventh rank or Black's second rank. |
| Queen center | `+2*C`. |
| King placement | `E*(13*C) + (1-E)*(13*S - 8*C + H)`, with `S` and `H` defined below. |

For the king, `S` counts friendly pawns one rank directly ahead of it, on its
file and neighboring files (at most three). `H` is 24 when the king is on its
own back rank on the c- or g-file, otherwise zero. This rewards a
castled-looking location; it does **not** check whether castling actually occurred.
The shield and that location bonus fade out with the middlegame weight `1-E`.

Two further adjustments apply to the board as a whole:

- **Bishop pair:** +28 for a side with at least two bishops, once per side.
  It counts bishops, without checking that they occupy opposite square colors.
- **King approach in sparse endings:** after the other base terms, if `E > .75`
  and the absolute White-minus-Black score exceeds 200, add `3*(7-D)` toward the
  side already ahead. `D` is the kings' Chebyshev distance, the larger of their
  file/rank separations. This encourages bringing the winning king closer.

The base result is rounded with Python's `round()` and returned as an integer.
There is no explicit default term for general mobility, a trapped piece,
attacked/undefended material, a pin, a fork, a development count, tempo, or an
attacking initiative. Such effects must emerge through the terms above or
through search. The optional terms below address only some of these gaps.

### Checkmate and draws

Terminal results override static evaluation. Checkmate is represented internally
by `30000 - distance_in_plies` for a winning root, with the corresponding negative
score for a losing root. This favors faster wins and delays unavoidable mate.
Values with absolute magnitude at least 29000 receive a signed `mate_in_plies`
field; they should not be read as a large pawn advantage. The distance starts at
the query root and counts individual players' moves, not move pairs.

Terminal draws score zero. Current threefold/50-move draw claims, and valid claims
by declaring an intended move, are **optional choices**, also valued at zero.
The engine can prefer continuing a winning position. Fivefold repetition and
75-move draws are automatic under its implemented rules; checkmate takes
precedence. An intended-move claim ends play before the declared move is made,
so that move is recorded separately from the played line.

Repetition identity includes the board, turn, castling rights and en-passant
availability only when an en-passant capture is legal. Earlier repetitions
require supplied history. Insufficient-material recognition covers bare kings,
one minor against a bare king, and bishop-only positions with all bishops on
one square color. It deliberately does not declare two knights automatically
dead or solve every unusual blocked dead position.

## Optional evaluation terms

These are independent Boolean flags under `evaluation`, available only in
`analyze` mode. **All are off by default**, including in the live-game helper.
They add to static evaluation at quiet search frontiers; they are not required
for the separate diagnostic report or for goal probes.

| Flag | Exact additional score |
| --- | --- |
| `mobility` | For each knight/bishop, `3*(min(M,8)-4)`, where `M` is its count of geometric destinations outside enemy pawn control. Range: -12 to +12 cp per minor piece. |
| `restricted_piece` | For each knight/bishop with a credible capture threat: -48 cp if `M == 0`, or -28 cp if `M == 1`. No penalty otherwise. This is a **per-piece** cap, not a cap on the whole position. |
| `king_exposure` | For each king, -12 per enemy rook/queen access line on the king's file, or -6 on an adjacent file, capped at -36 cp per king. Only qualifying file access, defined below, is counted. |

`M` respects occupied squares and sliding-piece blockers and includes geometric
captures, but excludes squares controlled by enemy pawns. It does **not** test
king pins or other enemy attacks, so a counted destination is not necessarily a
safe legal escape. The counter stops at eight when scoring mobility, or at two
when only deciding whether a piece is restricted.

A capture threat is called **credible** if a legal enemy capture exists and
either the attacker costs no more than the victim, or its destination after
capture is not geometrically attacked by the victim's side. This is a cheap
plausibility check, not an exchange-sequence calculation. Its separate comparison
values are pawn 100, knight 320, **bishop 330**, rook 500, queen 900, king 20000;
the bishop value differs from the main evaluator's 335. These are the implemented
constants, not new tunings introduced by this documentation.

Qualifying **file access** means a file on or beside the king with no friendly
pawn anywhere on it, an enemy rook/queen on that file, and a clear vertical path
to the king's rank. An entry square occupied by another enemy piece blocks the
access. A file alone, without enemy heavy-piece access, adds no penalty. This
term does not count diagonal attacks, general attacking-square coverage, or
duplicate the base pawn-shield formula.
Unlike the direct capture-threat check, file access is geometric: it does not
test whether the rook/queen is pinned or can legally use the line.

The base evaluator rounds first; these integer extras are then added with the
correct side-to-move sign. Calling `evaluate()` directly returns only the base
score. `extra_evaluate()` itself returns a White-relative adjustment; `analyze()`
performs the conversion when options are enabled.

## Core candidate-search algorithm

`analyze()` combines **iterative deepening, negamax alpha-beta search, and
quiescence**:

1. Generate legal root moves, optionally restricted by `root_moves`.
2. Search base depths 1, 2, 3, and so on, up to the requested ceiling or deadline.
3. At ordinary interior nodes, alternate the score's sign and assume the
   opponent chooses its best response. Alpha-beta cutoffs skip branches that
   cannot change the relevant result.
4. At the nominal depth boundary, use quiescence to examine captures and
   promotions before accepting a static score. Checked positions generate all
   legal evasions, including quiet moves; there is no stand-pat evaluation while
   in check. An optional restricted-piece extension can also include quiet moves.
5. Finish examining every permitted root move before accepting an iteration's
   top candidate set. A partial deeper iteration never replaces the last fully
   completed set.

The requested depth counts **plies**: depth 6 is six individual moves. It is a
ceiling, not an assurance that depth 6 will finish. Quiescence normally stops at
eight quiescence plies at a quiet frontier. Compulsory check evasions and enabled
threat extensions can carry a line beyond that limit. A checked quiescence node
at total root-relative ply 96 or later aborts the current iteration with
`check_extension_limit`; it does not substitute a static score while checked.

The root keeps the best `candidates` moves. Once that set is full, its weakest
score becomes a threshold for later root searches. A root that cannot beat the
threshold may be rejected using a bound; rejected bounds are never presented
as exact candidate scores. Returned completed scores are exact **for this bounded
search and its frontier rules**, not for chess as a whole. Requesting more
candidates generally costs more search.

If even depth 1 cannot finish, the result explicitly reports `fallback: true`,
depth zero, and an unevaluated legal move with `score_cp: null`. A missing score
must not be interpreted as equality. The previous iteration remains available
if a later iteration times out.

### Move ordering and speed features

Move ordering changes how quickly pruning works, without granting a positional
bonus to the final evaluation. Priorities include a previously preferred move,
captures (favoring valuable victims and cheaper attackers), promotions, quiet
cutoff moves called *killers*, and history scores for quiet moves that caused
cutoffs. Castling and central destinations receive small ordering preferences;
UCI text breaks ordering ties. Previous leading root moves are searched first
on the next iteration.

The engine reuses preferred **moves**, not evaluation scores, across repeated
position identities. It has no score/bound transposition table; this avoids
reusing a value under a different repetition or move-count history. Other speed
work includes precomputed board geometry, direct tactical move generation for
quiescence, early existence checks for legal moves, and reusing child positions
already generated during legality checking.

There is no null-move pruning, late-move reduction, opening-book shortcut,
tablebase lookup, neural evaluation, or parallel search. Quiet moves are omitted
from ordinary non-check quiescence, except for enabled threat extensions and
the special handling of intended-move draw claims. That omission is a central
source of horizon errors, including quiet threats and zugzwang.

## Goal-oriented queries

`probe` is a separate Boolean goal search. It is **not** an `analyze` request with
unhelpful opponent replies filtered out. The interface rejects a `goal` in
analysis mode and rejects `root_moves` in probe mode. To study a specific move's
consequences, place it in `after` and probe the resulting position.

Each request has one atomic goal:

```json
{"type": "capture", "side": "white", "target": "e4"}
```

Only `type`, `side`, and `target` fields are allowed. `side` accepts `"white"` or
`"black"` and defaults to the player to move at the effective search root, after
any `after` moves. `target` is mandatory for the two capture goals and forbidden for
all other types. It must initially hold a non-king piece of the appropriate side.

| Goal type | Success condition |
| --- | --- |
| `capture` | The goal side captures the enemy piece initially on `target`. |
| `avoid_capture` | The goal side's piece initially on `target` survives every position through the horizon or game end. |
| `castle` | The goal side completes a new legal castling move, on either wing. It does not count castling that preceded the query. |
| `check` | The opponent's king is in check at some position within the horizon. |
| `avoid_check` | The goal side's king is never in check through the horizon or game end. |
| `checkmate` | The goal side checkmates the opponent within the horizon. |
| `avoid_checkmate` | The goal side is not checkmated through the horizon or game end. |
| `stalemate` | The opponent is stalemated within the horizon. |
| `avoid_stalemate` | Neither side is stalemated through the horizon or game end. |

Capture goals track the **original piece's identity**, not continued occupation
of a fixed square. Moving it, promoting it, moving its rook during castling, or
capturing it en passant is accounted for. A replacement piece arriving on its
old square does not become the target.

Achievement goals can finish early; an initial check/mate/stalemate can already
satisfy the applicable goal. Avoidance checks every visited position and searches
the full requested horizon, unless the game ends first. A different terminal
event can satisfy an avoidance goal: avoiding stalemate alone, for example,
does not exclude being checkmated. Nor does capturing a queen prove the resulting
exchange or position is favorable.

### Forced strategies and cooperative examples

The adversarial proof search is an AND/OR search: on the goal side's turn, one
successful choice suffices; on the opponent's turn, **every legal defense** must
succeed for the goal to be forced. It includes optional draw-claim choices and
does not prune quiet moves by material score.

The separate witness search asks whether *some* qualifying path exists, allowing
cooperation by both sides. Achievement searches try horizons 1 through `depth`;
avoidance searches use the full horizon directly, since a shorter safety result
would not answer the question. The proof stops at the first successful achievement
horizon; witness collection is limited by the requested count and budget.

| Overall `status` | What was established |
| --- | --- |
| `forced` | A goal-side strategy survives every legal opponent choice within the stated horizon. |
| `possible` | A cooperative example exists **and** a completed proof search refutes a forcing strategy within the horizon. |
| `unreachable` | Exhaustive cooperative search found no qualifying line within the horizon. |
| `unknown` | The searches did not establish the complete classification. Inspect the component statuses; this does not mean no line exists. |

Read `proof_status` (`forced`, `refuted`, `unknown`) and `witness_status`
(`found`, `absent`, `unknown`, `not_searched`) alongside the overall verdict.
`proof_only: true` skips cooperative search and dedicates the search allowance
to proof/refutation. A completed refutation can therefore give overall
`unknown` with `proof_status: "refuted"` and `witness_status: "not_searched"`,
even without a timeout. A successful proof supplies a representative line, so
its witness status can be `found` even in proof-only mode.

Returned lines carry `evidence: "proof_representative"` or
`"cooperative_witness"`. A representative is just one path through a proved
strategy, not the whole branching strategy. A separately listed cooperative line
can start with a move that does not force the goal, even when the overall query
is `forced`. Re-query after the opponent's actual reply instead of blindly
following the displayed path. Lines are not ranked by material quality, and a
refuted proof does not currently export a complete refutation tree.

There is no built-in compound-goal language, piece-trap goal, score-threshold
filter, required capture-piece-type filter, or restriction to one castling wing.
Use separate focused probes and analyze the resulting boards. Every proof is
conditional on the supplied position/history and finite horizon.

## Optional diagnostics and threat extensions

### Diagnostics: inspect without adding evaluation terms

`diagnostics: true` works with either query mode. It examines the starting board
and the boards along returned lines **after** search. It does not add evaluation
weights or alter the search algorithm, although reserving time for inspection
can reduce the achieved depth.

For the query root player's knights and bishops, it reports friendly blockers,
geometric destinations, destinations outside enemy pawn control, direct legal
capture threats, and legal non-capturing enemy pawn pushes that would attack the
piece. Pawn promotions are excluded from that pawn-push hint. Restricted mobility
means at most one destination outside enemy pawn control.

For that player's king, it reports aligned enemy sliding pieces with clear lines
or a single friendly screen, heavy-piece access on nearby files, and lines newly
present relative to the preceding displayed board. A single-screen line is
information about exposure; it is not a proof that moving the screen loses.

The inspected side remains the **query root player** throughout the line, even
when the turn changes or `goal.side` names the other player. If the enemy is not
actually to move, capture and pawn-push hints use an explicitly labeled hypothesis
that the enemy could move next on the unchanged board. En-passant rights are
cleared when constructing that changed-turn hypothesis.

Results are cached by `(FEN, preceding FEN)`. `diagnostic_coverage` reports the
number inspected/skipped, completion, and elapsed cost; a skipped inspection is
null. Deadlines are checked between inspections, not in the middle of each
`diagnose()` call. No warning, and even complete diagnostic coverage, is not a
proof of safety. These hints are distinct from the numeric options and proof
searches described above.

### Threat extensions: retain quiet defenses at a flagged frontier

`threat_extensions` is an integer 0, 1 or 2, only for `analyze`, and defaults to
zero. At a non-check quiescence frontier, it tests whether the side to move has
a knight or bishop with at most one pawn-safe geometric destination and a
credible enemy capture. When the condition holds and the branch has allowance
left, search includes **all legal moves** for one more ply without stand-pat.
This includes moving a blocker, taking the attacker, or making a countercheck.

The allowance is consumed per branch, not renewed at each threatened position.
It is independent of the three optional evaluation flags. Every legal check
evasion remains part of search regardless of this option. Merely anticipating a
future pawn push is not the trigger; the restricted piece must already face the
qualifying capture threat at the inspected frontier.

`extended_frontiers`, `capped_threat_frontiers` and
`threat_frontier_unresolved` disclose the work and remaining uncertainty. These
counts include work in attempted iterations, and zero flagged threats does not
establish that all threats were recognized. Extra branching and extra evaluation
can reduce the completed base depth; optional features are not automatically an
improvement in a fixed time budget. The measured bishop-trap example and timing
tradeoffs are in [ENGINE-CHANGES.md](../ENGINE-CHANGES.md).
At the extension cap, search resumes ordinary quiescence/static evaluation; it
does not abort the iteration or prove that the piece can be saved. The unresolved
flag is true when extensions are enabled and a frontier was capped or search
stopped for its time limit.

## Request fields and defaults

These are the public JSON request defaults for `astra_chess.py query`.
Unknown fields and invalid mode/option combinations are rejected.

| Field | Default | Accepted meaning |
| --- | --- | --- |
| `label` | Mode-specific label | Descriptive text only; not a natural-language search instruction. |
| `mode` | `"analyze"` | `"analyze"` or `"probe"`. |
| `fen` | `"startpos"` | Standard start or a validated six-field FEN. |
| `after` | `[]` | Legal UCI moves applied before search; they do not consume the requested search depth. |
| `history_fens` | `[]` | Preceding positions in order, excluding the supplied starting FEN. Used for repetition. |
| `depth` | 5 for analyze; 4 for probe | Integer 1–32, measured in plies from the effective root. |
| `seconds` | 3.0 | Finite positive number up to 180; an attached clock may reduce the allowance. |
| `candidates` | 3 | Integer 1–10: top root candidates for analyze, maximum returned evidence lines for probe. |
| `root_moves` | All legal root moves | Nonempty, duplicate-free list of legal UCI moves; analyze only. Other plies' defenses remain unrestricted. |
| `goal` | None | Required for probe and forbidden for analyze; fields described above. |
| `diagnostics` | `false` | Post-search inspection for either mode. |
| `evaluation` | All flags `false` | Optional `mobility`, `restricted_piece`, `king_exposure` Boolean flags; analyze only. |
| `threat_extensions` | 0 | Up to two extra full-width threat plies per branch; analyze only. |
| `proof_only` | `false` | Skip cooperative witness search; probe only. |

The effective root is the supplied FEN **after** replaying `after`. The intervening
positions are appended to the supplied history automatically. Thus `root_moves`,
goal targets, default goal side and returned score perspective all refer to that
effective root. FEN validation checks structural consistency, king safety,
castling rights and en-passant plausibility; it does not prove that a position
or supplied history arose in a real game.

Direct Python APIs accept `multipv`/`max_lines` up to 20, whereas JSON requests
limit `candidates` to 10. Direct `probe()` defaults to two seconds; the JSON
interface defaults to three. Python `history` takes preceding repetition keys,
not FEN strings; the JSON interface handles that conversion.

The live helper `play_engine_game.py query` deliberately has different defaults:
depth 8, 15 seconds, three candidates, diagnostics on, and proof-only on when
`--goal` is supplied. `--no-diagnostics` and `--witness` turn off those defaults.
Optional evaluation terms and threat extensions remain off. These requests are
also bounded by the shared game clock.

### How the time limit is divided

With diagnostics enabled, the interface reserves `min(0.5 seconds, 10% of the
allotted time)` before calling search. Search then reserves
`min(0.5 seconds, 8% of its own allowance)` for assembling results. In a normal
probe, 68% of the remaining search interval is initially allocated to proof;
witness search uses whatever remains to the final search deadline. Proof-only
uses the whole search interval for proof/refutation.

Diagnostics can use remaining query time, up to one second after their own
start. These are cooperative deadlines, not operating-system interrupts; move
generation, individual inspections, formatting and scheduling can overrun them
slightly. Inspect actual elapsed values and completed depths. The attached game
clock includes query/report overhead as well as engine search.

## Examples and interpreting results

Run commands from the repository root. Save the following as
`scratch/development-query.json`:

```json
{
  "label": "Compare two developing moves after 1. d4 d5",
  "mode": "analyze",
  "fen": "startpos",
  "after": ["d2d4", "d7d5"],
  "root_moves": ["c2c4", "g1f3"],
  "depth": 5,
  "seconds": 3,
  "candidates": 2,
  "diagnostics": true
}
```

```text
python astra_chess.py query --request scratch/development-query.json --output scratch/development-result.json --html scratch/development-report.html
```

For a targeted experimental comparison, add any desired flags:

```json
{
  "evaluation": {"mobility": true, "restricted_piece": true, "king_exposure": true},
  "threat_extensions": 2
}
```

That block shows fields to add to the analysis request; comparing one option at
a time makes its effect easier to interpret. Compare achieved depth and search
cost, not just the resulting score.

An independently runnable goal request, saved as `scratch/capture-query.json`:

```json
{
  "label": "Can White force capture of the queen currently on e4?",
  "mode": "probe",
  "fen": "7k/8/8/8/4q3/8/4R3/K7 w - - 0 1",
  "goal": {"type": "capture", "side": "white", "target": "e4"},
  "depth": 3,
  "seconds": 2,
  "candidates": 3,
  "proof_only": true
}
```

```text
python astra_chess.py query --request scratch/capture-query.json --output scratch/capture-result.json --html scratch/capture-report.html
```

This manufactured position allows `Rxe4` immediately. For a preservation question,
use `avoid_capture` and a target occupied by the goal side's own non-king piece.
To investigate a threat further along a line, copy that board's FEN plus its
preceding history, or use the report's follow-up query exporter.

In an analysis result, check `completed_depth`, `fallback`, `timed_out`,
`diagnostics.stop_reason`, and `settings` before relying on the top score.
Candidates include UCI, SAN, the initial and subsequent FENs, score, mate distance,
and how the line ended. `recommended_action` distinguishes moving, claiming a
draw, and an already ended game. The `diagnostics` result object also contains
search statistics even when optional **position** diagnostics were not requested.

For a probe, read both component statuses, the requested `horizon_plies`,
`proof_completed_depth`, `witness_exhausted_depth`, each line's `evidence`, and
the proof/witness interruption flags. `timed_out: false` alone does not say the
proof finished: the proof portion can exhaust its allocation while witness
search still completes. A line-count cap is also not exhaustive enumeration.

## Other facilities and limitations

Optional `--html` output is a standalone evidence viewer with board/line
navigation, a place for an independent assessment, and a follow-up JSON exporter.
It preserves selected options, preceding history and tracked goal identity when
branching. It does not run the engine inside the browser or automatically play
the recommended move. JSON outputs record the request, effective settings,
timing, engine version and a source hash covering rules, search and diagnostics.

`--game-clock` attaches a query to the append-only own-turn ledger used by the
live helper. The fixed cumulative mode, optional per-move clock, review reserve,
critical-position allocation, explicit credits/extensions, color-aware journal
and compaction recovery are documented in [ENGINE.md](../ENGINE.md) and
[the play skill](../skills/astra-chess-play/SKILL.md). The selected future staged
90/40 + 30 minute control with 30-second increments is still **planned**, not
implemented; see [TIME-CONTROL-NEXT.md](../TIME-CONTROL-NEXT.md). Legacy `--session`
turn clocks remain available and cannot be combined with `--game-clock`.

The report hints, positional weights and frontier extensions are intentionally
simple. They can miss quiet traps, long-term compensation, king attacks and
zugzwang; they can also overvalue an apparent advantage. More depth helps only
when enough of the relevant continuation is actually searched. The intended
workflow is to form a candidate and concern, inspect the engine's replies,
ask focused follow-ups where needed, and verify the real board before moving.

## Source map

| Implementation | Where to inspect |
| --- | --- |
| Base values/formulas | [`search.py`](../astra_engine/search.py): `VALUES`, `_GEOMETRY`, `_SHIELD`, `evaluate` |
| Candidate search, ordering, quiescence and mate/draw semantics | [`search.py`](../astra_engine/search.py): `_order`, `_Search`, `analyze`, `_terminal`, `_mate_plies` |
| Goal types, identity tracking, proof/witness search | [`search.py`](../astra_engine/search.py): `_goal`, `_target_after`, `_Probe`, `probe` |
| Optional scores and frontier trigger | [`diagnostics.py`](../astra_engine/diagnostics.py): `extra_evaluate`, `_credible_capture`, `_open_file_access`, `threat_frontier` |
| Board inspection | [`diagnostics.py`](../astra_engine/diagnostics.py): `diagnose`; [`astra_chess.py`](../astra_chess.py): `attach_diagnostics` |
| Request validation, defaults and time split | [`astra_chess.py`](../astra_chess.py): `prepare`, `run_query` |
| Rules and repetition/dead-position subset | [`rules.py`](../astra_engine/rules.py): `Position` |
| Live helper defaults and records | [`play_engine_game.py`](../play_engine_game.py): `parser`, `make_query`; [`clock.py`](../astra_engine/clock.py) |
| Regression evidence | [`test_engine.py`](../tests/test_engine.py), [`test_search_improvements.py`](../tests/test_search_improvements.py), [`test_diagnostics.py`](../tests/test_diagnostics.py), [`test_interface_improvements.py`](../tests/test_interface_improvements.py) |

The numeric constants above describe the code as implemented. When changing a
formula or option, update this reference with the implementation and validate
the intended tradeoff; a larger heuristic score alone is not evidence of stronger
play.
