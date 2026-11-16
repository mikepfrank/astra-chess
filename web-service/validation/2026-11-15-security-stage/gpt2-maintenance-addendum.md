# GPT-2 maintenance integration

November 15 local / November 16, 2026 UTC. Mike added both GPT-2 services to
the host maintenance scope and supplied the project at
`C:/Users/MikeFrank/Documents/=== FILES ===/-- AI --/GPT-2`. This is a read-only
deployment review and plan amendment. No services, admission, packages, user
sessions or budgets were changed; no generation, paid API calls or emails ran.
Mike expects little public traffic and is the private lab's only user; he will
check recent activity. Still verify quiescence at the actual maintenance window.

## Verified deployment and remaining preparation

Live checks at approximately 2026-11-16 01:51–01:54 UTC:

| Component | Verified baseline | Maintenance consequence |
|---|---|---|
| Public app | `gpt2-public.service`, enabled/running, PID 91398; frozen release `78ebbdc254249562187c06db8ec9c3cb7dd0e87b` at `/home/gpt-2/GPT-2-releases/seed-78ebbdc`; loopback 8899 | Preserve effective unit/drop-ins and explicit `PYTHONPATH`; do not deploy a development branch by accident. |
| Private lab | `gpt2-codex.service`, enabled/running, PID 196465; `/home/gpt-2/GPT-2-codex`; release metadata records `ed3eafa0236890013616fd941ea48b9091fcab99` | This deployed directory is not a usable Git checkout. Its main source hash matches the reviewed local file; preserve deployment metadata, not just a guessed branch. |
| Shared Python | `/home/gpt-2/.venvs/gpt2-public`, Python 3.12.12, `sys.base_prefix=/usr`, OpenSSL 3.2.2 | Unlike the chess private runtimes, both GPT-2 apps depend on OS Python/crypto. The pinned OS transaction changes their base runtime; test both after reboot. |
| Python packages | torch 2.14.1+cpu, transformers 5.18.0, tokenizers 0.23.2, httpx 0.28.1, certifi 2026.7.22 | Add the certifi fix to preparation. Preserve the model stack/decoding settings unless a separate finding requires a change. |
| Public readiness | HTTP 200; queue waiting 0/running false; result retention 600 seconds; generation deadline 300 seconds; maximum reply 256 tokens | This was an idle snapshot, not reserved downtime. Health is model-loaded readiness, not a generation test. |
| Lab readiness | Scoped health HTTP 200; 18 sessions recorded idle, 7 paused, 6 with `pending_human`; no pending continuation/continue/followup flags; zero sandbox containers | Idle does not mean all work has been consumed. Preserve pending inputs. Browser presence can schedule new actions; coordinate with Mike before stopping. |
| Docker image | `gpt2-codex-runtime:0.154.0`, image ID `sha256:9d9274de90e73ba2e215935f0dfbd09eb5c2fe248ba7a6b3052e45969de496fb` | Host RPM updates do not patch this image's Debian/Node/Python/Git/curl/bubblewrap/Codex contents. Complete a separate image dependency/security assessment before treating scope as complete. |
| Isolation | `gpt2-codex-network.service` enabled/active(exited); internal network `gpt2-codex-isolated`, `172.30.97.0/24`, gateway `172.30.97.1`; INPUT hook and `GPT2-CODEX-INPUT` chain present, allowing 8902 then dropping other traffic | Re-establish and test isolation after Docker/kernel changes, before restarting the lab. An active oneshot unit is not proof rules survived a Docker restart. |
| Preview | `gpt2-preview.service` inactive | Keep it inactive; avoid an extra model copy or bypassing memory guards. |

Public source SHA-256 (`src/gpt2_local/public_chat.py`):
`8ad720b67ea71faf03843fe1fbaed52af3d3d61312fe758b281c98ac4efee720`.
Lab source SHA-256 (`src/gpt2_local/codex_chat.py`):
`4566d1162eca5f6155da408a8671af03d0611d1f1bc84e19fb1dfba020beac37`.
Both match the reviewed local worktree files exactly. Lab release identity also
comes from `/var/lib/gpt2-codex-ops/files-release.json`; don't publish its entire
contents or private route/configuration values.

