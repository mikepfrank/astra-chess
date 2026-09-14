# Arcturus chat deadline, September 14, 2026

## Confirmed failure

The operator reported repeated errors while requesting only a sidebar chat
reply during the human's turn. Four recorded attempts began at 21:38:13,
21:42:31, 21:53:14 and 21:54:38 UTC and failed about 60.2 seconds later.
Each ended with the supervisor's `TimeoutError: Player response deadline reached`.
The failures straddled the monitor activation; the monitor restart did not
change any game records. The existing position remained after White's 18th move.

The earlier OpenRouter time-policy change applied only to the AI's own chess
turn. Chat during the human's turn still received a hard 60-second allowance,
and post-game chat received 120 seconds. Max reasoning remained selected.

A separate read-only audit found two HTTP-200 requests per failed attempt.
The first completed a status-tool request; the second was streaming reasoning
but was canceled before terminal completion. No provider rejection, output
limit, model mismatch or Codex error appeared. About 43K input tokens were
present, below the 250K compaction trigger. Resource counters showed no OOM,
task-limit rejection or CPU throttling. The preceding successful chat took
about 58 seconds, just below the same cutoff. No raw reasoning, chat transcript,
credentials or player identifiers are included in this record.

## Correction

OpenRouter chat receives a separate 600-second host response budget and a
900-second bridge ceiling. The host supplies the latter budget; opponent text
and model tool arguments cannot change it. Completed context compaction retains
the existing pause policy, while the bridge provides a bounded outer timeout.
The model sees chat timing explicitly identified as not charging the chess
clock. Max reasoning, per-response output cap, daily token admission, provider
spending guard and own-turn clock policy remain unchanged. Astra keeps its
existing chat and bridge deadlines.

A human move supersedes an in-flight human-turn chat. The old worker is
canceled and reaped before the already queued chess response can start. Stale
public text and tactical results cannot be persisted after supersession.
Already accepted messages remain saved; uncertain provider usage still settles
conservatively. Ordinary commentary alone is not treated as a completed response.

## Verification and activation

All 50 focused Windows tests passed: chat timing, post-game chat, bridge timing,
supervisor limits, compaction/clock settlement and parallel-worker isolation.
The eight new chat tests include five supersession races (waiting, compaction,
direct text, tool text and tactical-query completion). Independent source review
confirmed stale callbacks cannot write into the new ply and the old process is
reaped before one successor starts. Tests used disposable data and fake players.

Exact-commit Linux checks, idle deployment and a live retry remain pending.
