# Astra Search Lab: proposed next iteration

Proposal accepted September 7, 2026. Implementation and measured defaults are
documented in [ENGINE.md](ENGINE.md) and [ENGINE-CHANGES.md](ENGINE-CHANGES.md).
The analysis below records the evidence and intended scope before implementation.

The preserved baseline is Git commit `37f3767`. It includes the unchanged engine,
tests, historical experiment artifacts, game 8 evidence, new replay, and updated
index. All 38 existing tests passed again before the commit. The rule/search
source hash still matches the recorded game. This proposal is separate from that
baseline. Experimental options remain separate from the default evaluation.

## What the evidence says

The engine assisted real decisions, including 36.Qc2 and the recovery of Black's
bishop, but it did not reliably expose the bishop trap or final king attack.
At White's move 21 it returned `Rfd1 c4 bxc4 bxc4` at -0.07. In the resulting
position Bd3 is threatened while its rear exits are blocked by c2 and Ne2.
I failed to inspect that fact, and the engine's evaluation could stop without
accounting for the impending piece loss. The earliest avoidable mistake in that
sequence has not yet been established.

The current continuation search permits a static evaluation when not in check
and mainly follows captures/promotions. An attacked piece or a quiet mating
threat can make that stopping assumption misleading. A few extra plies help,
but do not by themselves establish reliability.

A read-only benchmark before move 20 found:

| Time allowance | Candidate count | Completed depth | Nodes |
| --- | ---: | ---: | ---: |
| 4 seconds | 3 | 3 plies | 23,293 |
| 15 seconds | 3 | 4 plies | 93,809 |
| 4 seconds | 1 | 3 plies | 24,210 |

The 15-second search still rated Ra1 nearly equal and did not reveal the eventual
bishop loss in its displayed continuation. These are single-position measurements,
not general performance results. A profile of that position attributed about
62% of query time to legal-move generation and 23% to evaluation; roughly 98% of
visited nodes were continuation-search nodes. Profiling overhead affects the
timings, but the concentration of work gives us a concrete optimization target.

## 1. Give the combined player a real shared clock

**Recommended policy:** a 3,600-second cumulative clock for our turns. Ordinary
turns aim for 60–90 seconds; critical turns may use 120–180 seconds when the
remaining game budget permits. Keep time available for later play and reduce
allocations as it runs down. A simpler alternative is a hard 120-second budget
per move, without a cumulative limit. Choose one policy explicitly for each trial.

Start accounting from the first observation that it is our turn; stop when the
move is submitted and subsequently verified. Charge deliberation, commentary,
browser operations, retries, and all engine calls to that same interval. An
invalid click or rejected move must not end the turn. Persist append-only events
for observation, initial candidate, query, decision, submission, and verification;
reject attempts to reset the budget on the same ply. Keep timing uncertainty
visible when browser observation or action completion is delayed.

Reserve approximately 35–45 seconds for final inspection and move entry. The
previous average decision-to-submission gap was 22.5 seconds, with a maximum
near 45; the former eight-second reserve was unrealistic. Software still cannot
force me to move, so the clock must display remaining time prominently and report
overruns honestly.

Use roughly 10–20 seconds for an ordinary initial search. Allow another 20–60
seconds for a concrete unresolved danger when the clock permits. Every follow-up
spends the existing turn/game balance. Escalation triggers include an attacked
low-mobility piece, opening a line near the king, a sharp score change, an unstable
best move across depths, or a capture/check sequence that remains unresolved.
Quiet positions should not automatically consume the larger allowance.

## 2. Make threat inspection explicit and inexpensive

Add a diagnostic report for the starting position and returned candidate boards:
own-piece blockers, restricted mobility, enemy pawn control, legal pawn advances
that attack a vulnerable piece, and new lines toward the king. For the bishop
example, the report should explicitly identify c2 and e2 as blocked exits.

Compute this outside the per-node evaluator, reuse attack information, and include
its cost in the search/report budget. Label findings as **restricted mobility** or
**capture threat**. Geometric mobility is not proof that a piece can escape, and
no apparent safe square is not proof that it must be lost: capturing the attacker,
moving a blocker, exchanging pieces, and forcing counterchecks can matter.

