# Game 8 evidence audit

Local audit of `game.json`, all referenced request/result JSON pairs, and the stored line positions. This audit reran the project rules only; it did not perform a new search or use an external chess engine. The parent agent separately captured `browser-movelist.txt` from the final embedded-browser accessibility state and programmatically confirmed that all 80 SAN plies match the journal.

## Record integrity

- All 80 played plies, canonical SAN entries, and 81 FENs agree exactly when replayed with `astra_engine.rules`. The final move is 40...Re1; result is 0-1 by resignation.
- All 55 referenced output files have matching request files; no duplicate references, missing pairs, or unreferenced output files were found. This describes preserved evidence, not a guarantee that no failed or overwritten invocation occurred.
- Every request root and complete preceding FEN history matches the journal. All 560 candidate plies have legal UCI, matching canonical SAN, and matching stored FENs.
- The 40 selected White moves match the actual journal. All 40 recorded decision clocks have query counts and engine charges consistent with the saved outputs. All recorded submission intervals match their UTC endpoint differences.
- All outputs record the same engine source SHA-256: `c610956f6253e4f09c84a602cb5f45e09bb1a0af55af510fd7ab5980627ecef7`.

## Search totals

- 55 successful stored queries: 53 across the 40 played White moves, plus 2 during the resignation review.
- Completed depths in plies: depth 2 = 1 query; depth 3 = 27; depth 4 = 22; depth 5 = 5. Fifty queries reached a time limit; none returned a fallback.
- Search time summed from outputs: 176.861 seconds including resignation review, 171.548 seconds for played moves. Interface time including result handling: 178.362 seconds overall. Total reported nodes: 1,112,500.
- Per-turn search time including resignation review: mean 4.314 seconds, median 3.688, range 1.422-9.173. Every turn stayed below the 12-second engine allowance. Move 9 used the most time (9.173 seconds).
- All queries were normal analysis; 14 restricted the root candidate moves. No goal probes or hypothetical continuation (`after`) queries were exercised in this game.
- The selected move differs from the logged initial candidate on 13 of the 40 played moves. This count measures changes of selection, not whether each change improved the position.

## Recorded turn timing

These statistics cover White moves 2-40 (39 moves). Move 1 had setup/context overhead and is excluded; turn 41 ended in resignation and is not a played move. The recorded observation timestamp starts each interval.

| Interval | Mean | Median | Minimum | Maximum |
| --- | ---: | ---: | ---: | ---: |
| Observation to recorded decision | 29.378 s | 27.175 s | 18.475 s | 55.557 s |
| Observation to submission timestamp | 51.894 s | 50.572 s | 35.909 s | 77.225 s |
| Recorded decision to submission timestamp | 22.516 s | 19.877 s | 15.988 s | 44.908 s |

- All 39 decisions were recorded before 60 seconds, but 8 submissions exceeded 60 seconds: moves 9 (74.287), 15 (68.510), 20 (72.284), 22 (69.735), 24 (69.695), 33 (60.836), 35 (62.286), and 36 (77.225). Thus the overall turn-time target was not consistently met.
- Move 1: recorded decision at 23.375 seconds; submission at 203.830491 seconds after the journal clock start. Per the parent agent, its overhead included initial automatic approval rejection, context compaction, and setup; setup before the recorded clock start is not measured.
- Move 17: per the parent browser audit, the clock began at the later confirmation timestamp 17:05:11.958Z, although ...b5 was already visible around 17:04:55Z. Its logged 55.460-second submission interval therefore undercounts roughly 17 seconds. The table above is deliberately the uncorrected journal statistic, not an exact measure from first possible observation.
- Turn 41 has no decision/submission/resignation timestamp in `game.json`. The parent agent separately observed resignation confirmation at 2026-09-07T17:32:14.035Z, 103.532 seconds after the logged turn-41 observation. This is a result-confirmation interval, not a played move time.
- Submission timestamps are captured after browser actions return, so these intervals include tool/action latency and are not exact physical-click timestamps. The decision-to-submission gap includes final review, commentary, and tool overhead; it is not exclusively engine or reasoning time.
- Initial candidates and concerns are present in all 41 turn records, but the journal has no separate immutable candidate-entry timestamp. It documents the workflow without independently proving when each idea was first formed.

