# September 15: missing post-game questions caused by tool-output truncation

During the initial diagnosis, no live runtime configuration, saved game, clock,
or prompt was changed. The operator requested review of the final exchange of a completed
81-ply Arcturus game, including whether questions reached the model.

## Findings

The five post-game human messages were accepted in order, each before its own
worker started. All five workers completed successfully with High reasoning;
there were no cancellations, API errors or timeouts in this exchange.

The private per-game Codex rollout contains complete `chess_status` outputs and
GLM reasoning content. The gateway receipts retain provider/status/usage
metadata, not complete outbound request bodies. A complete saved tool output is
therefore not proof that every character was sent to the model.

Codex applies a separate individual-tool-output budget. The service did not
configure `tool_output_token_limit` before this repair. With the pinned CLI and former
configuration, the middle of sufficiently long tool results is replaced by a
`chars truncated` marker, retaining roughly 12,000 characters overall.
`chess_status` puts moves before recent chat, with board/clock metadata and
candidate/decision evidence afterward. Recent questions landed in the omitted
middle even though they were present in the service response and saved rollout.

## Exact Linux reproduction

All five saved status outputs were replayed through Linux Codex **0.154.0** in
fresh isolated test homes, with High reasoning and an entirely mocked upstream.
The existing `tests.audit_reasoning_roundtrip.audit_case` helper was used with
in-memory hooks for input inspection and production Unicode serialization
(`ensure_ascii=False`). No live thread was resumed and no OpenRouter request or
paid inference occurred. Five cases made 20 mocked requests; each tested both
immediate continuation and process restart/resumption, with identical visibility.

| Original status time (UTC) | Raw characters | Wire characters | Characters removed | Visibility result |
| --- | ---: | ---: | ---: | --- |
| 22:30:23 | 14,517 | 11,968 | 2,571 | Initial harness question missing |
| 22:32:14 | 14,838 | 11,965 | 2,895 | Older congratulations survive; harness question and follow-up missing |
| 22:34:55 | 15,568 | 11,969 | 3,621 | Original harness question now survives; newer follow-ups missing |
| 22:41:39 | 18,404 | 11,961 | 6,465 | Original question survives; new discussion of coding tools missing |
| 22:42:37 | 18,441 | 11,964 | 6,499 | Original question survives; newest delivery complaint missing |

This reproduces the observed responses: a closing caption, a response to older
congratulations, a delayed tool inventory, and two statements that no new message
was pending. The reasoning records describe missing/truncated messages rather
than deciding to reject the operator's questions as prompt injection. The saved
player prompt also permits discussing the experiment and tools.

The actual historical full HTTP request bodies were not captured. The table is
a reconstruction of each tool output's wire representation using the same
binary, configuration and source content, corroborated by the historical
reasoning and public replies. It does not claim byte-for-byte reconstruction of
the entire historical conversation payload.

## Independent synthetic check and candidate repair

Windows Codex **0.154.0-alpha.6.2** independently lost a middle-position latest
message sentinel in 16,147-, 48,147- and 120,147-byte synthetic outputs. A fixture
with `tool_output_token_limit=8192` still truncated a 48,147-byte result; a
32,768-token tool budget preserved it exactly. These were also isolated,
mocked-provider checks, with no tracked runtime changes.

A repair should combine an explicit, verified tool-output budget with a bounded
status format that prioritizes new human messages. Merely raising the overall
250K compaction threshold or the 32K model response ceiling does not address
this independent limit. Test actual outbound message visibility through the
native CLI, not only host snapshots or retained rollout content. Reordering chat
alone is insufficient for arbitrary long results, and increasing the limit alone
does not guarantee all future unbounded payloads remain intact.

Relevant code: `astra_web/chess_game.py:model_snapshot`,
`astra_web/codex_bridge.py:_config_text` and `_event_input`, and
`astra_web/openrouter_gateway.py:_forward`. The
[official Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)
defines `tool_output_token_limit` as the budget for individual tool/function
outputs in history; its exact default truncation behavior above is empirical.

Private source transcripts, reasoning, per-message IDs and reproduction homes
remain excluded from Git. Synthetic local receipts are under
`var/status-truncation-audit/`; exact Linux receipts remain in the private
operator-checks directory. This document retains only diagnostic findings.

## Authorized repair

The operator authorized a substantially larger per-tool output budget. The
repair sets `tool_output_token_limit = 65536` for OpenRouter runtime profiles,
including existing GLM games. The bridge verifies the effective setting from
Codex `config/read` before starting or resuming a thread. Missing, altered or
noninteger values stop the attempt rather than silently accepting truncation.
This is a transport configuration repair: no saved game profile, persona,
prompt, thread identity, reasoning preference, chess-clock policy or model
response ceiling changes. Original Astra configuration is unchanged.

The 52 focused bridge and chat-reasoning tests passed locally. The reusable
`tests/audit_tool_visibility.py` regression checks actual outgoing tool results
with 10,000-character Unicode human comments in the middle of 20,000-, 80,000-
and 160,000-character snapshots. It checks the immediate continuation, history
after process restart and the next tool response on the resumed thread. Exact
Linux receipts and preservation-checked activation were required before this
repair could be reported as live.

## Verified activation

Release `4783af4c9b853ce2d51ea9d62c63e35ad88d9ab6` is live after the
September 16 **00:27 UTC / September 15 19:27 CDT** activation. The exact staged
Linux commit passed 266 regression checks: 265 passed, one Windows-only skip.
The native visibility audit passed all nine wire checks across twelve mocked
requests. The independent four-action/eight-request High/Max audit retained the
original binding and existing reasoning/response policy. Windows native
visibility checks had also passed with the same three fixture sizes.

The same five saved status results from the diagnosis were then replayed through
the updated Linux bridge with High reasoning and production Unicode serialization.
All five entire results, including every human message, survived in the actual
mocked-provider input, both immediately and after thread resumption. These were
fresh disposable threads; no live player action was initiated.

Idle was checked before and within the Arcturus-only maintenance gate. The
deployment backed up private data and configuration, restarted only Arcturus,
and verified all 19 saved games, all database-table digests and all private-file
digests unchanged. Original Astra/Caddy process IDs, every service unit, both
notification timers and private configuration were unchanged. Health passed and
the maintenance gate restored its original configuration. The larger tool budget
will be written and verified when each subsequent GLM action begins, including
actions on existing saved games. No other site or live conversation was changed.

The activation receipt is retained in the private September 16 00:27 deployment
backup; exact-commit test/native receipts remain in the private staged checkout.
Later documentation-only commits record this result and require no restart.
