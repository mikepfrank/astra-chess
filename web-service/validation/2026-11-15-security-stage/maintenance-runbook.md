# Security maintenance: activation and recovery runbook

Prepared November 15, 2026 (local date); live checks crossed into November 16 UTC.
This document is a procedure for later approved stages, **not a record of
updates already applied**. Mike approved the security plan and requested a
status report and return to the session prompt after each major stage.
Step 1 is preparation/staging only; stop before traffic gating or service changes.

## Verified live baseline

Both installed `--check` entrypoints passed, with no model calls or service
changes. Both services reported zero active responses, replay builds and
reserved tokens at this check. This is a snapshot, not an idle reservation.

| Unit | State / boot setting | PID / relevant restriction |
|---|---|---|
| `astra-chess.service` | active / enabled | 4149; 1 CPU, 2 GiB, 64 tasks |
| `or-chess.service` | active / enabled | 4313; 2 CPUs, 2 GiB, 128 tasks |
| `astra-caddy.service` | active / enabled | 422239; 0.25 CPU, 256 MiB, 64 tasks |
| `astra-game-notify.timer` | active / enabled | notifier inactive, last exit successful |
| `or-chess-game-notify.timer` | active / enabled | notifier inactive, last exit successful |
| `gpt2-codex.service` | active / enabled | Separate workload; coordinate its maintenance |
| `gpt2-public.service` | active / enabled | Separate workload; coordinate its maintenance |
| Docker / containerd | active | `docker ps` listed no running containers |

Mike has now included both GPT-2 services in scope. The
[GPT-2 addendum](gpt2-maintenance-addendum.md) records their verified releases,
shared OS-backed Python, Docker isolation and additional preparation required.
Empty `docker ps` is normal while the private lab is idle: it launches ephemeral
sandboxes for actions. Public accepted jobs/results are in RAM; its procedure
gates new POSTs, drains, and retains result access for 600 seconds before stop.
Lab stop timeout is 25 seconds and public is 3 minutes; neither is a drain.
Other interactive/user-managed work may exist beyond this inventory.

The installed Astra lifecycle helper is the reviewed version that accepts the
exact `new-games.caddy` import. SHA-256:
`7a831dc2747748b7f238a09411cf87e9974b756ad36ffa041a87c90f768bc8d5`.
Arcturus helper SHA-256:
`d52bed3259f430372acebb3e8785b67d7ec73dc2a206f41ebd86fdcc4a2bc59e`.
The absence of an Astra import literal in the Arcturus helper is expected: it
edits only its two flat hostname blocks and delegates full validation to Caddy.

The isolated Astra security branch is `codex/astra-security-20261115`, with
worktree `C:/Users/MikeFrank/Documents/ChatGPT/Chess/astra-security-worktree`.
It starts at the exact deployed `60bc178f3b442a2c333ed35dc304a99e17106b00`.
Its initial candidate source change is only the certifi requirements pin
`2026.7.22 -> 2026.10.23` and a security-advisory comment. All other dependency
pins and backend code remain at that live baseline. Record the candidate commit
and requirements hash after checkpointing; the candidate is for a later gated
release, not already deployed. Do not pull the hosted development branch head
to accomplish this dependency update. Root's isolated runtime fixture checks
used that exact live source baseline with the new Python/certifi environment;
the final requirements artifact must match the tested package set.

## Runtime placement and service sandbox constraints

Both applications and both notifiers have `ProtectHome=tmpfs`,
`ProtectSystem=strict`, `PrivateTmp=yes`, and `NoNewPrivileges=yes`.
Each app and its notifier bind the source repository and its own runtime tree
read-only. Their data/state directories are separately writable.

| Account | Source / existing venv | Bound private runtime tree |
|---|---|---|
| `astra` | `/home/astra/astra-chess/web-service/.venv` | `/home/astra/.local/share/astra-chess-runtime` |
| `or-chess` | `/home/or-chess/astra-chess/web-service/.venv` | `/home/or-chess/.local/share/or-chess-runtime` |

The app and notifier `ExecStart` commands both use that account's
`.venv/bin/python`. Both `.venv` paths are currently **ordinary directories**.
Astra's current `pyvenv.cfg` refers to the unversioned alias
`.../python/cpython-3.12-linux-x86_64-gnu/bin`; Arcturus refers to its explicit
`.../python/cpython-3.12.14-linux-x86_64-gnu/bin` directory.

The initial staging area is `/home/ec2-user/chess-security-stage-20261115`.
It is deliberately outside these service sandboxes. Do not point production
units or venv links at that staging area and do not move a staged venv intact:
venv scripts contain absolute interpreter paths.

Recommended final layout, after staging passes:

- Put each approved Python build in a new versioned directory under that
  account's existing bound `...-runtime/python/` tree.
