# Arcturus experimental deployment

The preferred address is `arcturuschess.com`, served from the separate
`or-chess` Linux account. It retains the Codex driver, selects the
`openrouter-glm` profile (`z-ai/glm-5.3-flash:nitro`, Max reasoning for new games), and binds
new games to the Arcturus persona. The original Astra account, application
unit, repository and game data remain independently operated.

## Canonical domain and existing accounts

The experimental unit sets `ASTRA_ORIGIN=https://arcturuschess.com` and
`ASTRA_ADDITIONAL_ORIGINS=https://arcturus.astraplayschess.com`. The optional
comma-separated alias setting defaults to empty in other deployments. Each
request must use an explicitly configured Host; writes require that host's own
Origin and the existing session/CSRF checks. Listing two origins never permits
cross-host writes. `/api/config` exposes only the preferred `canonical_origin`.

Keep the old Arcturus hostname serving the same application and data. Cookies
remain host-only: existing passwords work at the new address, but visitors must
sign in there. Passwordless visitors should use **Your account → Add a password**
on the old address before moving. Its manual new-address notice explains this;
the new address does not link back to the original Astra domain. Game IDs,
replay paths, saved player bindings and recovery records stay in the same data
directory. Recovery links use the preferred origin. No account tokens or browser
storage are copied between domains.

After the idle-only application/unit update and installed-namespace preflight,
run `tools/ops/activate_arcturus_domain.py` on the server as root in default plan
mode. Review its successful route/config validation, then use `--apply` with
`--expected-config-sha256` from that plan. The helper appends only the new apex
proxy and HTTPS `www` 308 redirect, preserving the original configuration bytes,
bind-mounted inode, original routes and all three service process identities.
It reloads the verified Caddy process through pinned-PID SIGUSR1. Backups and
reports are private under `/var/lib/arcturus-domain-activation`. A failed
activation attempts to restore and verify the original routes; any concurrent
unknown configuration edit requires manual reconciliation.

Verify real certificates, `www` path/query preservation, old/new Arcturus health,
replay continuity and unchanged original Astra routes. Compare saved table,
private-file and budget hashes around maintenance. This change requires no paid
model calls or emails. Website activation does not enable SES mail delivery.

## Max reasoning for new games

Profile v4 uses Max reasoning and a 32,768-token output ceiling for each provider
response, including reasoning. The gateway supplies this limit when Codex omits
it and validates effort against the game's trusted runtime profile. Existing
High games retain their saved effort, response ceiling, prompts, conversation
and replay provenance. Their existing v2-to-v3 context-only compatibility rule
continues to apply. The 250K compaction trigger, 200M daily allowance, chess clock,
per-action token limit and dollar budget are independent of this change.

Activated from application commit `da1a1af` at the September 14, 00:40 UTC
maintenance checkpoint. Staged Linux regressions and actual Codex checks passed;
the installed namespace and isolated two-action Max test passed before restart.
All ten paid requests completed with Max/32,768, costing $0.01170204 in total.
Saved user data/replays and budget baseline were preserved, and the original
Astra/Caddy processes were unchanged. The coherent private backup and operator
receipt are under `/home/or-chess/backups/max-reasoning-20260914T004026Z/`.
See [the sanitized validation record](../experiments/arcturus-max-reasoning-2026-09-14.json).

Before activation, verify Max on the actual Codex build through the local mock
gateway, including tool continuation, compaction and output-limit failure. Check
all saved game bindings against the staged code without mutating their records.
Deploy at an idle boundary with a coherent private backup and stop/restart only
`or-chess.service`; verify the public `/api/config` reports `reasoning: "max"`.
Any paid validation belongs in a disposable operator-check directory under the
same service restrictions and shared spending ledger, while normal workers are
stopped. Record it separately from the preserved user games.

## Initial validated deployment: September 13, 2026

This is the original activation record. The subsequent context-compaction
update is recorded separately below.

