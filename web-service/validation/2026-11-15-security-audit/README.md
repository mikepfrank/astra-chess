# Lightsail security-update survey — November 15, 2026

Status: **survey complete; application awaits Mike's approval**. No packages,
application code, service configuration, enablement, or running processes were
changed. DNF metadata caches were refreshed; an upgrade transaction was resolved
with `--assumeno` and aborted before downloading/installing packages. No model
calls or email tests were made.

Scope: the host reached by `ssh lightsail`, OS-managed packages, shared Caddy,
and the private runtimes/dependencies used by Astra and Arcturus. Other accounts'
private software and container images were not comprehensively audited. This is
a version/advisory survey, not an intrusion investigation or penetration test.

## Evidence and baseline

- [Host package inventory, security notices and transaction preview](host-package-survey.json)
- [Installed-to-candidate OS package table](os-update-candidates.csv)
- [Both private Python environments, Caddy build metadata and Codex binaries](chess-runtime-survey.json)

The CSV lists `check-update` candidates before dependency resolution, excluding
the separate obsoletes listing. The full `upgrade --assumeno` result in the JSON
is authoritative for the actual proposed transaction and dependency additions.

The host is Amazon Linux **2023.9.20251208**, running kernel
**6.1.158-180.294.amzn2023.x86_64**. It has approximately 16 GiB RAM and
250 GiB free on the root filesystem; no failed systemd units were reported.
Applications were idle at the game-inventory check; that must be checked again
before maintenance. Active process IDs stayed Astra **4149**, Arcturus **4313**,
and Caddy **422239**. Both notifier timers were active/enabled. Both primary
sites and the old Arcturus alias returned HTTP 200 with `{"ok":true}` at `/health`.
Both private virtual environments passed `pip check`.

Live repositories: Astra `60bc178f3b442a2c333ed35dc304a99e17106b00`;
Arcturus `a98784cdafacbe5e6616cc55b0e94a34e8056bf2`.
Do not replace Astra's deployed revision with the newer local branch head:
the October static rollout intentionally excluded prepared backend changes.

