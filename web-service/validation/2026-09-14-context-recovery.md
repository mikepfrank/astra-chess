# September 14: Arcturus stalled continuation investigation

## Observed failure

An experimental game stopped responding after Black's tenth move. The saved
board, legal moves, player colors, and thread binding were correct. No Codex
child was left running. Eight consecutive attempts at the same position ended
without a submitted move; one instead exceeded the public-message size guard.
Several model replies described an initial board despite receiving the correct
current position from `chess_status`.

The failing requests completed at OpenRouter with HTTP 200 and complete streams,
using Friendli, GLM-5.3 Flash, Max reasoning, and 32,768 maximum output tokens.
Their input sizes ranged from approximately 152K to 168K tokens. No automatic
compaction had occurred; the configured threshold remains 250K. No output-limit
error or advertised provider context-limit rejection explained these attempts.
This establishes an incoherent model continuation, not a demonstrated provider
implementation defect or a proven context-length cutoff.

Repeated failures also leave erroneous public model remarks in the last twelve
messages returned by status. This can reinforce the error; the source of the
first incorrect response remains uncertain.

## Offline checks

A private copy of the game's existing session was resumed with the exact Linux
Codex CLI 0.154.0 and a mocked upstream provider. The outgoing request retained
the current FEN, ply, matching tool call IDs and results in order. The next
mocked tool result also appeared correctly at the end of the request. The copy
used its own rollout path; the live session was not changed.

`tests/audit_reasoning_roundtrip.py` separately exercised synthetic reasoning
summary, content, encrypted content, and combined fields. All four variants
preserved the exact fields and status snapshots through tool continuation,
process restart, and another tool continuation. Both Windows
0.154.0-alpha.6.2 and Linux 0.154.0 passed. The sixteen provider requests per
runtime were mocked, without real keys or inference charges.

The candidate's bridge and maintenance suites passed 46 tests on Linux
(one Windows-only process-job check skipped). The Windows bridge suite passed
all 42 tests, and the four maintenance tests passed separately. These include
rejection of unmatched compaction completion, unknown threads, chess tool calls,
public text, active services, changed game versions, and busy saved workers;
usage is settled even after a model failure.

## Prepared recovery

`CodexPlayer.compact` uses the existing thread and supported
`thread/compact/start` RPC. It preserves the saved persona and runtime profile,
requires a matched compaction lifecycle, rejects chess tools, and exposes no
public-chat emitter. It records provider evidence and normal usage telemetry.

`tools/ops/compact_player_context.py` requires stopped-service maintenance,
idle saved workers, an existing OpenRouter binding and the expected game
version. It reserves and settles the normal resource allowance, verifies that
every saved game document remains identical, and writes a private maintenance
receipt. The board, clock, chat transcript and game thread are retained. An
operator backup is required before use; historical data must not be restored
over new usage or game writes.

The operator explicitly authorized the copied-conversation test and recovery
on September 14 after automatic approval review initially blocked the request.
The refreshed copy included a later failed retry; that retry had an incomplete
provider stream, in addition to the earlier context-confusion failures.

At 15:45 UTC, real compaction on the copy succeeded through Parasail using the
same thread, saved prompt, Max reasoning and 32,768 output allowance. It used
138,750 input and 3,932 output tokens, cost $0.0227785, and preserved the entire
game document. The following request carried only 8,703 input tokens.

The first normal continuation timed out waiting for its second provider stream
within the ordinary 120-second allocation. A second continuation completed the
candidate/query/choose workflow and committed a legal check evasion in the copy.
The tactical query rejected the model's initial candidate, and the model used
that evidence to choose its final move. The accepted move stopped the chess
clock after 104.415 seconds.

This exposed a separate supervisor bug: follow-up text generation exceeded the
same turn deadline after the move had already been committed, leaving the
worker marked as an error. The recovery candidate handles that narrow case as
a completed action with a privately audited commentary timeout. It still
terminates the Codex process and charges conservatively when final usage is
unknown. Actual connection failures remain errors; the ordinary thinking-time
target follows the soft policy below.

The operator subsequently requested a soft two-minute thinking target for
Arcturus. Under that policy, an ordinary provider wait or continued reasoning
past 120 seconds does not abort an own-turn response. All such elapsed time
counts against the earned classical clock; tool responses warn the model after
the target is exceeded. The earned clock, token budget, and genuine transport
errors remain operational bounds. Once a move is committed, trailing text has
a short grace period and cannot convert the committed move into an error.
The bridge's independent process bound follows the host's earned-clock
allowance, preventing its old five-minute fallback from cutting a valid longer
turn short. This policy is scoped to OpenRouter own-turns.

## Live recovery completed

Code `18c910d` was deployed to the isolated Arcturus service after 87 targeted
Linux tests passed (one Windows-only process check skipped). The suite covers
reasoning transport, explicit compaction, maintenance accounting, soft targets,
post-move timeout handling, clock exhaustion and retry refunds.

The service was stopped only after an idle inventory and consistent snapshot.
A full private backup preceded the code update. Live compaction through the
installed service's restricted environment completed at approximately
16:11:33 UTC on September 14: 138,750 input and 2,218 output tokens, $0.0219215,
same thread, Max reasoning, 32,768 output ceiling and 250K automatic threshold.

Every saved game document remained identical, including moves, board, clocks,
messages and player bindings. Account, replay and request tables were unchanged.
Expected changes were limited to the target Codex context and receipts, audit
events, token accounting and the global OpenRouter spending ledger. The ledger
retained its cap, initial baseline and key binding, and spending moved forward.
The first final-check assertion had omitted that expected global-ledger write;
a separate private reconciliation confirmed it without restoring any data.

Both Arcturus HTTPS hostnames and the original Astra hostname returned healthy
responses. Original Astra and Caddy process IDs stayed unchanged. No transient
maintenance worker remained running. The live game is still at its original
position awaiting the user's Retry; the private test move was not copied into
it. Compaction and the new policy are active, but the user's next live move has
not yet been observed.

Private diagnostic copies and reports remain under the experimental account's
`operator-checks/turn11-*` directories. They contain game data and are not
included in this repository. The requested API key and unrelated account data
are absent from the synthetic tests and tracked artifacts.