Use the existing adversarial `capture` and `avoid_capture` goals for targeted
verification before adding an ambiguous new `trapped` goal. For example, from
the position after a proposed 21.Rfd1, ask whether Black can force capture of the
original White bishop on d3 within a bounded horizon. Those goals already track
piece identity and cover all legal defensive replies. Pair the result with normal
analysis: a forced capture can be an even trade or a compensated sacrifice.

Add an optional **proof-only** mode for urgent defensive probes. Currently the
probe splits its budget between adversarial proof and cooperative examples.
Proof-only mode would use the whole allowance for proof/refutation and return
`unknown` on timeout. It must preserve the full requested horizon for safety
goals; surviving fewer plies does not prove safety for the requested duration.

## 3. Trial small evaluation and search options separately

Initially optional, with independent switches and logged settings:

- Minor-piece mobility excluding own blockers and enemy-pawn-controlled squares;
  a modest, capped penalty for a threatened piece with very few available squares.
- King exposure from nearby open files and enemy queen/rook access. Build on the
  existing pawn-shield and phase-dependent king terms rather than duplicating them.
- An experimental, bounded extra full-width ply at a frontier with a concrete
  threat. Cap extensions per branch and retain every legal check evasion. Do not
  add all quiet moves throughout continuation search indiscriminately.

Report unresolved frontier threats when caps or deadlines prevent examination.
Do not turn a heuristic warning or a completed shallow analysis into a claim of
proved safety. Promote an option to the default only after it improves tactical
results at equal elapsed time on more than this game's known failures.

## 4. Optimize measured bottlenecks before deciding on a port

First preserve search semantics while reducing Python work:

1. Generate legal captures/promotions directly in ordinary continuation search,
   with a separate early-exit legal-move check for stalemate. When in check,
   generate every evasion. Preserve draw-claim and terminal handling.
2. Reuse child positions already constructed during legality checking, avoiding
   construction of the same child again when search enters it. Bound any cache.
3. Reduce evaluator rescans and precompute rule-derived geometry. Preserve score
   rounding and deterministic ordering in these pure speed changes.

Keep broader algorithm changes separate. Principal-variation search, different
candidate ranking, and cached transposition scores each need their own validation.
In particular, a cache keyed only by the board cannot safely reuse scores whose
draw status depends on the preceding position history.

If this pass still cannot reach useful depth within the new budget, propose a
compiled C++ or Rust core behind the existing JSON interface. Keep Python as the
reference. Port rules and search incrementally, checking legal moves, evaluations,
draw claims, goal proof status, timeouts, and every emitted line. No compiler was
found on PATH during this review; installed toolchains elsewhere have not been
ruled out. No toolchain installation or speedup is assumed or promised.

Rule-derived geometry tables are acceptable; opening books, endgame databases,
external engines, and learned evaluation data remain outside this experiment.

## Implementation order and acceptance gates

After review: first capture regression positions and repeatable timing baselines;
then implement the clock and report-level diagnostics; then make pure speed
changes; then trial evaluation and frontier options independently. Revisit the
compiled-core decision using those measurements. Each stage gets its own commit.

- Preserve the existing rules, perft, draw-history, proof/witness, and deadline
  tests. Pure speed changes must preserve fixed-depth scores and deterministic
  candidate order when given enough time to complete.
- Check every output line's legality, SAN, and FEN against the reference rules.
- Add the bishop trap and final attack, plus independent cases: immobile but safe
  pieces, pinned attackers, compensated sacrifices, capture of the attacker,
  freeing an exit, and counterchecks. Establish useful diagnostic behavior before
  declaring either known failure solved.
- Compare repeated unprofiled runs across opening, quiet middlegame, tactical,
  and endgame positions at 3-, 15-, and 45-second budgets. Measure fixed-depth
  elapsed time separately from fixed-time depth and tactical decisions. Include
  report/probe overhead, memory, and deadline overshoot.
- Proposed overhead gates: report-level diagnostics under 100 ms per inspected
  position on this machine; optional evaluation terms below roughly 10% median
  fixed-depth overhead if enabled by default, unless equal-time tactical results
  justify the cost. These are acceptance targets, not achieved measurements.
- Keep default speed refactors free of intentional search-strength concessions.
  A larger requested depth, a single improved score, or one win does not establish
  greater strength. Report failures as well as improvements.

The first recommended package is the shared clock, root/candidate diagnostics,
proof-only targeted probes, and measured Python optimization. The evaluator and
quiet-threat extension options can then be tested against that stable reference.
