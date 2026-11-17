# Maintenance progress — services resumed; private updates remain pending

## November 17: preparation rechecked; no downtime authorized tonight

Mike authorized preparation only before bed. Post-OS candidate integrity and
isolated checks passed: 1,457 application tests, six expected Windows-only
skips, Caddy protocol fixtures and candidate-image sandbox probes. All production
processes/settings/routes remain unchanged and available. See
[the current checkpoint](../2026-11-17-security-recheck/README.md) and
[next-window instructions](../2026-11-17-security-recheck/next-window.md).
Do not begin draining or deployment until Mike returns and resumes the work.

## November 16 evening: services reopened at Mike's request

All four apps and both notification timers are active/boot-enabled again;
reviewed lifecycle helpers archived the old maintenance checkpoints. Focused
checks passed. Private runtime/certifi/Caddy/image candidates remain inactive.
See [the current resumption record](../2026-11-16-security-resume/README.md).
Future activation requires a fresh coordinated drain; the stopped-state
instructions below are historical and must not be assumed current.

## November 16 evening: snapshot, OS upgrade and reboot complete

Mike confirmed the stopped-instance snapshot and same-host restart. The pinned
OS transaction completed successfully and the host rebooted onto the new
kernel. All apps and notifier timers remain stopped/disabled; maintenance gates,
private lab isolation and recovery checkpoints verified. **Current pause is
before runtime/certifi/Caddy/image activation and regression testing.** See
[the OS checkpoint](../2026-11-16-security-os/README.md) for versions, evidence,
warnings resolved, and the exact next stage. The snapshot instructions below
are historical, completed prerequisites; do not repeat them on resumption.

## Completed drain/backup checkpoint, November 16, 23:30 UTC

**Pause here for Mike's AWS snapshot.** All four application services remain
stopped/boot-disabled; both chess notifier timers remain stopped/disabled.
Shared Caddy is running with the maintenance gates. No OS package installation,
runtime/image activation or reboot has occurred. The next separately approved
stage is the pinned OS update and reboot after snapshot confirmation.

The backup helper exited successfully with `complete:true` after checksums and
fsync of recovery files, final manifest and parent directories:

- Root-private directory: `/var/backups/chess-security/20261116T232418Z`.
- `applications.tar`: 11,821,199,360 bytes, 101,167 archive members;
  SHA-256 `63bdf64b98f3e7346bec06538dfb6eb3156b516c2a520ab39443a72cc652a789`.
- `gpt2-codex-image.tar`: 715,110,912 bytes;
  SHA-256 `8a099cbdf1fcf210a0b65be03815048e0be428e949ad8712c17e382dd2b73234`.
- [Sanitized backup result](backup-result.json) records artifact checksums and
  all 821 successful owner-run SQLite quick checks: Astra 299, Arcturus 438,
  GPT-2 84. No application constructors, model calls or emails were used.
- Independent archive verification compared all three primary databases, all
  three stopped maintenance checkpoints and the current Caddyfile against their
  archived copies: seven matching files. Docker archive manifest retains
  `gpt2-codex-runtime:0.154.0` and the expected old image ID. Backup directory
  mode 0700 and every file mode 0600, root-owned, were verified.

The actual recovery archives, inventories and private manifests remain on-host.
Only sanitized outcome metadata is committed; no credentials, chat content,
private capability URLs or raw network capture were saved in this repository.

Mike confirmed all lab tabs closed, but a later strict check still observed
polling. Inspection identified only Windows/Chrome request categories (discarding
raw packets/URLs/cookies) and found no lab tab in the visible Chrome window or
this chat's browser panel. Mike then located and closed the remaining page;
the original strict 60-second quiet conditions passed without weakening them.
An embedded browser in another chat can be easy to overlook; paused pages
continue polling. No client connection or AI action was forcibly interrupted.

## AWS handoff and next stage

Current local `ssh lightsail` resolves to `ec2-user@16.145.194.176`; use the
current instance, not an older host. This IP lookup does **not** establish that
an AWS static IP is attached; confirm that in Lightsail before stop/start.