The experimental service is enabled and serving HTTPS at
[arcturus.astraplayschess.com](https://arcturus.astraplayschess.com). Application
code through `e1d5cf8` is deployed. Namespace preflight, actual Codex wire audit,
80 focused Linux tests and the two-action paid smoke test passed. The test
played `1.d4 a6 2.Bf4` and reported `$0.00600888` in inference cost. See the
[sanitized test record](../experiments/arcturus-linux-smoke-2026-09-13.json).

Caddy 2.11.4 accepted the candidate and reloaded through SIGUSR1, preserving its
PID, the Astra application PID, and the mounted Caddyfile inode. The original
apex and www responses matched their preflight state. The new hostname passed
certificate, secure-cookie, foreign-origin, illegal-move and record-persistence
checks. Windows HTTPS requests confirmed Arcturus/GLM and Astra/Ultra on their
respective hostnames, and the browser confirmed the Arcturus interface. The
successful private activation audit is
`/var/lib/astra-caddy-activation/activation-kzc4kc7k/report.json`; its directory
also contains the original configuration for recovery.

The local preview is stopped. The budget baseline was retained; the service and
paid operator checks use the same private host ledger. Long-game compaction and
playing strength remain untested. The following sections document the installed
layout and reproducible operator procedure; do not rerun hostname activation on
an already active configuration.

## Deployed context-compaction update: September 13, 21:32 UTC

Deployed code `43a494e` selects GLM profile v3: a verified 1,310,720-token
context window and a 250,000 total-context-token auto-compaction trigger. The
gateway accepts the audited exact `tools: []` compaction request and rejects
tool-call output from its text-only summary. The pinned persona, full prompt,
model, throughput routing, per-request budget check and 8,192-token output
ceiling still apply. Chess clock and turn allocation pause during reported
compaction; API tokens and the independent process timeout continue to count.
Gateway request bodies are capped at 8 MiB before and after serialization;
individual upstream SSE events retain the separate 2 MiB bound. Byte limits
remain independent of the configured context-token window.

Existing v2 games can use precisely this v3 context-policy upgrade when every
other identity field matches. Saved game/prompt/persona/tool provenance and
thread identifiers are retained; the bridge records its runtime context policy
separately. No game recreation, session deletion or budget reset is needed.
Unrelated profile changes and reverse upgrades remain rejected.

The OpenRouter action ceiling becomes 2,000,000 cumulative input/output tokens,
including repeated context and compaction. Smaller operator overrides remain
effective. The daily default remains 20,000,000 tokens, and the lifetime $50
usage-delta allowance and $5 admission reserve are unchanged. Daily admission
reserves the action ceiling and conservatively charges incomplete attempts.
The one-worker, half-CPU and 2 GiB limits remain unchanged.

The update passed 347 Windows service tests (two platform skips), a staged Linux
Codex 0.154.0 compaction/resume lifecycle, installed-unit namespace preflight,
and the same lifecycle under the installed unit's restrictions. The provider
was mocked throughout repair validation; no paid turn or live-game move was
started. Namespace configuration reported the 250K trigger and 2M action cap.

Only `or-chess.service` restarted. All saved database table contents and private
game/budget file hashes matched before and after; the saved thread and ply 11
position remained intact. Original Astra/Caddy PIDs were unchanged, and both
public health endpoints returned HTTP 200. The private coherent backup and
operator evidence are under `/home/or-chess/backups/compaction-20260913T213250Z/`.
See [the sanitized repair record](../experiments/arcturus-compaction-repair-2026-09-13.json).

## Active Arcturus daily allowance: 200 million tokens

Mike selected `ASTRA_MAX_DAILY_TOKENS=200000000` for this deployment's private
`/home/or-chess/.config/or-chess/service.env`. It was activated at 22:02 UTC on
September 13 after idle checks and a coherent private backup. The running process
and a check under the installed service restrictions both verified the setting;
loopback and public health returned HTTP 200. Game/database/private-file hashes
and the original Astra/Caddy PIDs were unchanged. Backup and private evidence
are under `/home/or-chess/backups/daily-limit-20260913T220210Z/`; see the
[sanitized update record](../experiments/arcturus-daily-allowance-2026-09-13.json).
This is an Arcturus deployment override: the shared application's
20,000,000-token default and the original Astra service remain unchanged.

The allowance applies to the existing UTC-day token ledger; retain its used
and reserved counters. The 2,000,000-token action ceiling, 500-turn daily limit,
single worker, $50 lifetime usage-delta budget and $5 admission reserve still
apply independently. Raising the daily token allowance does not reset or expand
the dollar budget. No application source change is required.

## Files and boundaries

| Path | Purpose and service access |
| --- | --- |
| `/home/or-chess/astra-chess` | Experimental repository and `web-service/.venv`, read-only |
| `/home/or-chess/.local/share/or-chess-runtime` | Private Python 3.12.14 and full Codex 0.154.0 bundle, read-only |
| `/home/or-chess/.local/share/or-chess` | Private application and audit data, read/write |
| `/home/or-chess/.local/share/or-chess/openrouter-budget.json` | Shared lifetime experiment budget ledger |
| `/home/or-chess/.config/or-chess/service.env` | Mode `0600` credential file, read by PID1 and hidden from the service filesystem |
| `/etc/systemd/system/or-chess.service` | Small system unit, executing as `or-chess:or-chess` |

The unit starts the application directly through the virtual environment's
`python -m uvicorn`, bypassing the original launcher's OpenAI credential loader.
It listens only on `127.0.0.1:8792` and trusts forwarded headers only from
`127.0.0.1`. The real OpenRouter key stays in the application environment; the
Codex child receives an ephemeral loopback-gateway token. OpenAI keys are
explicitly removed from the unit environment.

The private filesystem uses `ProtectHome=tmpfs`, selective binds, and a
read-only system. Resource limits cover the application and its descendants
together: 2 GiB memory, 128 tasks, 1,024 file descriptors, up to two logical
CPUs (`CPUQuota=200%`), and `Nice=10`. The service uses one web supervisor with
`ASTRA_MAX_WORKERS=2`, allowing two distinct game actions and tactical searches
to overlap. Model reasoning remains Max. These limits bound the experiment;
they are not a reservation of separate physical resources. Keep the complete
Codex bundle, including its helper executables and resources, in the bound
runtime directory.

The initial one-worker/50% CPU restriction is superseded by the September 14
two-worker trial. Its budget check uses a bounded cross-process lock wait:
30 seconds to acquire the lock, retrying every 50 ms, followed by the existing
provider-usage request. Inference is not held under that lock. The $50 baseline
and $5 admission reserve remain; reported usage can lag in-flight requests.
Local/default configurations remain at one worker and OpenRouter permits only
one or two. Keep a single web application process owning the data directory.

The native Linux concurrency audit exhausted the original 64-task cap before
either model request could start: systemd counts threads as tasks, and the two
Codex processes each start many threads. With 128 tasks, the audit completed
with a kernel-recorded peak of 96 and no task-limit rejections. This is a mock
provider test, not a peak-memory or sustained-load benchmark.

## Prepare and validate

Use the experimental checkout and its own virtual environment. The pinned
Python executable is
`/home/or-chess/.local/share/or-chess-runtime/python/cpython-3.12.14-linux-x86_64-gnu/bin/python3.12`;
Codex is
`/home/or-chess/.local/share/or-chess-runtime/codex/bin/codex`.
Installation alone does not establish their compatibility with the unit.

Create the configuration and data directories as `or-chess:or-chess`, mode
`0700`. Supply `OPENROUTER_API_KEY` through the protected environment file,
without printing it or copying the operator's entire login environment. The
unit supplies the fixed profile, persona, origin, runtime and data settings.
Do not override them in the environment file: environment-file values take
precedence over unit defaults, and the preflight rejects mismatches.
The selected daily-token override is a separate deployment setting; keep its
single `ASTRA_MAX_DAILY_TOKENS=200000000` entry in that private environment file.
After a controlled restart of only `or-chess.service`, verify the effective
configuration without displaying the file's credential contents. Preserve all
existing game and usage records using the update procedure below.

Transfer the existing experiment's budget ledger securely into the data
directory, owned by `or-chess` with mode `0600`. Preserve its initial usage
counters and key fingerprint. **Do not create a fresh baseline for deployment
or a disposable test.** Stop local paid experimentation before transferring
authority to the host; independently writable ledger copies cannot provide a
single coherent admission record. The live service and every paid operator
check use the same `ASTRA_OPENROUTER_BUDGET_PATH` supplied by the unit.

The lifetime allowance remains $50, including other use of the same key since
its saved baseline. New requests stop with $5 or less remaining. This is a
local usage guard; delayed provider accounting and work already in flight mean
it is not a provider-enforced hard cap. Missing, invalid or mismatched ledger
data fails the operator preflight without initializing a replacement.

After transferring the reviewed code and installing its pinned requirements:

```sh
sudo install -o root -g root -m 0644 deploy/or-chess.service /etc/systemd/system/or-chess.service
sudo systemd-analyze verify /etc/systemd/system/or-chess.service
sudo systemctl daemon-reload
sudo /home/or-chess/astra-chess/web-service/.venv/bin/python tools/run_openrouter_service_check.py preflight
sudo /home/or-chess/astra-chess/web-service/.venv/bin/python tools/run_openrouter_service_check.py wire
```

Run those commands from the experimental `web-service` directory. The helper
copies the installed unit's namespace, environment and resource properties
into a transient system unit. It refuses unit drop-ins, which need explicit
reconciliation before this simple parser can represent them accurately.

Every mode first runs the no-network preflight: account and paths, hidden
operator/production files, read-only code/runtime, writable SQLite state,
Python and exact Codex version, resource limits, persona, key presence and
existing private ledger binding. Output contains check results rather than
credential or ledger contents. The wire mode then exercises actual Codex
0.154.0 against the loopback gateway and a mocked upstream. It checks the
exact composed persona instructions and the seven canonical chess tools.
Neither mode makes a model request to OpenRouter. Wire reports are private
under `operator-checks/wire` in the data directory.

The separately authorized paid smoke test runs two model actions, including
thread resume, with disposable game data and the same shared budget ledger:

```sh
sudo /home/or-chess/astra-chess/web-service/.venv/bin/python tools/run_openrouter_service_check.py live --live
```

The launcher refuses this mode while `or-chess.service` is active, avoiding
concurrent players during the check. The explicit `--live` flag is required.
An audit passing on Windows does not replace these Linux namespace checks.

## Update an existing experimental deployment

Stage and test the candidate before modifying the running checkout. This
compaction update requires no Caddy change, hostname reactivation, Astra
application restart, credential change or database migration.

1. Record the current/candidate revisions and engine fingerprint. Inspect all
   experimental games, workers, replay builds and resource reservations with
   the [read-only inventory](../tools/ops/report_games.py). A saved error/idle
   game may remain; confirm no active response or compaction interval. An idle
   snapshot alone does not prevent a new player request.
2. Stop only `or-chess.service`, verify it is inactive and its worker control
   group is empty, then check the saved state again. Take the definitive private
   backup of the **whole** `/home/or-chess/.local/share/or-chess` directory now,
   outside both the live data directory and repository. Include SQLite companion
   files, game/query evidence, per-game Codex sessions, bridge recovery metadata
   and the existing OpenRouter budget ledger.
3. Update only the experimental checkout under its owning account. Preserve the
   runtime, virtual environment and private environment file unless separately
   reviewed changes require them. Verify the saved game's binding against the
   candidate on a private copy; retain its board, clocks, messages and thread ID.
   Run namespace preflight and mocked wire checks, with the focused compaction
   regressions, before starting only `or-chess.service`.
4. Verify health with the Arcturus Host header, HTTPS identity and saved-record
   preservation. Confirm the original Astra application and Caddy process
   identities remain unchanged. Keep a private audit of the backup, revisions,
   tests and preserved-record hashes. A stopped error-state game remains saved
   for the authorized retry; restarting the service does not itself retry it.

For a code rollback, retain current application data. Never restore an older
database, Codex session or budget ledger after accepting new moves or paid
requests without reconciling those writes. In particular, the spending baseline
and monotonic usage counters must not move backwards.

## Activate the hostname

After the checks pass, start the experimental application and verify its
loopback health before admitting public traffic:

```sh
sudo systemctl enable --now or-chess.service
curl --fail -H 'Host: arcturus.astraplayschess.com' http://127.0.0.1:8792/health
```

The new DNS record must reach the host. Preserve the current apex and `www`
routes when adding this separate Caddy site:

```caddyfile
arcturus.astraplayschess.com {
    reverse_proxy 127.0.0.1:8792
}
```

Validate the complete candidate proxy configuration before activation, save
the previous configuration, and preserve the existing mounted file's inode
when updating it. The installed Caddy 2.11.4 supports a `SIGUSR1` config reload
for its command-line configuration even with the administration API disabled;
the reload is performed by the reviewed activation helper. After reloading,
verify the new HTTPS hostname, the existing Astra hostname, and the Caddy
process state. Proxy changes are an operator step separate from installing the
experimental application unit.

The bounded [activation helper](../tools/ops/activate_arcturus_caddy.py) first
saves a root-private original and candidate, validates the candidate, and
checks the original HTTPS routes and experimental loopback service. Its default
mode makes no proxy change. Apply uses the reviewed original SHA-256:

```sh
sudo .venv/bin/python tools/ops/activate_arcturus_caddy.py
sudo .venv/bin/python tools/ops/activate_arcturus_caddy.py --apply --expected-config-sha256 HASH_FROM_PLAN
```

It preserves the individually mounted configuration inode and pins the verified
Caddy main process for `SIGUSR1`. Successful activation requires unchanged Caddy
and Astra application process identities, unchanged original route responses,
and valid HTTPS responses for the new host. A failed activation attempts to
restore the original bytes and reload them; private backups and reports remain
under `/var/lib/astra-caddy-activation`. The helper never operates the Astra
application unit or game database.

To stop experimental traffic, stop `or-chess.service`; retain its private
game records and budget ledger for recovery. Change only the new hostname's
proxy route if rolling back the experiment. Do not reset its spending baseline.

## Explicit context recovery

When the provider returns incoherent continuations despite correct host state,
inspect the private rollout and provider receipts first. A completed HTTP
request without a submitted move is different from a timeout or output limit.
Do not replace the model, reset its thread, or change a game's saved persona to
recover it.

The operator command `tools/ops/compact_player_context.py` can compact one
existing experimental thread. Test the proposed recovery on a private copy
before applying it to a live continuation. It makes a paid provider request
using that thread's existing conversation. Preserve a coherent backup, stop
only the experimental service, confirm all workers are idle, and run as its
service account with the normal protected provider environment:

```sh
python tools/ops/compact_player_context.py \
  --data-dir /home/or-chess/.local/share/or-chess \
  --game-id GAME_ID --expected-version SAVED_VERSION \
  --stopped-unit or-chess.service \
  --codex /home/or-chess/.local/share/or-chess-runtime/codex/bin/codex
```

The command refuses an active unit, remaining worker processes, stale game
version, missing thread, or non-OpenRouter game. It never starts a chess turn,
emits public chat, or changes game/clock documents. It preserves the thread ID,
saved prompt, reasoning/output settings and 250K automatic-compaction policy.
Provider usage is reserved and settled normally; receipts remain private.

Inspect the maintenance receipt and game hashes before restarting the
experimental service. Then validate a normal continuation. A successful
compaction alone does not prove that play has recovered. Never restore the
pre-compaction usage ledger over newly billed requests.
