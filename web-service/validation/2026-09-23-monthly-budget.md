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

## Validation

- Windows budget suite: 43/43 passed, including v2 migration above the old cap,
  exact exhaustion, provider caps, September/October and December/January resets,
  skipped months, pre-first-check usage, corrupt/understated ledgers, key/counter
  regressions, clock reversal, concurrent migration/rollover and fetches spanning
  midnight. Impossible stale monthly counters are rejected without persisting;
  refreshed telemetry can retry normally, including BYOK.
- Windows gateway/bridge/service checks: 85/85 passed.
- Exact-commit Linux suite: 353 checks, 352 passed, one Windows-only skip.
- Native Linux Codex 0.154.0 mocked-provider audits: reasoning selection (four
  actions), tool visibility (nine checks) and private notes/request metadata
  (three actions/eight requests) all passed at `d21680d`.
- Node syntax and direct identity-rendering checks passed for Arcturus, Astra
  and a generic alternate persona. The served public JavaScript has the new
  Arcturus beta branch; public root, health and asset each return HTTP 200.

## Activation

Deployed commit `d21680d17958ebfc0db8151f2d61a4de7eaeca42` on September 23 at
20:27 UTC using the existing idle-gated helper. All 35 game documents, database
tables and private-file digests survived unchanged through activation, as did
private configuration, units and notification timers. Arcturus PID changed
4155008 -> 83871; original Astra/Caddy stayed 3778964/3778975. Health and gate
restoration verified. Coherent private backup:
`/home/or-chess/backups/ui-reasoning-20260923T202745Z`.

Only after activation/rollback checks succeeded, a fresh guard check migrated
the live ledger at 20:29 UTC: September spend **$21.610289586**, remaining
**$78.389710414**, $100 limit, no $5 reserve. Original key fingerprint and initial
usage counters were preserved; private mode 0600 verified. Numeric-only receipt:
`/home/or-chess/.local/share/or-chess/operator-checks/monthly-budget-d21680d.json`.
No paid model calls or game actions were performed for this update.

Future code rollback must retain a version 3 ledger reader or explicitly
reconcile only the budget record; do not restore an old baseline or game data.
