# Completed: Astra won as Black

Game 10 ended with **48...Rcxd2#**, result **0-1**, in the embedded browser.
Final move submitted at `2026-09-08T02:02:08.819Z`; Chess.com checkmate and
the complete move list were observed at `2026-09-08T02:02:18.969Z`.
The journal has 96 verified plies, no pending move, and a finished clock.
Use `game.pgn`, `game.json`, and `clock.jsonl` as the completed record.

## Resolved pause and extension

The user authorized finishing with reasonable additional time. The append-only
extension `wally-black-extension-1` added 900 seconds to the original 3600,
with 120-second allocation targets and the existing 40-second entry reserve.
The pause boundary `2026-09-08T01:41:35.130231+00:00` preserved 3690.855 seconds
already used, including the original 90.855-second overrun.

The first live observation on resumption was `2026-09-08T01:56:30.503Z`,
confirming the unchanged position after 45.Kf2. Only the documented 895.372769
seconds of paused waiting/setup were excluded. No original charge was refunded.
Final charged own time: **3951.183 seconds (65:51.183)**; remaining extended
allowance: **548.817 seconds (9:08.817)**. The old permission warning is resolved.

## Experiment continuity

Rules, search, and evaluation stayed frozen at fingerprint
`96e9ed243d69eede25b24c4c22248753053ee162b51fd0eb4cc081f47a311174`.
Clock accounting changed only to represent the explicit authorized extension.
The future staged/increment policy is recorded in `TIME-CONTROL-NEXT.md`;
it was not applied retrospectively to this game.

No new game is authorized by this completion note. The requested archive is now
`replays/wally-engine-v02-black-replay.html`, with color-aware score export and labels.
Build instructions are in `README.md`; replay metadata explicitly selects Black.
