# September 20: repeated output-limit failures, followed by recovery

Read-only investigation of the latest player-reported stalled game. Checked the
saved game, audit/clock events, provider receipts, native session metadata and
service process/resource state. No game action, provider request, retry,
compaction, clock adjustment or service restart was performed during diagnosis.
Private chat text, hidden reasoning and player identifiers are not copied here.

## Current status

At 14:19 UTC September 20, the game was active at 30 plies after Black's
`15...b5`, waiting for the human's 16th move. Worker idle; no active responses,
replay builds or token reservations anywhere in the service. The last accepted
move was at 03:07:11 UTC September 20 (11:07:11 p.m. Eastern September 19), and
its worker completed at 03:07:14 UTC.

Installed checkout remains `515d2ea`, running backend `31f3270`. Arcturus PID
`4056774` is unchanged since September 18. The service cgroup contains only that
Python process, with all memory pressure/OOM counters zero. The bounded service
journal query returned no matching error messages; provider receipts and game
audit events provide the useful failure evidence.

## Established failure sequence

| UTC interval | Position/action | Evidence |
|---|---|---|
| Sep 19 22:05:48-22:18:21 | Black's seventh move | HTTP 200, then incomplete `max_output_tokens`; 32,768 output tokens, AtlasCloud; no move. |
| 22:18:21-22:19:15 | Next attempt | Candidate/query/choose succeeds; `7...O-O` accepted. Trailing response is cut off by the normal post-move allowance; no worker error. |
| 22:51:46-23:03:05 | After White's `8.Qd2` | Same 32,768-output cutoff, AtlasCloud. |
| 23:03:05-23:14:37 | Same position | Same cutoff, AtlasCloud. |
| Sep 20 00:07:44-00:19:35 | Same position | Same cutoff, AtlasCloud. |
| 00:25:34-00:38:39 | Same position | Same cutoff, AtlasCloud. |
| 00:38:39-00:39:12 | Same position | Complete response, 1,251 output tokens, all reported as reasoning; no ordinary answer or tool call. Host correctly rejects completion without a move. |
| 00:40:55-00:41:36 | Automatic compaction | Completed in 40.954 seconds, paused the AI clock; no board changes. |
| 00:43:48 | Recovery | `8...Nbd7` accepted, explicit sidebar comment follows. |
| 02:09-03:07 | Continued play | Seven subsequent AI moves through `15...b5` succeed without worker errors. |

The five length failures consumed the full configured 32,768 output allowance
each and took roughly 11-13 minutes per failed action. The gateway explicitly
records `incomplete_reason=max_output_tokens`; this is separate from the soft
two-minute move target, daily allowance, 2M action budget and input compaction
threshold. The output cutoff also happened with the conditional comment reminder
absent, so it was not triggered by an appended reminder on those requests.

All five length failures were routed to AtlasCloud. That provider also completed
successful requests before and after the failures, including compaction and its
first continuations. The recovery query-result review and move were subsequently
served by Z.AI; later moves used CoreWeave. These observations establish the
failure location, not a proven provider-specific or model-internal defect.

## Context, accounting and remaining uncertainty

The failed move-eight requests reported about 112K input tokens. Their incomplete
responses did not update Codex's last completed-request token metadata. The next
completed reasoning-only response reported 290,831 input tokens, exceeding the
250K automatic compaction setting. Compaction then reported 111,277 input/2,900
output; the first ordinary request afterward reported only 8,805 input tokens.
The exact cause of this inconsistent pre-compaction input accounting was not
established by these receipts. Native token events also label the effective
window as 258,400 while the saved/runtime profile records 1,310,720; that telemetry
discrepancy merits a separate audit rather than silently changing configuration.
No provider context-length rejection was recorded. The later source/log audit
below resolves the effective-window discrepancy and compaction timing, but not
the provider's input-count jump.

### Follow-up: exact compaction trigger and effective limits

A second read-only audit compared native token events and numeric native log
fields with official Codex source at tag `rust-v0.154.0`.

- The failed move-eight attempts left native `last_token_usage` at 107,666 input
  plus 7 output = **107,673 total**, unchanged across the incomplete responses.
  Our gateway saves their usage in provider receipts, then rejects the
  incomplete terminal event as `upstream_output_limit`; it does not forward that
  terminal usage update to Codex. Native usage updates on completed responses.
- At **00:39:11.817 UTC**, the completed response with no move updated native
  last usage to 290,831 input + 1,251 output = **292,082 total**.
- The next action started at **00:40:55 UTC** and compacted before normal play.
  Codex's total-scope trigger uses the last completed request's total plus
  estimates for subsequently appended local items, not cumulative lifetime
  billing. Thus this last completed usage explains the timing.
- Native turn logs show **244,800** effective auto-compaction limit and
  **258,400** usable context, despite requested settings 250,000 / 1,310,720.
  The exact warning that the GLM slug uses fallback model metadata is present.
  This version's fallback descriptor sets both context and maximum context to
  272,000; the configured context override is clamped to that maximum. The
  compaction limit is then `min(250000, 272000 * 90%) = 244800`, and usable
  context is `272000 * 95% = 258400`. These are effective Codex metadata limits,
  not evidence about GLM's actual provider-supported capacity.

Source locations: `codex-rs/core/src/context_manager/history.rs` lines 635-694;
`core/src/session/turn.rs` lines 1090-1115 and 2644-2678;
`models-manager/src/model_info.rs` lines 25-36 and 142-179;
`protocol/src/openai_models.rs` lines 515-524 and 1994-2009. Downloaded source
is in ignored `var/codex-compaction-source/`; no hidden reasoning text was
printed or interpreted.

The provider input-count jump remains unresolved. Native history retained large
plaintext reasoning records from failed generations, but that alone does not
establish which tokens the provider processed or counted on each request.
Five failed records each contain 131,072 text characters; all pre-jump reasoning
records total 702,157 characters. These are structural sizes, not exact tokens
or proof that reasoning was newly reintroduced on the 291K-input request.
Do not explain compaction as adding all repeated input billing together, or
claim it triggered at 112K. Repairing model metadata or changing the threshold
requires a separate runtime change and validation; neither was done here.

The five failed attempts at move eight were refunded by the existing explicit
Retry path (2,899.817 seconds total), with per-attempt evidence retained. This
investigation made no further clock changes. The successful compaction's 40.954
seconds were excluded from the chess clock automatically.

The model's later sidebar explanation attributed the pause to housekeeping;
that omitted the preceding output-limit failures. Saved provider metadata is
the authority for this incident. A useful follow-up would be clearer user-facing
output-limit errors and a bounded recovery policy after repeated length cutoffs.
Simply raising the output ceiling could prolong the same failure. Any change
to reasoning, provider routing or automatic compaction needs its own decision
and validation; none was made here.
