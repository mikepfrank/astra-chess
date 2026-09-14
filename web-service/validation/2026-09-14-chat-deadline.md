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
clock. The initial deadline repair retained Max reasoning; the later
per-response effort change is described below. The per-response output cap,
daily token admission, provider spending guard and own-turn clock policy remain
unchanged. Astra keeps its
existing chat and bridge deadlines.

Current v4 Arcturus games use High reasoning for chat during the human's turn
and after the game, and Max for move decisions. The host derives the response
kind from the authoritative board/status, then passes it as a separate trusted
bridge argument. Gateway validation, Codex configuration, thread resume and
turn start all use the selected effort. Private per-action receipts record it.
The saved game's original Max profile, persona, prompt and replay metadata do
not change. Earlier High/8K games and Astra/Ultra preserve their recorded
policies. Automatic compaction within chat inherits High; a separate explicit
operator compaction uses the saved policy. Neither changes the 250K threshold.

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

The same 50 checks passed on Linux at exact commit `16e2bd8`, with no failures
or skips. The idle guard deferred the first deployment attempt until a response
finished. At **22:07:33 UTC**, the Arcturus-only gate enclosed backup, code update,
namespace preflight and restart. All 14 game documents, database table digests,
private files, environment and service units remained unchanged. Original Astra
and Caddy process IDs were unchanged, and the gate restored its exact previous
configuration. The private backup is `chat-deadline-20260914T220733Z`.

Before the live retry, Mike requested High reasoning for chat while retaining
Max for move decisions. Exact commit `ce66868` passed all 151 focused Windows
checks; Linux passed 150 and skipped its Windows-only process-tree check.
The additional tests cover runtime profile validation, immutable game identity,
High chat → Max move → High post-game chat, bridge configuration/resumption,
automatic and explicit compaction, and rejected untrusted effort overrides.

The actual remote Codex 0.154.0 executable completed Max move → High chat → Max
move on the same disposable thread. All six mocked upstream requests carried
the expected effort, unchanged instructions and seven canonical tools, with
32,768 output tokens. The 250K threshold, original saved Max profile and thread
were preserved; each process was reaped. No real credentials, external provider
contact or player records were used for this native transport audit.

The idle guard deferred activation while another player was being served.
At **22:24:26 UTC**, a second gated deployment activated `ce66868`. All 14 game
documents, database tables, private files, environment and service units matched
across activation. Original Astra/Caddy PIDs were unchanged, and the exact proxy
configuration was restored. The private backup and deployment receipt are under
`chat-deadline-20260914T222426Z`. Two workers, aggregate resource limits, Max move
reasoning, output/context limits and spending controls were preserved.

## Live pending-chat verification

One Retry of the existing pending human-turn chat started at **22:25:27.823 UTC**
and completed at **22:28:54.576 UTC** (206.8 seconds). The worker-start event,
bridge runtime policy and private provider receipt all recorded **chat / high**
with 32,768 output tokens. All three provider request streams completed, with
zero gateway rejections. Four public assistant entries were added and the worker
returned to idle. Its board, moves, clock ledger/balance and original saved Max
profile/thread matched the private pre-retry baseline. No chess move was made
and no chess time was charged for the test.

Mike subsequently confirmed seeing the chat response. The signed-in browser
displayed the reply, unchanged **1:03:24** remaining chess
time and "Your move. Take your time." with no Retry/error state. Both original
and experimental services, Caddy and the two notification timers remained
active. The private `live-chat-result.json` is retained beside the deployment
receipt. This verifies successful completion under High; it is not evidence of
an average latency improvement. This individual response still took roughly
3 minutes 27 seconds, so responsiveness remains an observation for subsequent
beta play.