The [maintainer Critical certifi advisory](https://github.com/certifi/python-certifi/security/advisories/GHSA-6q48-6c7w-9gw2)
was rechecked: 2026.10.18 removes compromised emSign trust; the already selected
2026.10.23 candidate includes this fix. Prepare/test the shared GPT-2 environment
update and retain rollback material before activation. Do not mutate its live
venv while either app runs, or replace it with a chess venv. The GPT-2 container
assessment and shared-venv candidate are **not yet completed/staged** by this
documentation checkpoint. No new image vulnerability finding is asserted yet.

## Drain and backup sequence

1. Before the outage, finish the additional dependency/image assessment and
   prepare a narrowly scoped, validated GPT-2 maintenance gate/restoration
   procedure with saved prior unit/admission state. Existing preview/promotion
   scripts restore historical releases/configuration; they are not generic
   down/up scripts and must not be invoked blindly for host maintenance.
2. With Mike available, prevent new public **POST `/api/message` and
   `/api/regenerate`** submissions using the existing deployment's 503 JSON
   `accepted:false`, `Cache-Control: no-store`, and `Retry-After` convention.
   Keep result GET/SSE routes accessible. Wait for queue waiting/running to
   clear, then retain completed results for the full advertised **600 seconds**
   before stopping. This conservative lead-in can occur while chess is still
   available. Do not replace it with the chess helpers' 30-second quiet period.
   Continue checking the queue during retention, restart the idle interval if
   work reappears, and recheck just before stopping.
3. Coordinate the private lab with Mike: let any current action finish before
   pausing/disconnecting, because those controls cancel active work. Verify
   aggregate session/pending status and worker/container activity, then prevent
   new scheduling. Preserve pending human inputs; do not clear flags or edit
   live SQLite to manufacture quiescence. Lab health alone does not prove idle.
4. Stop GPT-2 apps only after those conditions hold, and preserve/temporarily
   disable their boot settings until deliberate post-reboot restoration. Record
   any network-unit changes separately. The public 180-second and lab 25-second
   stop timeouts are not graceful drain mechanisms: public results are in RAM,
   while the lab's stop hook forcibly removes its labeled sandbox containers.
5. Then use the chess drain helpers, verify all stopped/gated checkpoints, and
   make private backups plus the coordinated AWS snapshot. A proxy restart from
   the chess helpers must not interrupt GPT-2's result-retention lead-in.

Shared Caddy has a file bind mount: preserve its inode when changing config,
take `/run/lock/astra-caddy-config.lock`, validate and use the existing supported
SIGUSR1 configuration reload procedure. Binary replacement later requires a
restart. Preserve every chess/public/alias/private route and Astra's independent
new-game pause; never restore a historical whole Caddyfile over current routes.

Back up privately, preserving ownership/modes:

- Both actual GPT-2 release trees, effective unit/drop-ins, all installed
  launcher/network/cleanup/preflight/seccomp/sudoers files, and prior enablement.
- `/etc/gpt2-public.env` and `/etc/gpt2-codex.env` without logging contents. The
  latter includes credentials and the private URL capability.
- Shared venv/package inventory and `/home/gpt-2/.cache/gpt2-public/huggingface`
  model cache. Preserve pinned model revision, thread counts and sampling.
- Complete `/home/gpt-2/.local/share/gpt2-codex`, including consistent SQLite
  databases/companions, budget ledger, native threads, per-player Codex homes,
  workspaces, pending inputs, request IDs and scheduling metadata. Back up after
  writers stop; do not copy only a main SQLite file while WAL writes continue.
- `/var/lib/gpt2-codex-ops`, image identity/export for rollback, network/firewall
  configuration, and existing shared Caddy/TLS state.

Public chat archives live in each browser. A server backup cannot preserve them;
retain the origin and leave browser storage alone. Accepted jobs/results are
in-memory and must finish/be collected before stop. Do not auto-resubmit an
uncertain request. Do not instantiate lab application/store classes against
production data for an inventory: constructors perform recovery/schema writes.

## Startup and regression sequence

Keep admission gated through testing; restore previous boot settings only after
successful validation. Start public GPT-2 before the lab, verifying available
RAM and its 8-GiB preload guard rather than bypassing it. Both have independent
model runners despite sharing a read-only weight cache; check cold-start memory,
cgroups, swap/OOM counters and logs. Keep preview inactive.

- Validate new OS Python/OpenSSL, `pip check`, imports and package/model/source
  identities for both apps. Health checks must use correct Host/path values
  without exposing the private route in logs or this repository.
- Check public direct/HTTPS health, streaming support, aliases and result routes;
  later perform one short controlled generation with streaming and final-result
  retrieval. Verify existing browser archive preservation with Mike.
- After Docker updates/reboot, verify the internal bridge, 8902 gateway-only
  firewall access, loopback listeners, launcher privilege restrictions and
  scoped cleanup. Run no-key/mock sandbox tests for read-only root, dropped
  capabilities, custom seccomp/nested bubblewrap, resource limits and blocked
  metadata/SSH/other host ports. Preserve custom seccomp; replacing it with
  Docker defaults may break nested sandboxing.
- Lab scoped health is only an HTTP/application check. Verify preserved session,
  pending-input, thread and budget state; then use a designated test session for
  a user-coordinated short end-to-end sandbox/gateway/continuation check. Keep
  development test spending separate from the lab's existing daily allowance;
  don't reset the ledger or use an arbitrary real conversation as a test.
- Ungate only after tests pass. Restore the saved enablement/admission state;
  preserve new user data on rollback and avoid duplicate running hosts.

Host OS, shared GPT-2 Python, chess private Pythons, shared Caddy and the lab's
container image are separate update surfaces. The staged chess Codex bundle
does not upgrade the lab's container CLI; any CLI change needs its own protocol
and sandbox tests. Report status and return to the prompt after each agreed
major maintenance stage, as Mike requested.

## Source references

All paths below are relative to the supplied GPT-2 project:

- `.worktrees/gpt2-streaming/docs/{DEPLOYMENT,SEED-UPDATE,PRODUCTION-STREAMING}.md`
- `.worktrees/gpt2-streaming/src/gpt2_local/public_chat.py` (job/result state,
  health, stop), `runtime.py` (eager model load), `web/public.html` (browser archive)
- `.worktrees/gpt2-streaming/scripts/lightsail-preview.py` (POST gate, retention,
  locked Caddy updates); `lightsail-promote.py`/`lightsail-update.py` (deployment-specific)
- `.worktrees/gpt2-codex/HANDOFF.md`, `docs/CODEX-CHAT.md`
- `.worktrees/gpt2-codex/src/gpt2_local/{codex_chat,codex_chat_budget}.py`
- `.worktrees/gpt2-codex/deploy/codex-chat/` (units, Dockerfile, networking,
  launcher, cleanup, seccomp and installation)
