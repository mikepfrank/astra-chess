# Monitor finished-game results — November 25, 2026

Requested change: a small wins/losses/draws breakdown inside Arcturus's
Finished summary card. Results are explicitly from the AI's perspective.

## Scope and behavior

The existing private API supplies the full inventory, after configured
fixture exclusions. The browser counts only finished rows: human loss means
AI win, human win means AI loss, and draw means draw. Unrecognized/missing
results are listed as unrecorded. Filters, search, and pagination do not alter
the overall totals. No API, database, model, or account changes were needed.

## Checks

- `node --check` passed for the changed application and browser-test JavaScript;
  `git diff --check` passed.
- `node tests/browser/monitor.cjs` passed using the documented Playwright
  1.62.1 and installed Chrome. Every request was intercepted; no real accounts,
  game actions, email, or model calls were used. This included existing private
  access, refresh/staleness, pagination, escaped names, and cleanup checks.
- New assertions cover AI-result mapping with both human colors, ignoring
  unfinished rows, unknown outcomes, all-page totals, filter independence,
  refreshed counts, and mobile width. Desktop and mobile screenshots were
  visually inspected; generated screenshots remain in ignored
  `web-service/var/browser-qa/monitor-results-{desktop,mobile}.png`.
- Independent code review confirmed the live `fa184ab` API has the same
  complete-inventory and outcome contract.

## Deployment and live verification

Development commit: `5ac159df05fec780985ad403ad257fca8475d6e7`.
Deployment commit: `7512aa2c0226ba375549864be7b65dd8a859132e`, cherry-picked onto
live base `fa184aba3a212fb542d59ef3592c7484b3a96caa` in the isolated branch
`codex/arcturus-monitor-results-20261125`. Only the two static files and their
browser test changed. Remote checkout cleanliness, expected base/target, and
the exact changed-file allowlist were checked before fast-forwarding.

Public HTTPS verification returned HTTP 200 and `Cache-Control: no-cache`,
with exact file hashes matching the deployed checkout:

| File | SHA-256 |
|---|---|
| monitor.js | cf0e3b2dc74c91306d7f2d1f2424b334a328cea3318cf7789b019e76d7b95e19 |
| monitor.css | 7548373dd835010b63b3508ded8678bc550444b70b1d9389c8beaeda6b84b395 |

The read-only production report, using the running service's data directory
and exclusion list, showed 55 player games and 18 finished games: **18 AI wins,
0 losses, 0 draws, 0 unrecorded**. No real private browser session was used;
layout verification used synthetic data, and live verification checked assets
and aggregate inventory separately.

PIDs before/after were unchanged: Arcturus 10124, Astra 10123, Caddy 15765,
GPT-2 public 9959, GPT-2 private 10059. No service was stopped or restarted.
Arcturus's checkout was clean afterward; Astra remained at `995a587`.
Existing open monitor tabs need a page reload to fetch the new script.

If rollback is needed, revert the isolated change on the deployment branch
and fast-forward the Arcturus checkout after checking current HEAD/cleanliness;
do not reset across subsequent work or deploy the entire development branch.