AWS [recommends stopping an instance for snapshot consistency](https://aws.amazon.com/lightsail/faq/).
With the static-IP attachment confirmed, Mike can stop the instance, create a
manual snapshot (for example `pre-security-2026-11-16`), wait until ready, and
start the **same** instance again. See the official
[snapshot procedure](https://docs.aws.amazon.com/lightsail/latest/userguide/lightsail-how-to-create-a-snapshot-of-your-instance.html)
and [stop/start IP behavior](https://docs.aws.amazon.com/lightsail/latest/userguide/lightsail-how-to-start-stop-or-restart-your-instance-virtual-private-server.html).
Stopping the host also quiesces other workloads not covered by these app backups.
The four apps and notification timers should stay disabled after startup; do
not invoke reopening helpers yet. Reconnect, verify saved maintenance state and
snapshot identity, then proceed to the OS stage and its separate prompt pause.

## Earlier 23:25 UTC update (superseded by completion above)

Mike located and closed the remaining lab page. The unchanged strict quiet
requirements then passed; the lab gate/stop completed. Astra and Arcturus each
completed their own 30-second quiet drain and stopped successfully. All four
apps are inactive/boot-disabled; both notifier timers are inactive/disabled,
both notifier jobs inactive, and Caddy remains active after the two expected
chess-helper proxy restarts. All three chess hostnames and the public GPT-2
generation route return maintenance 503 with their expected markers.

Backup preflight passed. The private backup is currently being created at
`/var/backups/chess-security/20261116T232418Z`; it is not complete until the final
manifest says `complete:true` and the helper exits successfully. Read-only
SQLite quick checks passed for 299 Astra, 438 Arcturus and 84 GPT-2 databases.
The latest backup helper also includes the maintenance helper source directory;
its SHA-256 is `dba364ed5ab800ab3843d45710a9b9ae36237b82d848609d253027fe8b36f5e7`.
No OS/package/runtime/image promotion or reboot has occurred. Return to the
prompt after backup verification for Mike's AWS snapshot.

## Earlier partial checkpoint (superseded by the update above)

Verified November 16, 2026 at 19:53 UTC (1:53 p.m. America/Chicago).
The promised downtime heads-up was given before any gate. Mike will handle
the AWS snapshot, but **the all-services backup/snapshot checkpoint is not
ready yet**. No OS/package/runtime/image activation or reboot has occurred.

| Service | Current verified state | Recovery checkpoint |
|---|---|---|
| Public GPT-2 | Stopped, boot-disabled; PID 0 | GPT-2 phase `stopped`; generation POST gate remains installed |
| Private GPT-2/Codex lab | Running/enabled, PID 196465; not gated | GPT-2 phase `prepared` |
| Astra chess | Running/enabled, PID 4149 | No new chess shutdown performed |
| Arcturus chess | Running/enabled, PID 4313 | No new chess shutdown performed |
| Shared Caddy | Running/enabled, original PID 422239 | GPT-2 public gate applied by SIGUSR1; no proxy restart |

Public GPT-2 completed **600 continuous idle seconds** of result retention,
then cleanly stopped/disabled. No generation was interrupted. Its result/page
GET routes now return upstream-unavailable responses until startup; its two
generation POST routes return the expected maintenance 503.

Private shutdown was safely refused before any gate/stop because an established
Caddy/backend connection continued exchanging traffic. Mike had confirmed
idle and tabs paused/closed, but a paused lab tab still polls every two seconds
and sends presence heartbeats. A follow-up asks him to fully close all private
lab tabs, and that confirmation is still pending at this checkpoint. No forced
interrupt, direct session edit or weaker guard was used. Pending human inputs
are preserved. Keep chess running until this dependency is resolved.

## Exact resumption point

- Durable root-private checkpoint: `/var/lib/gpt2-maintenance-ops/maintenance.json`.
  Do not delete/recreate it or repeat the public gate/retention unnecessarily.
- Initial helper `/home/ec2-user/chess-security-stage-20261116/ops/gpt2_maintenance.py`
  (SHA-256 `e45d926dfa706aea0d75ad6115dce5957a6ef3ed96516cc01dba18adeede565a`)
  performed prepare, public gate, refused lab gate and successful public stop.
- Subsequent reviewed helper is staged separately at
  `/home/ec2-user/chess-security-stage-20261116/ops/gpt2_maintenance-v2.py`,
  SHA-256 `80018c27bb074cd66782b9313346b5033bce808cc0a1058c543b92585b1f7912`.
  It has the same checkpoint/gate format, 28 passing tests, flushed progress,
  explicit closed-tab wording, and a 300-second lab quiet deadline to allow
  connection expiry plus 60 continuous quiet seconds. No safety condition was
  relaxed. Use `sudo python3 -u -I -B .../gpt2_maintenance-v2.py` for next commands.
- Once Mike confirms all lab tabs closed, run `gate-lab --owner-idle`, then
  `stop-lab`, inspecting each result. If traffic/work remains, do not force it.
- Then sequential `~/astra-down.sh`, `~/arcturus-down.sh`, requiring both stopped
  checkpoints and disabled app/timers. Recheck current identities/activity first.
- Final backup helper is staged at
  `/home/ec2-user/chess-security-stage-20261116/ops/backup_host_security.py`,
  SHA-256 `63f96f146faf66e5c421eee44ebe57a06fbc6c683c3c49cc7b04d2296b2138fc`.
  It has 11 passing admission-guard tests and independent review. Run `--check`
  then the actual helper only after all four drains. It has **not** created a
  backup yet. Required main SQLite files and nonzero per-owner check counts
  prevent an empty data directory from reporting a clean check.
- Return to Mike with the backup result and request his fresh Lightsail snapshot
  before installing any OS updates. Later runtime activation instructions are
  in [the GPT-2 checklist](gpt2-activation-checklist.md) and the original runbook.

If the window must be abandoned, deliberately start public GPT-2 behind its gate,
verify readiness, then use the helper's validated reopening path while the lab
is healthy; preserve pending inputs and restore recorded boot/admission state.
Do not leave a partial maintenance state undisclosed or delete its checkpoint.

Preparation artifacts/tests are committed at `06897ce` on
`codex/openrouter-chess`; subsequent guard-documentation refinements and this
progress checkpoint are recorded in the following commit. All software
candidates remain inactive. No paid model calls or email tests have run.
