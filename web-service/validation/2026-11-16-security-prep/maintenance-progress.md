# Maintenance progress — waiting for private lab tabs to close

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