Amazon Linux pins repositories to the installed release. An ordinary check
against the old release did not reveal this backlog. Explicitly querying
**2023.12.20261112**, after refreshing metadata, found **325 applicable security
notices: 1 Critical, 197 Important, 111 Medium, 16 Low**. These are advisory
counts, not distinct CVE counts or proof of 325 exploitable attack paths.
The full preview proposes **252 package upgrades, 22 installs, 395 MB download**,
with no removals listed. The install set includes the replacement kernel and
new dependencies. See [AWS deterministic updates](https://docs.aws.amazon.com/linux/al2023/ug/deterministic-upgrades.html)
and the [target release notes](https://docs.aws.amazon.com/linux/al2023/release-notes/relnotes-2023.12.20261112.html).

## Recommended updates

Priorities below distinguish vendor severity from our operational scheduling.
Version targets are this survey's snapshot; recheck advisories before execution.
Exact RPM release suffixes are retained in the CSV.

| Priority | Component | Installed | Proposed target | Reason / application impact |
|---|---|---|---|---|
| Critical | AWS SSM Agent | 3.3.3050.0 | 3.3.5828.0 | AWS Critical advisory; update through the OS transaction. Agent is running; registration/IAM exposure was not audited. |
| Critical | certifi, both chess venvs | 2026.7.22 | 2026.10.23 | Remove compromised CA trust. Rebuild both venvs and restart their apps. |
| High priority | OS release and kernel | AL2023.9.20251208; kernel 6.1.158-180.294 | AL2023.12.20261112; kernel 6.1.190-237.442 | Apply complete reviewed distribution transaction, then reboot. Retain the 6.1 kernel series. |
| High priority | System crypto, SSH and core libraries | OpenSSL 3.2.2; OpenSSH 8.7p1; systemd 252.23-10; glibc 2.34-231.0.1; curl 8.11.1 | OpenSSL 3.5.8-1.amzn2023.0.4; OpenSSH 9.9p1-16.amzn2023.0.1; systemd 252.23-15; glibc 2.34-231.amzn2023.0.6; curl 8.21.0-5.amzn2023.0.5 | Distribution backports and security/reliability updates; also update sudo, CA certificates, OS Python, Git, rsync and other packages in the preview. |
| High priority | Host container stack | Docker 25.0.13; containerd 2.1.5; runc 1.3.3 | Docker 25.0.18; containerd 2.3.7; runc 1.4.3 | Security updates. Docker/containerd are active; coordinate non-chess workloads before reboot. Container images themselves are outside this survey. |
| High priority | Both private Python runtimes | Python 3.12.14, OpenSSL 3.5.8, Expat 2.8.4, SQLite 3.53.1 | Python 3.12.16 with patched bundled libraries; require OpenSSL >=3.5.9 and verify Expat fixes | Separate from OS Python. Stage a new versioned runtime/venv; preserve Python 3.12. Candidate archive's embedded library versions still need inspection. |
| High priority | Shared Caddy and its embedded Go runtime | Caddy 2.11.4, Go 1.26.3, x/net 0.55.0 | Caddy 2.11.9 built with patched Go 1.26.11 or 1.27.4; audit module versions | Public HTTP/2 server is exposed to relevant Go denial-of-service defects. A standalone-binary replacement and proxy restart are required. Candidate build has not yet been validated. |
| Staged compatibility work | Both Codex standalone bundles | 0.154.0 | Audit 0.169.0 before promotion | Later Linux sandbox/trust hardening and bundled dependency fixes. Harness rejects unreviewed versions; this needs protocol/continuation/sandbox tests and reviewed allowlist changes. No specific Critical Codex CVE is asserted. |
| Maintenance | pip in both private venvs | 25.0.1 | 26.3 | Installation-time archive/path-handling advisories. Upgrade within the staged environments before subsequent package maintenance. |

### Highest-priority advisory evidence

- **SSM:** [ALAS2023-2026-3149](https://alas.aws.amazon.com/AL2023/ALAS2023-2026-3149.html)
  is Critical. CVE-2026-89049 concerns authenticated remote-host port-forward
  destination validation and possible access to instance-role credentials.
  An active SSM process alone does not prove an attacker has the required
  Session Manager authorization. The proposed version supersedes the full
  advisory's fixed package, 3.3.5226.0.
- **certifi:** [GHSA-6q48-6c7w-9gw2](https://github.com/certifi/python-certifi/security/advisories/GHSA-6q48-6c7w-9gw2)
  is maintainer-rated Critical. Compromised emSign intermediate keys make the
  old trust bundle unsafe against an on-path attacker. The fix starts at
  2026.10.18; use the current 2026.10.23 bundle. Both environments contain the
  affected version and make outbound HTTPS requests.
- **Python:** [3.12.16](https://www.python.org/downloads/release/python-31216/)
  adds SSL-level distrust for compromised eMudhra keys (CVE-2026-115557),
  Expat updates and other security fixes. Astral publishes a compatible
  [20261110 standalone build](https://github.com/astral-sh/python-build-standalone/releases/tag/20261110).
  Its actual linked libraries must be checked before promotion. OpenSSL
  [3.5 security advisories](https://openssl-library.org/news/vulnerabilities-3.5/index.html)
  include fixes after 3.5.8; not all DTLS/QUIC findings apply to these Python clients.
- **Caddy/Go:** [Go HTTP/2 HPACK crash, CVE-2026-97032](https://github.com/golang/go/issues/81867),
  [HTTP/2 memory exhaustion](https://github.com/golang/go/issues/81857), and
  [HTTP/2 CPU exhaustion](https://github.com/golang/go/issues/81742) affect the
  installed Go/x/net versions. Live Caddy enables `h1 h2`; HTTP/3 is disabled.
  Caddy also has a [reverse-proxy header fix](https://github.com/caddyserver/caddy/security/advisories/GHSA-8qx7-j2v2-x6q5).
  [Caddy 2.11.9](https://github.com/caddyserver/caddy/releases/tag/v2.11.9) predates
  the November 10 [Go security releases](https://go.dev/doc/devel/release):
  do not assume its stock binary includes those later fixes. Inspect or rebuild
  the candidate with patched Go. Its x/net 0.60.0 fixes the listed HTTP/2 issues;
  newer HTML-parser advisories need reachability review before a module override.
- **Codex:** the [official changelog](https://learn.chatgpt.com/docs/changelog)
  records 0.169.0 on November 13. Since 0.154.0, releases include Linux sandbox
  executable-integrity and ripgrep-mask hardening and project-trust fixes.
  These justify a separately tested upgrade, not an unconditional binary swap.

### Selected OS applicability qualifications

- [OpenSSH ALAS2023-2026-1604](https://alas.aws.amazon.com/AL2023/ALAS2023-2026-1604.html)
  concerns legacy `scp -O` run as root under particular options; it is not
  evidence of unauthenticated sshd compromise.
- [glibc ALAS2023-2026-3396](https://alas.aws.amazon.com/AL2023/ALAS2023-2026-3396.html)
  requires hardlink protection disabled plus a suitable privileged executable.
  This host has `fs.protected_hardlinks = 1`, mitigating that specific path.
- [sudo ALAS2023-2026-3156](https://alas.aws.amazon.com/AL2023/ALAS2023-2026-3156.html)
  requires particular time-bounded sudoers rules. Those rules were not audited.
- [systemd ALAS2023-2026-3224](https://alas.aws.amazon.com/AL2023/ALAS2023-2026-3224.html)
  addresses DNSSEC trust-anchor rollover; it lists no CVE. An Important notice
  is not necessarily an arbitrary-code-execution vulnerability.
- [containerd ALAS2023-2026-3273](https://alas.aws.amazon.com/AL2023/ALAS2023-2026-3273.html)
  and [Docker ALAS2023-2026-3391](https://alas.aws.amazon.com/AL2023/ALAS2023-2026-3391.html)
  include conditional malicious-image/checkpoint/build-cache issues. Chess runs
  under systemd, but the container daemons are active and may support other
  workloads; those workloads need an inventory before the reboot.

### Optional framework updates

Version-specific PyPI advisory metadata reported no known entries for the other
16 installed Python packages. That is not proof that their code has no flaws.
Routine upgrades available include FastAPI 0.141.1 -> 0.163.1, Starlette 1.6.0 ->
1.10.0, Uvicorn 0.52.4 -> 0.54.0, Pydantic 2.13.5 -> 2.14.3, pydantic_core
2.46.5 -> 2.50.4, AnyIO 4.15.1 -> 4.16.0, Click 8.5.0 -> 8.5.1, idna 3.19 ->
3.20, annotated-doc 0.0.5 -> 0.0.6, and typing-inspection 0.4.4 -> 0.4.5.
Defer these unless required for a security fix, to reduce unrelated regression
risk. Do not replace the project's own chess engine. SQLite's replacement
bundle merits validation, but no service-reachable Critical SQLite issue was
established in this survey.

## Proposed execution plan, after approval

1. **Stage and test before downtime.** Pin artifacts and verify signatures or
   checksums. Build separate versioned Python environments with reviewed pins;
   inspect their OpenSSL/Expat/SQLite versions. Inspect/rebuild and test the
   Caddy candidate. Run model-free tests against the exact deployed application
   baselines. Do not mutate an active venv or deploy unrelated branch changes.
   Audit Codex 0.169.0 separately so its integration work does not block urgent
   OS/trust/proxy fixes.
2. **Coordinate a maintenance window.** Recheck all workloads, including
   non-chess Docker and Telegram/new-project services affected by host reboot.
   Validate the installed lifecycle helpers' current Caddy-import support.
   Use the Astra and Arcturus `down` wrappers sequentially to gate traffic,
   stop notifier admission and wait for 30 continuous quiet seconds, including
   model/chat/compaction/replay work and child processes. No forced cancellation
   of a live game turn. Keep apps disabled at boot until deliberate restoration.
3. **Back up the quiescent host.** Save private game databases and companions,
   journals, Codex homes, queries/replays, credentials, notifier state, budget
   ledger, effective units/drop-ins, proxy config/imports/TLS state, runtime
   versions and lifecycle checkpoints. Take a fresh Lightsail snapshot and
   verify recovery access. Snapshot storage may incur the ordinary AWS charge.
   Keep any rollback clone's notifiers/model workers disabled until cutover.
4. **Apply the pinned OS transaction and reboot.** Use the reviewed
   `dnf upgrade --releasever=2023.12.20261112` transaction. Verify the replacement
   kernel actually boots, SSH works, filesystems and systemd are healthy, and
   the security backlog clears. The wrappers leave chess behind maintenance.
5. **Activate tested private runtimes and Caddy, in stages.** Confirm the OS
   baseline first, then switch each tested runtime, allowing rollback to its
   previous binary/environment. Review both app and notifier units' read-only
   bind paths; the notifiers use the same venv Python. A versioned Codex path
   change also needs coordinated unit updates and `daemon-reload`. Validate
   Caddy under its real `astra` identity
   and service sandbox; check all domains/redirects and private health routes.
   Preserve the disabled Caddy admin API and current protocol policy.
6. **Regression-test before reopening.** Run model-free/native mocked-provider
   tests, then a small real-provider smoke test for each AI in disposable,
   private test state. These last tests incur API charges and are included in
   the requested maintenance approval; do not run full games or alter a player's
   saved game. Verify move legality, board/clock updates, chat/notes separation,
   High/Max move selection versus High chat, retry/resume, private/public
   replays, PGN/RTF exports, account recovery routes, operator monitors, and
   notifier dry-run/deduplication inside each notifier's actual sandbox. Run
   these richer tests in isolated state before invoking the `up` helpers:
   those helpers reopen traffic automatically after basic health checks and
   do not provide a pause for additional testing. Do not send real emails as part of this plan
   without a separate explicit request.
7. **Restore each app and notifier with its `up` helper; verify again.** Preserve
   Astra's intentional new-game pause while allowing existing games. Confirm
   Arcturus's normal admission, authentication, games, TLS, quotas and notification
   timers. Review logs and resource use during controlled smoke work. Stop and
   roll back a failed stage before users resume.
8. **Finish the Codex migration when its contract tests pass.** Review app-server
   schema/events, tool exposure, Linux sandboxing, interruption/continuation,
   reasoning settings and usage accounting. Update allowlists/check helpers only
   with supporting tests; replace the complete standalone bundle. Reuse the
   drain/backup/smoke procedure for promotion. Preserve model/persona/settings.
9. **Record versions, results and follow-up policy.** Save the post-update
   manifests and remaining advisory findings. Prefer future regular explicit
   release checks; unattended Codex/framework upgrades are unsuitable for this
   integration without its compatibility tests. No recurring job was configured
   during this survey.

The main outage should be limited to draining, backups/snapshot, applying the
prepared changes, reboot and validation. Actual duration depends on snapshot and
regression results; no precise downtime estimate is promised before staging.

## Preservation and test details

Astra's pause is represented by
`/home/astra/.config/astra-chess/new-games.caddy`,
`/etc/systemd/system/astra-caddy.service.d/30-new-game-admission.conf`, and
`/home/astra/.local/share/astra-chess/new-games-paused`. Live import and marker
presence were confirmed. **Do not call admission `open` during this maintenance.**
Preserve the Arcturus UTC monthly-budget v3 ledger and all per-game Codex homes,
profiles, reasoning settings, prompt/tool fingerprints and saved clocks.

Use existing full fixture suites and Arcturus native audits:
`audit_model_wire.py`, `audit_chat_reasoning.py`, `audit_tool_visibility.py`,
`audit_private_notes.py`, `audit_parallel_codex.py`, `audit_compaction_wire.py`,
`audit_compaction_lifecycle.py`, `audit_reasoning_roundtrip.py`.
Astra has `tests/audit_codex_protocol.py` and service-namespace checks.
Several check helpers hardcode Codex 0.154.0; adapt/review those for candidates.
Compare constructed test sandboxes against effective live unit drop-ins.

Source references: [Arcturus lifecycle](../../tools/ops/ARCTURUS-SERVICE-LIFECYCLE.md),
[current Arcturus handoff](../../HANDOFF.md), and the separate hosted worktree's
`web-service/tools/ops/SERVICE-LIFECYCLE.md`, `NEW-GAME-ADMISSION.md`, and
`web-service/docs/CODEX-INTEGRATION.md`.

If a rollback is needed after user writes resume, roll back code/runtime while
preserving current data. Never restore an old game database or spending ledger
over newly written state merely to undo a software update.
