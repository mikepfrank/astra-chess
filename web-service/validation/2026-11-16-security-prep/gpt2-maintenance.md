# GPT-2 maintenance helper preparation

November 16, 2026. The helper is source prepared for this host maintenance;
**no production gate, reload, stop, restart or package change was performed by
this implementation task**. Root coordinates the actual window with Mike and
must give his requested heads-up before first traffic gating.

Source: `web-service/tools/ops/gpt2_maintenance.py`. Standalone standard-library
helper for root and system Python on Lightsail. Its durable private checkpoint
is `/var/lib/gpt2-maintenance-ops/maintenance.json`, under a root-owned 0700
directory; checkpoints/backups are 0600 and contain the private lab route, so
never copy them into this repository or print their content.

## Commands and order

Run the staged, reviewed helper as root, replacing `HELPER` below with its
installed/staged absolute path. Use `python3 -u` for unbuffered SSH output;
drain/quiet progress also explicitly flushes every 30 seconds. These commands
document future actions.

1. `python3 -u HELPER check`: only live read-only checks; prints queue/status counts,
   no chat contents/private URL. Requires the currently reviewed lab source hash.
2. `python3 -u HELPER prepare`: snapshot original *individual GPT-2 site blocks*,
   both app identities/boot states, and network-unit state; privately back up
   current proxy config; validate both candidate gates without installing them.
   Refuses to overwrite an existing checkpoint. Staging files for validation
   are private and temporary beside Caddyfile so relative imports resolve.
3. **Downtime starts here:** `python3 -u HELPER gate-public`. Only POST
   `/api/message` and `/api/regenerate` receive 503/`accepted:false`; results,
   streams, health and static pages remain available.
   After public backend shutdown, its GET routes naturally return proxy 502
   until restart; only the generation POSTs show this maintenance response.
   This helper does not claim an all-page public maintenance banner.
4. `python3 -u HELPER stop-public --timeout 1200`: observe queue idle and pre-gate
   upstream connections settled; wait at least 600 uninterrupted idle seconds
   (honoring a larger advertised TTL), recheck at the boundary, then disable and
   stop. Work reappearing resets retention. Timeout leaves app running behind
   maintenance; it never forces a turn or declares success on timeout.
5. Mike must have **CLOSED all private lab tabs after work finished**. Merely
   pausing activity is insufficient: paused tabs still poll every two seconds
   and send presence heartbeats every fifteen seconds.
   `python3 -u HELPER gate-lab --owner-idle` requires this explicit operator
   assertion and still checks actual sessions, labeled containers, cgroup child
   processes and upstream connections for 60 continuous idle seconds. This
   exceeds the reviewed lab presence TTL of 45 seconds. The total quiet-check
   deadline is 300 seconds to allow existing keepalive connections to expire
   before the 60-second interval. Continued polling still causes refusal;
   increasing this deadline does not relax any idle/connection check.
   It does not change any
   session/pending flag or make a control/presence API call. Gating mid-turn
   would expire browser presence and cancel work; therefore it is refused.
6. `python3 -u HELPER stop-lab`: final idle/gate/identity checks, then disable/stop.
   Pending human inputs are preserved. Network/Docker units are recorded but
   not stopped/disabled by this helper. `status` shows phases and safe unit data.
7. Proceed with chess drain helpers and consistent offline backups/snapshot;
   the shared proxy restarts from those helpers now cannot interrupt GPT-2's
   600-second result-retention lead-in. Pause at agreed maintenance checkpoints.
8. After host/runtime changes: validate/re-establish Docker isolation separately,
   then `start-public` and `start-lab` in that order. Both remain gated and boot
   disabled while root performs fuller tests. The normal public memory guard
   remains enabled; do not bypass it. Lab startup checks network unit active,
   but does **not** substitute for firewall/container sandbox validation.
9. After regression/isolation checks pass, `reopen --validated` checks direct
   health, restores only the saved GPT-2 blocks into the **current** shared
   config, checks HTTPS health, and restores prior app boot settings. The
   completed checkpoint is archived privately. An aborted gate before stopping
   can use this same path once both apps are healthy and reopening is intended.

## Safety boundaries and recovery

- Caddyfile edits hold `/run/lock/astra-caddy-config.lock`, validate as `astra`,
  modify/fsync its existing inode, verify host/process bind agreement and use
  SIGUSR1 file reload. The helper checks journal success and real HTTPS gate
  responses. No Caddy restart or old whole-file restore is used.
- A shared operation lock prevents parallel invocations of this helper. Other
  operators must also honor the shared proxy lock. Independent edits inside a
  GPT-2 block cause refusal; changes to other sites survive reopening.
- No automatic rollback after a proxy reload failure: preserve checkpoint and
  inspect privately. Rerun the gate operation to reconcile an interrupted
  write/reload, or explicitly reopen after health checks. On a partial Caddyfile
  write or incompatible manual edit, manual scoped repair is required; do not
  overwrite current chess routes from the full backup.
- `prepare` records app identities; an unexpected restart before drain is a
  refusal requiring investigation, not a reason to erase the checkpoint.
- `start-*` provides readiness only, not generation/sandbox regression proof.
  Private scoped `/health` cannot establish queue/worker/isolation health.
- Default total public drain/retention deadline is 1200 seconds; a long accepted
  generation may require a larger explicit deadline (maximum 7200). Polling is
  every five seconds; the caller can collect output asynchronously.
- Existing public origins/aliases, private capability, all chess blocks, Astra
  new-game admission import, browser archives and GPT-2 budget/session data are
  untouched. Lifecycle stop changes only the two application boot settings;
  Docker/network enablement is deliberately left for coordinated host work.

The independent gates may be sequenced as `gate-public`, `gate-lab --owner-idle`,
`stop-lab`, then `stop-public`; this closes the lab during public result retention.
Do not launch concurrent commands: the operation lock is intentionally exclusive.
- Gate probes send an empty JSON object to public generation endpoints, which
  must be rejected as invalid if the gate is absent; they cannot generate text.
  No paid model calls, emails, or credential-bearing sandbox actions occur.

## Validation

`python -m unittest discover -s web-service/tests -p test_gpt2_maintenance.py`
passed 28 tests locally. It covers scoped config changes/restoration with unrelated edits, invalid/duplicate
layouts, public queue/connection retention and boundary races, owner assertion
plus actual lab quiescence, refusal to stop busy/ungated apps, and explicit
reopening acknowledgement. Full live candidate adaptation/validation and
read-only `check` should be run from the staged helper before the maintenance
heads-up; do not confuse source-only test results with a completed live drain.

## November 16 quiet-check refinement

The initial 120-second private quiet check correctly refused to gate while
upstream traffic continued. Source review confirms the paused UI keeps polling;
the HTTP/1.1 backend uses a 15-second socket timeout, so recently active bytes
are more consistent with an open tab than a long-unused connection. Source:
`gpt2_local/web/codex.html` polling/presence timers and
`gpt2_local/codex_chat.py` handler setup. Idle session records, even alongside
an owner's pause assertion, do not exclude an in-flight mutation/Resume request.
Keep the settled-connection and real worker/container checks; do not infer
quiescence from SQLite status alone. This local helper refinement must not
replace or interrupt an already-running public retention process.
