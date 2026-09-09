# Astra own-turn time audit

Settled moves through **70**, playing **white**. 70 own turns; **109:56.7** raw charged time and **109:56.7** after recorded refunds.

Completed queries consumed **23:07.8** (21.0% of charged time, 91 queries). The remaining **86:48.9** is not individually attributed.

Explicitly excluded pause/resumption intervals within these settled turns: **0:00.0**.

Mean move: **1:34.2**; median: **1:21.1**. 31 turns exceeded 90 seconds; 16 exceeded 120 seconds.

## Largest charges

Intervals overlap with query time; do not add the columns.

| Move | Charged | Queries | Observation to entry | Decision to submission/end |
|---|---:|---:|---:|---:|
| 49. a5 | 5:58.4 | 0:25.9 | 1:17.7 | 0:10.6 |
| 43. Rh7 | 4:06.6 | 0:33.1 | 1:22.5 | 0:16.7 |
| 41. Re7+ | 3:36.8 | 0:43.1 | 1:03.2 | 0:15.2 |
| 48. Kh2 | 3:15.9 | 0:14.0 | 2:00.3 | 0:15.2 |
| 44. Re7+ | 2:56.8 | 0:14.0 | 0:43.4 | 0:24.3 |
| 19. Qg4+ | 2:43.2 | 0:43.1 | 0:30.0 | 0:30.0 |
| 20. b3 | 2:35.5 | 0:48.1 | 0:37.0 | 0:12.5 |
| 36. Rf4 | 2:22.9 | 0:14.0 | 0:59.5 | 0:23.0 |
| 21. Qxc4 | 2:15.9 | 0:38.1 | 0:30.4 | 0:30.9 |
| 33. Re8 | 2:13.6 | 0:14.0 | 0:59.1 | 0:15.7 |

## Ten-move blocks

These are mechanical blocks, not inferred opening/middlegame/endgame boundaries.

| Moves | Charged | Query wall | Other remainder | Mean per move |
|---|---:|---:|---:|---:|
| 1-10 | 10:56.4 | 3:12.4 | 7:44.0 | 1:05.6 |
| 11-20 | 17:23.0 | 5:06.7 | 12:16.3 | 1:44.3 |
| 21-30 | 16:30.5 | 2:42.0 | 13:48.5 | 1:39.0 |
| 31-40 | 14:30.7 | 2:10.5 | 12:20.2 | 1:27.1 |
| 41-50 | 27:41.2 | 3:34.3 | 24:06.8 | 2:46.1 |
| 51-60 | 10:24.0 | 2:53.4 | 7:30.6 | 1:02.4 |
| 61-70 | 12:31.0 | 3:28.5 | 9:02.5 | 1:15.1 |

## Evidence and limits

- Only settled own turns are included. Unsettled elapsed time is not estimated, even when a documentary pause note is present.
- The saved charged_seconds is authoritative. User refunds are shown separately and are never inferred from notes.
- Timestamp stages exclude only explicit user_time_extension pause/resumption intervals; these exclusions are reported separately from refunds.
- Query time is completed query wall time recorded by the clock, including orchestration and failed queries; it is not pure search CPU time.
- The nonquery remainder includes model deliberation, commentary, command overhead and UI work; their exact individual costs are not logged.
- Observation-to-recording includes any work before journal entry, including deliberation; it is not a tool-latency measurement.
- The last decision-to-charge-endpoint interval includes move entry and any further review or interruptions; it is not solely browser latency.
- Timestamp stage intervals and query time overlap and must not be added together. UTC offset differences are normalized.
- Late verification entry is not extra charged time when an earlier submitted timestamp is the saved charge endpoint. Some late entry work may fall within the next own turn.
- An explicit through-move cutoff excludes later settled turns. This report never reads the current live clock or changes any journal.

Total observation-to-entry interval: 30:06.0. Total last-decision-to-charge-endpoint interval: 18:46.0 across 70 turns with a recorded decision.

Source snapshot SHA-256:

```json
{
  "game": "li-v02-classical",
  "clock_sha256": "360537a6074db38cf09e2568ccb21caf7cbf7b4f8e018414723f8ce8e1f6d3b7",
  "game_sha256": "e8a600e0491585610ae255a7efd1630d41f2af9af03fc24ab6fa96b5adf5cb6c",
  "last_clock_seq_in_snapshot": 537
}
```
