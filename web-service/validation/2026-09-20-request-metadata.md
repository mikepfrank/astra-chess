# Private request metadata for future OpenRouter diagnosis

Mike authorized lightweight instrumentation after investigating inconsistent
input-token counts around repeated output-limit failures. This captures future
request structure without retaining another copy of private conversation text.
It does not reconstruct missing evidence for the earlier incident.

## Receipt fields

The existing private `provider-requests-*.json` records gain:

- `request_index`: one-based within the host action's gateway.
- `started_at`, `finished_at`: UTC timestamps, beginning after budget approval.
- `duration_ms`: monotonic elapsed time for measurement and upstream forwarding,
including response streaming; finalized on success, error or cancellation.
- `cancelled: true` when cancelled; cancellation still propagates normally.
- `usage.cached_input_tokens` and `usage.reasoning_output_tokens` when provided
  as valid nonnegative integers in standard nested provider usage fields.
- `request_metadata`, version 1, described below.

`canonical_payload`, `instructions`, `tools` and `input` each contain
`json_bytes` and `sha256`. Canonical JSON uses sorted keys, ASCII escaping,
compact separators, no nonfinite numbers, then UTF-8 encoding. This deliberately
stable comparison representation is not HTTPX's literal transmitted encoding.
Absent instructions serialize as null. Tools also include their count. Input
includes its count and `format` (`list`, `text`, or `other`). A text input is
classified as one synthetic user item; its input fingerprint still measures
the original string. `previous_response_id_present` indicates linked state,
without storing its ID.

`categories` uses only fixed labels: `reasoning`, `user`, `assistant`,
`developer`, `system`, `tool_call`, `tool_output`, `other`. Unused categories
are omitted. Unknown/malformed types and roles become `other`, never dynamic
receipt keys. Each category contains its item count, the sum of canonical JSON
item byte lengths, and an ordered aggregate SHA-256. Hash input for each item is
its eight-byte big-endian length followed by its canonical bytes. There are no
per-item hashes or copied IDs, names, text, arguments or arbitrary input labels.

`reasoning_bytes` separately counts plaintext `text`/`content`, summary text,
and encrypted-content UTF-8 bytes. Invalid lone surrogates use replacement
encoding for these counters; canonical JSON remains safely escaped. These
counts are bytes, not tokenizer estimates. Reasoning is only classified from
Responses reasoning items, not inferred from the prose of ordinary messages.

## Placement and interpretation

Measurements occur after the gateway's existing tool filtering, output allowance
and conditional trusted reminder, immediately before its upstream operation.
The bridge waits for gateway cleanup before writing its receipt, so cancelled
requests' final timing and status are included in the durable snapshot.
They stay alongside existing provider selection and usage fields in private
server receipts. No public endpoint, game document, AI prompt or export changes.
No extra inference request, provider pin, reasoning switch or compaction-policy
change is introduced. The model-context fallback discrepancy documented in the
earlier incident is not changed by this diagnostic addition.

Fingerprints reveal equality and stay private; they are not anonymization.
Fixed aggregates keep each receipt small regardless of message count. An
identical input fingerprint with a different reported token count identifies
an upstream discrepancy, but cannot prove which tokens the model actually saw.
Different fingerprints can also reflect structural IDs or metadata changes.
Provider-side translations, retention and tokenization remain outside our view.

## Validation and deployment

Prepared. Focused gateway tests cover forwarding preservation, mixed input
shapes, bounded/private metadata, timing and usage on incomplete/cancelled/error
paths. The native private-note audit additionally compares actual mocked
upstream requests with in-memory and persisted receipts across resumed actions.
Deployment requires that exact-commit audit along with existing Linux, reasoning
and tool-visibility receipts.

A local synthetic size check measured about 0.9 ms for 100K reasoning characters,
8.9 ms for 1M, and 42.1 ms for 6M. Metadata was 877-881 JSON bytes in that
two-category fixture. These are one-run measurements on the Windows laptop,
not provider latency or a guaranteed server performance bound.
Another near-ceiling fixture (7.9M characters) took 54.2 ms and produced 763
metadata bytes with one category.

Exact-commit checks and idle/gated activation are pending. No live move, retry,
chat or paid provider request is needed for validation.
