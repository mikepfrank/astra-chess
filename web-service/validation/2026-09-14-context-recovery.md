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

**Not yet applied or proven to restore this game:** automatic approval review
blocked the copied-game OpenRouter compaction test pending explicit user
permission to resend that conversation. The user was asked to authorize the
bounded test and subsequent live recovery. No paid recovery request, live
compaction, service restart, or chess move has occurred in this investigation.
The live checkout remains unchanged. Do not report the game as fixed until a
real continuation succeeds.

Private diagnostic copies and reports remain under the experimental account's
`operator-checks/turn11-*` directories. They contain game data and are not
included in this repository. The requested API key and unrelated account data
are absent from the synthetic tests and tracked artifacts.