- Create each replacement venv **at its final path** under that account's
  `...-runtime/venvs/security-20261115/`, using the explicit new interpreter.
  Reinstall from the reviewed pinned dependency manifest and verified artifacts.
- Verify ownership, path traversal, `pyvenv.cfg`, script shebangs and runtime
  library versions there; run candidate checks as the service account.
- Only after both apps and both notification timers/jobs are stopped, rename
  each old repository `.venv` to a unique rollback name and install `.venv` as
  a symlink to the tested final venv. Check for name collisions and unexpected
  existing symlinks before doing so. Record the actual rollback name.
- Never switch Astra's unversioned Python alias in place: it is part of the
  old venv's runtime resolution and is needed for reliable rollback.
- Retain the old runtime and old venv until the upgraded services are validated.

This layout should fit the existing read-only runtime binds without loosening
the service sandbox. Still test the real sandbox before promotion. A later
Codex upgrade is different: Astra's app bind explicitly names
`/home/astra/.codex/packages/standalone/releases/0.154.0-x86_64-unknown-linux-musl`.
New Codex paths need coordinated unit/config changes plus `daemon-reload` and
protocol tests. Arcturus's Codex sits inside its existing bound runtime tree.
Do not combine an unvalidated Codex change with the urgent Python/OS rollout.

Caddy binds **the executable file**, Caddyfile and optional new-game fragment
read-only. Replacing `/home/astra/.local/bin/caddy` does not update the old
process or its file bind. A controlled Caddy restart is required after replacing
the binary; keep its previous binary as a uniquely named rollback artifact.

## Preservation requirements

Retain these together; do not print or export credential contents into logs:

- Both `/home/astra/astra-chess` and `/home/or-chess/astra-chess` repositories,
  their exact deployed commits, ignored venvs and local runtime links.
- `/home/astra/.local/share/astra-chess` and
  `/home/or-chess/.local/share/or-chess`: databases and companions, game journals,
  replay/query artifacts, per-game Codex homes, profiles and clocks. The
  Arcturus `openrouter-budget.json` v3 ledger must not be reset or downgraded.
- Both bound runtime trees and Astra's complete selected Codex release bundle.
- `/home/astra/.config/astra-chess/service.env`, `operator.env`, and
  `/home/or-chess/.config/or-chess/service.env` privately, with ownership/modes.
- Both monitor configuration directories under `.config/` and both monitor
  state directories under `.local/state/`; preserve pending/delivered-message
  state to avoid unintentional duplicate email alerts.
- `/home/astra/.config/astra-chess/Caddyfile`, `new-games.caddy`, and all
  `/home/astra/.local/share/astra-caddy` TLS/storage state.
- `/home/astra/.local/share/astra-chess/new-games-paused` and Caddy's
  `/etc/systemd/system/astra-caddy.service.d/30-new-game-admission.conf`.
  **Never invoke new-game admission `open` as part of this maintenance.**
- Effective service/timer units, all drop-ins, enabled-unit symlinks and
  `/home/ec2-user/{astra,arcturus}-{down,up}.sh` wrappers.
- `/var/lib/astra-chess-ops` and `/var/lib/arcturus-chess-ops`, including their
  active maintenance checkpoints. The shared proxy lock is
  `/run/lock/astra-caddy-config.lock`; its transient file need not survive reboot.
- All GPT-2 source/runtime/cache, private session/workspace/budget databases,
  environment files, Docker image/isolation and deployment state enumerated in
  the [GPT-2 preservation list](gpt2-maintenance-addendum.md). Browser-owned
  public chat archives are not part of a server snapshot.

Store filesystem backups in a root-owned mode-0700 directory outside those
source trees, for example under `/var/backups/chess-security/`. Preserve modes,
owners, ACLs and extended attributes; test the archive listing and hashes.
Use an offline SQLite integrity check as the owning account once writers are
stopped. A full Lightsail snapshot supplements these explicit backups. For a
stopped-instance snapshot, coordinate shutdown/start in AWS with Mike; otherwise
ensure the chess backup is already consistent and separately restorable and
coordinate every other workload's snapshot expectations. Do not assume a live
whole-host snapshot gives every application's consistent in-memory state.

## Later-stage operator sequence

These are **future actions**, not actions performed by this preparation task.
Recheck pinned packages and private artifact hashes before proceeding.

1. **Preparation checkpoint:** Finish candidate tests and share the results
   with Mike. Agree the next window and the AWS snapshot workflow, including
   the GPT-2 workloads. Complete the newly added shared GPT-2 certifi candidate,
   container dependency assessment and safe admission/drain procedure before
   the outage; these were not covered by the chess staging tests. Pause at the
   session prompt as requested.
