# Astra Search Lab 0.2 — implementation and validation

Implemented September 7, 2026, after approval of the improvement proposal.
The original engine and completed Wally trial remain at commit `37f3767`.
No new game was played during development. The engine still runs entirely in
Python's standard library, with no imported engine, book, tablebase, or network
analysis. The replay rules library is used only as a test oracle.

## What changed and the defaults selected

- **Faster default search:** generate legal captures/promotions directly during
  quiescence, stop early when checking for any legal move, reuse child positions
  already built during legality checking, and reuse rule-derived geometry and
  evaluator scans. All check evasions, history-dependent draws, and exact
  completed candidate rankings are retained. No evaluation-score transposition
  table was introduced.
- **A shared game clock:** one hour of cumulative own-turn time, normally up to
  90 seconds per turn and up to 180 for a recorded critical position, with a
  40-second reserve. Targets decrease as the balance falls. Optional fixed
  120-second turns are also supported. An append-only ledger records observation,
  candidate, query, decision, submission, rejection, and verification. Retries
  cannot reset the clock or silently advance the actual game journal.
- **Post-search diagnostics:** blockers, minor-piece mobility, legal pawn-push
  and capture threats, and opened king lines. Enabled by default in the live
  game helper, explicitly selectable in the general query interface. These
  describe warning signs, not forced losses. Coverage and overhead are recorded.
- **Proof-only goal queries:** use the full search allowance for adversarial
  proof/refutation when requested. The helper defaults to this mode for goals;
  `--witness` restores cooperative example search. Avoidance still covers the
  entire requested horizon.
- **Experimental options:** independent mobility, restricted-piece, and king
  exposure terms; up to two extra full-width plies at concrete threat frontiers.
  All remain off in ordinary searches. Use them for targeted comparisons when
  a diagnostic or manual inspection gives a concrete reason.
- **Report interface:** inspect threats alongside each returned board and select
  optional features for follow-up queries. Goal side and target identity are
  preserved while navigating; captured targets require explicit retargeting.
  Proof refutation is distinguished from an unfinished search. Narrow-screen
  board overflow was corrected.

## Measurements

Three unprofiled repetitions per position at completed depth 3, comparing our
own baseline against the final default implementation:

| Position | Median speedup |
| --- | ---: |
| Before 20.Ra1 | 2.48× |
| Before 21.Rfd1 | 2.55× |
| After 21...c4 | 2.45× |
| Final king attack | 1.87× |
| Initial position | 1.96× |
| Manufactured rook endgame | 2.03× |

All 18 comparisons had identical candidates, scores, principal variations,
draw declarations, and node counts. The median of the six speed ratios was
**2.24×**. This is a throughput measurement on this machine, not a playing rating.

One timing sample per version/position/budget, with experimental options off:

| Position | 3 seconds: old → new depth | 15 seconds | 45 seconds |
| --- | --- | --- | --- |
| Before 20.Ra1 | 3 → 3 | 3 → 4 | 4 → 4 |
| Final attack | 5 → 5 | 5 → 5 | 5 → 6 |
| Rook endgame | 5 → 5 | 5 → 6 | 6 → 6 |

All returned lines were replayed through our legal rules and checked against
their SAN and FEN records. None of these 18 timing samples exceeded its requested
wall-time budget. Machine load and iteration boundaries affect achieved depth.
The longer searches still did not establish a favorable evaluation before the
bishop trap; speed and depth alone do not fix the horizon problem.

Raw measurements are in `engine-benchmarks/`. The time-comparison aggregate hash
predates final optional-diagnostics optimizations; rules/search were frozen and
these searches never imported or called diagnostics. The repeated fixed-depth
and optional-feature comparisons use the final source hash.

Diagnostic microbenchmarks over eight boards measured about **57 microseconds
median per board**, with the slowest position's median about **93 microseconds**.
All three optional evaluator terms together added about 20 microseconds to a
base evaluator costing about 21 microseconds. This is added function cost, not
whole-search overhead. Six-position, three-second comparisons showed some
options reducing the completed base depth, so there is insufficient evidence
to enable them routinely.

The targeted bishop-trap test is useful: after 21.Rfd1 with Black's candidate
restricted to ...c4, a one-ply base search scored it -8cp for Black. One threat
extension gave +7cp and still missed the later material loss; two gave +190cp
and displayed `c4 Ra7 cxd3 Rxd3`. The two-extension search can be much more
expensive across a broad root, which is why it remains a targeted option.
These scores are this engine's estimates, not independent chess ground truth.

## Verification and reproduction

**80 Python tests passed**, including the original 38, special-move and draw
rules, seeded rule comparisons, optional-feature counterexamples, proof-only
semantics, and clock/journal integrity. The engine plus report command also ran
with site packages disabled. Browser tests passed for goal identity and side,
history, captured-target handling, proof verdicts, option export, and a 390-pixel
layout. The updated threat report was inspected in the embedded sidebar.

```text
python -m unittest discover -s tests -v
python benchmark_engine.py --repeats 3 --output engine-benchmarks/speed-equivalence.json
python benchmark_engine.py --time-only --output engine-benchmarks/time-comparison.json
python benchmark_engine.py --options-only --output engine-benchmarks/optional-comparison.json
python benchmark_diagnostics.py --output engine-benchmarks/diagnostics-micro.json
node tests/test_report.cjs PATH-TO-EXISTING-PLAYWRIGHT-PACKAGE msedge
python astra_chess.py query --request engine_examples/wally-bishop-threat-v02.json --output engine-output/wally-bishop-threat-v02.json --html engine-output/wally-bishop-threat-v02.html
```

The browser check used an already-installed Edge in headless mode; no browser
or chess software was downloaded. Run benchmarks sequentially without other
searches. The public replay pages and historical game records were not changed.

For the next Wally trial, start a new journal (for example, `init --game
wally-engine-v02 --round 9`), record the first observed own turn, and follow the
procedure in `ENGINE.md`. Initialization alone does not start a browser game.
