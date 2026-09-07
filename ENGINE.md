# Astra Search Lab

A chess engine and a question-driven interface for this experiment. The engine's
rules, move generation, evaluation, and search are written here from scratch.
Running it needs only Python's standard library. It reads no opening book,
endgame tablebase, external engine, online service, or trained evaluation model.

## The collaboration

I supply a position, a question, and a budget. The engine returns structured
evidence: candidate moves, replies, scores, and every board position along each
line. I inspect that evidence, apply my own judgment, and may ask a more focused
question from any intermediate position. A returned line is not automatically a
move recommendation, and a cooperative example is not a forced result.

`astra_chess.py` is the command interface. JSON answers can be read directly;
optional standalone HTML reports show the board, selectable lines, a place to
record an independent assessment, and a follow-up query exporter. The exporter
preserves the preceding position history when branching from a candidate line.
It prepares a query; it does not run search inside the browser.

## Two kinds of question

**Analyze** ranks candidate moves using iterative deepening and adversarial
alpha-beta search with a simple hand-written evaluation. Scores are in
centipawns from the player at the query's starting position, even when a report
is showing a later position. One pawn is 100 centipawns. The report gives the
last fully completed search depth; an interrupted first iteration is explicitly
labeled as a fallback. A principal variation is one selected continuation,
not an exhaustive display of every defense.

The evaluation uses material, centralization, pawn structure/advancement, rook
files, bishop pairs, and simple king placement. There are no imported
piece-square tables or learned weights. Quiescence follows captures and
promotions for up to eight extra plies and always considers compulsory check
evasions. A rare 96-ply checking chain interrupts the iteration rather than
substituting a quiet evaluation while in check. Base depth and the displayed
line length can therefore differ. Quiet-position evaluation can still miss
zugzwang and threats beyond the search horizon.

**Probe** asks whether a specified goal can be reached or maintained within a
fixed number of plies. At the goal side's turn, one successful move suffices;
at the opponent's turn, every legal response must be covered to prove the goal.
A separate search can find an example that depends on cooperative responses.
Goal searches do not discard quiet moves based on their material score.

The returned goal lines distinguish `proof_representative` from
`cooperative_witness`. Even when a forcing strategy exists, a separately listed
cooperative example may start with a move that does not force the goal. The
representative is one path through the proved strategy, not its whole tree;
query again from the actual next position if the opponent chooses another reply.

- `forced`: a strategy for the goal is proved within the specified horizon.
- `possible`: a qualifying example exists, but the bounded goal can be prevented.
- `unreachable`: no qualifying line exists within the specified horizon.
- `unknown`: the budget prevented a definitive answer. Inspect the separate
  `proof_status` and `witness_status`; an example may still be available.

These labels concern the requested finite horizon. “Unreachable in four plies”
does not mean unreachable later. A proof of avoiding a loss for four plies does
not prove the game can be saved indefinitely. Capture and check goals do not
establish that the resulting position is strategically good; analyze the
resulting position separately.

### Goal vocabulary

| Type | Meaning |
| --- | --- |
| `capture` | Capture the opposing piece initially on `target`. |
| `avoid_capture` | Keep my piece initially on `target` throughout the horizon. |
| `castle` | Complete a new castling move by the goal side. |
| `check` | Put the opponent's king in check. |
| `avoid_check` | Keep the goal side out of check throughout the horizon. |
| `checkmate` | Checkmate the opponent. |
| `avoid_checkmate` | Avoid checkmate of the goal side throughout the horizon. |
| `stalemate` | Leave the opponent stalemated. |
| `avoid_stalemate` | Avoid a stalemate of either side throughout the horizon. |

`side` is `white` or `black`; omitted means the starting player. `target` is
required only for the two capture goals. The engine tracks the identity of that
starting piece when it moves, castles, or promotes, including en passant
captures. The target is not just a square to occupy. Each query has one atomic
goal; separate queries keep multiple hypotheses explicit.

Achievement goals may finish before the horizon. A check, mate, or stalemate
already present can satisfy the corresponding goal immediately. Safety goals
must hold at every position through the full horizon or a terminal result;
simply starting safely does not prove they will continue to hold.

## Run a query

From this folder:

```text
python astra_chess.py query --request engine_examples/opening.json --output engine-output/opening.json --html engine-output/opening.html
python astra_chess.py query --request engine_examples/mate-in-one.json --output engine-output/mate.json --html engine-output/mate.html
```

A candidate search request:

```json
{
  "label": "Compare central development after this hypothetical continuation",
  "mode": "analyze",
  "fen": "startpos",
  "after": ["d2d4", "d7d5"],
  "depth": 5,
  "seconds": 3,
  "candidates": 3,
  "root_moves": ["c2c4", "g1f3"]
}
```

`root_moves` is optional and restricts only the starting player's candidate
moves. The opponent's replies remain unrestricted. All input moves use UCI
notation (`e2e4`, `e1g1` for castling, `a7a8n` for knight promotion). Output
includes UCI, standard algebraic notation, and complete FENs.