2. **Drain/backup checkpoint:** Run the current read-only checks again. Follow
   the GPT-2 addendum: public POST gate, drain and 600-second result retention
   while chess stays available; coordinate the private lab's idle/pause state
   without cancelling active work. Stop GPT-2 and retain boot/admission state.
   Then run `~/astra-down.sh` and `~/arcturus-down.sh` sequentially. Each waits for
   30 continuous quiet seconds; neither forcibly cancels an AI turn. Require
   success and saved `stopped` checkpoints. Verify both apps and jobs inactive,
   app/timers disabled, and all public chess hostnames serving their expected
   maintenance marker. Take private backups and coordinate the AWS snapshot.
   Report status and pause. Avoid waiting at an unplanned checkpoint with users
   already gated; arrange Mike's availability first.
3. **OS checkpoint:** Apply only the reviewed pinned release transaction
   (`dnf upgrade --releasever=2023.12.20261112`) and reboot. Do not reboot if
   draining or backup verification failed. After reconnecting, verify the
   booted kernel, SSH, failed units, package/advisory status, and proxy maintenance
   gates. All four apps must remain disabled until deliberate restoration.
   Check Docker/network isolation before the lab can start; OS Python changes
   affect both GPT-2 apps through their shared venv. Report and pause.
4. **Runtime/validation checkpoint:** Promote the tested final Python/venv and
   Caddy artifacts in controlled stages while the apps/timers remain gated and
   stopped. Validate Caddy using the `astra` identity and actual sandbox paths.
   Restart only the shared proxy when needed and confirm maintenance remains
   intact. Run model-free and mocked-provider tests; then the approved small
   paid model checks in disposable private state. Report and pause before
   public reopening if that remains a separate agreed checkpoint. Include the
   GPT-2 addendum's sequential startup, memory, model-generation and sandbox/
   gateway tests; preserve its separate daily ledger and pending inputs.
5. **Reopen checkpoint:** Run the `up` helpers sequentially. They start the app,
   check private health and **immediately reopen public traffic** after that
   basic check. They do not wait for additional regression tests. Therefore
   finish richer tests before invoking `up`, using isolated test state/ports or
   carefully starting an app behind the gate without reopening. Starting an
   app does not itself re-enable it at boot; retain the saved helper checkpoint.
   Verify all primary/alias HTTPS routes, Arcturus normal admission, Astra's
   continuing new-game denial, existing-game access, monitor/replay/export
   behavior, app/timer enablement and logs. Restore GPT-2 admission/enablement
   only after its own checks pass. Report final versions and pause.
6. **Codex checkpoint, separately:** Audit/promote a newer CLI only after its
   schema, tools, continuation, sandbox, reasoning and accounting tests pass.
   Use another coordinated drain if necessary. Preserve models/personas and
   settings. A version string allowlist change alone is insufficient.

## Tests and test-launcher cautions

- Both service trees have unit/fixture tests. Candidate code should be the
  **deployed revisions**, not newer local source that has never been activated.
- Initial staging fixtures may run in disposable transient units with no API
  credentials, `PrivateNetwork=yes`, `Nice=10`, at most one CPU and 2 GiB RAM.
  Give them their own temporary/writeable directories and no live data writes.
- Test replacement Python imports, TLS certificate handling, SQLite integrity,
  replay/export formatting and HTTP streaming under the new runtime.
- Run notifier `--dry-run` as its owner inside a sandbox matching its actual
  notifier unit. This mode sends no mail and does not update delivery state;
  do not run the ordinary notifier command as a test.
- `run_openrouter_service_check.py` refuses any application drop-ins and its
  paid live mode requires the production Arcturus app to be stopped. It checks
  only the primary unit's properties; preserve that safeguard.
- Astra's `run_service_check.py` reads only its principal unit, while Astra
  currently also has `20-monitor.conf`. Reconcile the effective properties
  before relying on it as an exact sandbox test. It also hardcodes Codex
  0.154.0 for live checks.
- Caddy's admin API remains disabled, and live protocols remain HTTP/1.1 and
  HTTP/2. Candidate tests must not contact ACME or modify live TLS storage.

## Recovery rules

Do not delete maintenance checkpoints to bypass a refusal. A failed drain
leaves the service running behind maintenance; rerun `down` to continue waiting
or use its matching `up` helper to restore prior admission. An `up` failure can
leave a valid checkpoint for a subsequent retry.

Before reopening, a runtime rollback restores the prior `.venv` directory/link
and prior Caddy binary/config changes under the shared proxy lock, then repeats
health checks. Restore only the files this operation changed; never overwrite
the entire shared Caddyfile with an old copy that erases another site's state.

If an OS rollback requires the snapshot, keep the failed host's writable model
workers and notifiers disabled before activating a restored host. Never allow
both copies to accept games or send notifications. Preserve current credentials
and explicitly coordinate IP/firewall/DNS recovery in AWS.

After public traffic resumes, prefer code/runtime rollback while preserving
current data. Do not restore an older game database or budget ledger over new
player actions merely to undo a software update.
