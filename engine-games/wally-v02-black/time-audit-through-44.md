# Astra own-turn time audit

Settled moves through **44**, playing **black**. 44 own turns; **59:37.4** raw charged time and **59:37.4** after recorded refunds.

Completed queries consumed **9:16.4** (15.6% of charged time, 43 queries). The remaining **50:21.0** is not individually attributed.

Explicitly excluded pause/resumption intervals within these settled turns: **0:00.0**.

Mean move: **1:21.3**; median: **1:14.4**. 8 turns exceeded 90 seconds; 4 exceeded 120 seconds.

## Largest charges

Intervals overlap with query time; do not add the columns.

| Move | Charged | Queries | Observation to entry | Decision to submission/end |
|---|---:|---:|---:|---:|
| 44... Rc1+ | 2:45.7 | 0:00.0 | 2:23.2 | 0:22.3 |
| 1... c5 | 2:45.2 | 0:14.0 | 0:13.1 | 2:02.9 |
| 28... a5 | 2:44.8 | 0:24.6 | 0:43.2 | 0:47.7 |
| 10... Nxd4 | 2:10.8 | 0:43.1 | 0:18.7 | 0:10.7 |
| 15... Bc5 | 1:47.7 | 0:14.0 | 0:31.0 | 0:46.0 |
| 30... Rc5 | 1:41.3 | 0:04.3 | 0:44.6 | 0:18.9 |
| 22... Nf5+ | 1:34.6 | 0:10.1 | 0:38.6 | 0:31.9 |
| 41... Bf5 | 1:30.8 | 0:09.0 | 0:17.0 | 0:14.8 |
| 26... Rxd5 | 1:29.7 | 0:14.0 | 0:31.1 | 0:29.0 |
| 21... Ne7 | 1:29.3 | 0:14.0 | 0:29.9 | 0:22.1 |

## Ten-move blocks

These are mechanical blocks, not inferred opening/middlegame/endgame boundaries.

| Moves | Charged | Query wall | Other remainder | Mean per move |
|---|---:|---:|---:|---:|
| 1-10 | 14:04.1 | 2:49.3 | 11:14.7 | 1:24.4 |
| 11-20 | 12:29.0 | 2:20.3 | 10:08.6 | 1:14.9 |
| 21-30 | 14:35.0 | 2:13.2 | 12:21.8 | 1:27.5 |
| 31-40 | 12:04.0 | 1:44.5 | 10:19.5 | 1:12.4 |
| 41-44 | 6:25.3 | 0:09.0 | 6:16.2 | 1:36.3 |

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

Total observation-to-entry interval: 18:40.7. Total last-decision-to-charge-endpoint interval: 17:34.3 across 44 turns with a recorded decision.

Source snapshot SHA-256:

```json
{
  "game": "wally-v02-black",
  "clock_sha256": "9f9ab0b91d55f6bfc2c888a24b8afd7e019e54870564b51d17a1d24a69111768",
  "game_sha256": "1aa12f804a56c37b9210cd3af9673851309d9444b16c2cdeb6fd46fc026c6e30",
  "last_clock_seq_in_snapshot": 312
}
```