## Per-turn detail

| White turn | Successful queries | Completed depths (plies) | Search seconds | Decision seconds | Submission seconds |
| ---: | ---: | --- | ---: | ---: | ---: |
| 1 | 1 | 4 | 2.765 | 23.375 | 203.830 |
| 2 | 2 | 4, 5 | 4.703 | 34.777 | 54.727 |
| 3 | 1 | 4 | 2.765 | 19.612 | 36.047 |
| 4 | 2 | 3, 4 | 5.532 | 32.379 | 50.672 |
| 5 | 2 | 3, 4 | 5.531 | 33.192 | 51.675 |
| 6 | 1 | 3 | 2.766 | 21.952 | 57.309 |
| 7 | 2 | 3, 4 | 5.531 | 30.942 | 46.930 |
| 8 | 2 | 3, 4 | 5.531 | 33.305 | 50.572 |
| 9 | 3 | 2, 4, 4 | 9.173 | 55.557 | 74.287 |
| 10 | 1 | 3 | 3.687 | 26.472 | 44.461 |
| 11 | 1 | 3 | 3.688 | 20.098 | 40.870 |
| 12 | 1 | 3 | 2.766 | 18.475 | 35.909 |
| 13 | 1 | 3 | 3.688 | 24.184 | 45.846 |
| 14 | 1 | 3 | 3.688 | 22.398 | 41.789 |
| 15 | 1 | 3 | 3.688 | 23.602 | 68.510 |
| 16 | 2 | 3, 3 | 6.453 | 37.352 | 53.991 |
| 17 | 1 | 4 | 3.688 | 30.169 | 55.460 |
| 18 | 1 | 4 | 3.687 | 19.866 | 41.637 |
| 19 | 1 | 4 | 3.687 | 21.705 | 40.179 |
| 20 | 2 | 3, 3 | 6.453 | 35.285 | 72.284 |
| 21 | 1 | 3 | 3.687 | 32.084 | 55.139 |
| 22 | 2 | 3, 4 | 7.376 | 49.901 | 69.735 |
| 23 | 1 | 3 | 3.688 | 21.305 | 41.330 |
| 24 | 2 | 3, 4 | 6.453 | 36.492 | 69.695 |
| 25 | 2 | 4, 4 | 6.452 | 34.329 | 54.894 |
| 26 | 1 | 4 | 3.688 | 22.879 | 48.923 |
| 27 | 1 | 4 | 3.688 | 26.659 | 45.487 |
| 28 | 1 | 4 | 3.687 | 22.067 | 40.470 |
| 29 | 1 | 4 | 3.688 | 27.389 | 45.566 |
| 30 | 1 | 3 | 3.687 | 24.131 | 43.632 |
| 31 | 1 | 3 | 3.687 | 22.712 | 42.992 |
| 32 | 1 | 3 | 3.687 | 30.691 | 54.490 |
| 33 | 1 | 3 | 3.687 | 24.294 | 60.836 |
| 34 | 1 | 3 | 3.688 | 27.175 | 48.334 |
| 35 | 1 | 3 | 3.687 | 42.409 | 62.286 |
| 36 | 2 | 3, 4 | 6.454 | 49.970 | 77.225 |
| 37 | 1 | 3 | 3.688 | 23.690 | 56.242 |
| 38 | 1 | 4 | 3.687 | 25.053 | 43.768 |
| 39 | 1 | 5 | 2.297 | 33.340 | 52.124 |
| 40 | 1 | 5 | 1.422 | 27.846 | 47.551 |
| 41 | 2 | 5, 5 | 5.313 | n/a | n/a |
