# September 23: UTC monthly OpenRouter budget and beta label

Requested policy: $100 per calendar month with UTC boundaries, all experiment
spending to date charged to September, and BETA in the Arcturus board badge/title.

The service keeps its existing shared-key scope and credential fingerprint.
Version 2's original cumulative usage baselines are preserved in version 3.
Migration-month spend is the combined OpenRouter/BYOK cumulative delta; later
months use current-month provider counters, including spend before the month's
first chess request. Same-month spend never decreases. Missing/invalid monthly
telemetry, backwards cumulative counters or clock month, and credential changes
fail closed. A fetch crossing a UTC month boundary leaves the ledger unchanged.
Monthly allowance is $100; the old $5 admission reserve is removed. This remains
local admission control and cannot prevent delayed/in-flight overspend.

Provider field semantics were checked against the official
[limits reference](https://openrouter.ai/docs/api_reference/limits) and
[current-key endpoint](https://openrouter.ai/docs/api/api-reference/api-keys/get-current-api-key).
A read-only live check confirmed both UTC monthly fields and no provider key cap.
No key/account label/fingerprint or raw provider response was saved here.

Arcturus's badge is BETA, title/footer use Beta, and its description no longer
calls it experimental. Astra's existing Public beta labels are retained.

Validation and activation: pending. Deployment must preserve game/database and
private-file digests before the first version 3 guard check; migrate only after
the existing activation checks succeed so automatic code-only rollback can still
read the prior budget ledger. No paid model calls are needed for this update.