A focused question:

```json
{
  "label": "Can I capture the queen from this position?",
  "mode": "probe",
  "fen": "7k/8/8/8/4q3/8/4R3/K7 w - - 0 1",
  "goal": {"type": "capture", "side": "white", "target": "e4"},
  "depth": 3,
  "seconds": 2,
  "candidates": 3
}
```

Supply any structurally legal FEN instead of `startpos`. Optional `after` moves
apply a hypothetical continuation before searching. `history_fens`, if supplied,
must list actual preceding positions in order and exclude the starting FEN.
They are used for repetition claims; a FEN alone cannot establish earlier
repetitions. The caller is responsible for supplying an authentic history.

Draw claims are optional choices, including a claim made by declaring an
intended legal move. Such a declaration appears separately as
`claim_by_intended_move`; its unplayed move is excluded from the SAN/FEN
timeline. `recommended_action` distinguishes moving, claiming a draw, and an
already finished game. Fivefold repetition and 75-move draws are automatic.

`depth` counts plies (one player's move), from 1 to 32. `seconds` is a finite
positive search budget up to 180 seconds for study; `candidates` is 1 to 10.
Small scheduling, rules-generation, and output costs may extend the elapsed
time slightly beyond a search deadline. Search reports actual elapsed time.

## Optional inspection and search features (version 0.2)

Add `"diagnostics": true` to either kind of query to inspect the starting board
and returned candidate boards after search. The report lists own blockers,
minor-piece destinations outside enemy pawn control, legal enemy pawn pushes
that attack a piece, capture threats, and king lines. For example, the game 8
bishop on d3 has c2 and e2 blocked and can be attacked by ...c5–c4. When the enemy
is not to move, its threats are explicitly hypotheses on the unchanged board.
Geometric mobility is not a list of safe legal escapes. No warning means only
that these limited checks did not flag anything.

Diagnostics are cached per returned position/preceding board, run outside the
node evaluator, and have a shared deadline (at most one second, within the query
allowance). `diagnostic_coverage` discloses skipped positions and elapsed cost.
Queries reserve a small part of their allowance for inspection. HTML generation
and all other query overhead also count against an attached game clock.

Three extra evaluation terms are independently switchable and **off by default**:

```json
"evaluation": {"mobility": true, "restricted_piece": true, "king_exposure": true},
"threat_extensions": 2
```

`mobility` adds a small minor-piece mobility term excluding enemy pawn controls.
`restricted_piece` adds a capped penalty when such a piece has few destinations
and a credible capture threat. `king_exposure` assesses enemy heavy-piece access
along open files near the king. These hand-written heuristics can misjudge
compensation or defense and cost search time; they are experimental, not trained
chess knowledge.

`threat_extensions` (0, 1, or 2; default 0) allows that many additional full-width
plies per branch when a restricted minor piece is threatened at the search
frontier. It retains quiet defenses, blocker moves, captures of the attacker,
and counterchecks. Every legal check evasion is still searched independently of
this option. Reports disclose extended and capped frontiers; a cap or timeout
does not certify safety. A single extra ply was insufficient in the recorded
bishop-trap regression, while two exposed the subsequent material loss.

For a concrete piece question, use the existing `capture`/`avoid_capture` goal
with the piece's current square and `"proof_only": true`. That dedicates the
search budget to adversarial proof/refutation and skips cooperative witness
search. A refutation is reported as `proof_status: "refuted"`; overall `status`
may remain `unknown` because cooperative reachability was not examined.
`witness_status: "not_searched"` is not absence of a line. Avoidance still must
hold throughout the entire requested horizon, and capturing a piece does not
by itself prove a favorable exchange. Omit/disable `proof_only` to request the
original combination of proof and cooperative example search.

The HTML follow-up exporter preserves these settings and the selected board's
history. Every JSON result records effective search settings, version, and a
source fingerprint covering rules, search, and optional diagnostic/evaluation code.

## Clock and procedure for the next live game

Default: **one hour of cumulative own-turn time**, including deliberation,
queries, commentary, browser interaction, retries, and verification. Aim for
**60–90 seconds on ordinary moves**, with up to **120–180 seconds for a concrete
critical position** and **40 seconds reserved for review and move entry**.
Allocations shrink as the balance runs down. Alternatively initialize with
`--clock-mode move --move-seconds 120` for a fixed two-minute per-move allowance.
Both modes are cooperative: they report overruns rather than forcing a browser
move or concealing excess time.

`play_engine_game.py` requires an explicit new game directory name. Initialization
never overwrites a saved game. It does not control the browser or choose moves.
Run its `--help` for the observation, candidate, query, decision, submission,
rejection, and verification commands. An append-only `clock.jsonl` ledger records
the events; a turn starts at first observation and ends only after the submitted
legal move is verified. Repeating the same ply or marking a position critical
cannot reset elapsed time. A failed click leaves the clock running.

The general query interface attaches to that same ledger:

```text
python astra_chess.py query --request my-query.json --output engine-output/answer.json --html engine-output/answer.html --game-clock engine-games/NEW-GAME/clock.jsonl
```

The older `turn-start`/`--session` interface remains available for reproducing
the first trial, but is not the recommended live-game clock. It cannot be
combined with `--game-clock`. Queries are sequential under an exclusive lock.
Clock discontinuities, delayed timestamp entry, and uncertain timing are visible
in the ledger and status. The observation timestamp must come from the earliest
observed own turn, not a later confirmation read.

My planned turn procedure:

1. Record the earliest observation, reconcile the actual position, then record
   my initial candidate and concern before querying.
2. Request three candidates with roughly 15 seconds of search, a depth ceiling
   of 8, and diagnostics enabled. A ceiling is not a promised achieved depth.
3. Inspect the opponent's forcing replies and the candidate boards: checks,
   captures, changed king lines, loose/restricted pieces, and promotion threats.
4. For a concrete unresolved threat, mark the position critical and spend the
   remaining shared allowance on a deeper restricted-root comparison, a
   proof-only goal probe, or a comparison with up to two threat extensions.
   Experimental evaluation terms remain opt-in until broader evidence warrants
   making them defaults.
5. Choose a legal move, record the submission, and verify the browser position.
   Rejected or uncertain submissions consume the same turn balance.

Queries and decisions retain whether the engine changed my initial assessment,
what concrete opportunity or vulnerability it revealed, achieved depth, options,
and timing. These are qualitative observations, not an established playing
rating. The next live game is a new trial; development tests do not start it.

## Files and verification

- `astra_engine/rules.py`: immutable positions, legal move generation, SAN,
  FEN, castling, en passant, promotion, and repetition identity.
- `astra_engine/search.py`: evaluation, bounded candidate search, draw handling,
  and goal proof/witness searches.
- `astra_engine/report.py` and `report.template.html`: offline evidence viewer.
- `astra_engine/diagnostics.py`: optional rule-derived inspection and heuristics.
- `astra_engine/clock.py`: cumulative own-turn clock and append-only event ledger.
- `play_engine_game.py`: explicit game journal and verified-move workflow.
- `astra_chess.py`: validated requests, hypothetical positions, and turn budgets.
- `engine_examples/`: small manufactured examples and two study queries around
  the original Wally game's 29. fxg6. Recorded games are input examples, never
  search knowledge or opening databases.
- `tests/test_engine.py`: rules, search semantics, and interface checks.
- `tests/test_*improvements.py`, `test_clock.py`, `test_diagnostics.py`: speed-path
  equivalence, optional features, clock integrity, and interface integration.
- `benchmark_engine.py`, `benchmark_diagnostics.py`, `engine-benchmarks/`: repeatable
  comparisons against this engine's preserved baseline, including raw results.

```text
python -m unittest discover -s tests -v
```

The tests optionally use the already installed replay copy of `python-chess`
as an independent rules-only oracle. That library is not imported by the engine
or interface, provides no evaluation or move advice, and is not needed to run
the engine. The deterministic rules tests also work without it.

The preserved version 0.1 baseline passed **38 tests** on September 7, 2026, including
six recorded games, 400 seeded random playout positions, initial perft counts
20/400/8,902, all goal types, target identity through moves/promotion/en passant,
prospective draw declarations, root rankings, deadlines, and shared-budget
enforcement. The engine and report-generation command also ran with Python
site packages disabled.
That baseline result and runtime import audit are in `engine-output/verification.json`.
Version 0.2 passed **80 Python tests**, plus the report's browser integration
checks. Its measurements and selected defaults are in [ENGINE-CHANGES.md](ENGINE-CHANGES.md).

Representative original-baseline measurements on this machine:

| Query | Completed base depth | Search elapsed |
| --- | ---: | ---: |
| Initial position, three candidates, 3-second limit | 4 plies | 2.77 seconds |
| After the original Wally game's 29. fxg6, four candidates, 5-second limit | 4 plies | 4.61 seconds |

In the second query the leading line starts `Qf2+ Kh1 Qf3+ Kg1 Qxd3`.
An earlier search of the parent position at completed depth three still rated
`fxg6` favorably for White. This is a concrete example of the horizon limitation
and why a focused follow-up can matter; it is not a measured playing rating.
Runtime varies with the position and machine load. JSON answers record the
engine source hash, search timing, achieved depth, and query for reproducibility.

Draw handling distinguishes stalemate and checkmate, and checkmate takes
precedence over move-count draws. Repetition requires available history.
Insufficient-material detection covers the usual certain cases conservatively;
it does not attempt to prove every exotic blocked dead position. Evaluation and
finite search also have horizon limitations; they are not tablebase results.
