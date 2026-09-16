# September 15: missing post-game questions caused by tool-output truncation

Diagnosis only; no live runtime configuration, saved game, clock, or prompt was
changed. The operator requested review of the final exchange of a completed
81-ply Arcturus game, including whether questions reached the model.

## Findings

The five post-game human messages were accepted in order, each before its own
worker started. All five workers completed successfully with High reasoning;
there were no cancellations, API errors or timeouts in this exchange.

The private per-game Codex rollout contains complete `chess_status` outputs and
GLM reasoning content. The gateway receipts retain provider/status/usage
metadata, not complete outbound request bodies. A complete saved tool output is
therefore not proof that every character was sent to the model.

Codex applies a separate individual-tool-output budget. The service does not
currently configure `tool_output_token_limit`. With the pinned CLI and current
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
Linux receipts and preservation-checked activation are required before this
repair is reported as live.
