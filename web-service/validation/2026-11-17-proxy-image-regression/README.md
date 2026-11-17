# Proxy/container activation and gated regressions — complete, pause before reopen

Mike authorized the next update and regression stage after the completed Python
activation checkpoint. Keep public traffic gated and pause with results before
reopening. Codex migration remains deferred; Astra new-game admission stays
disabled. No new AWS task is needed for this stage.

Initial recheck: all four applications and both notification timers stopped and
boot-disabled with valid checkpoints; no failed units. Caddy old SHA256
`b7105518e3ed1c0761f232e44fc09345535533c9cb0abf0e12809416c7ac64d9`, candidate
`e8903acf0e525a53d9ad7c8d72b10bc63b71392ff39f9b7786c15d51a0639d01`.
Production Docker image tag remains old ID
`sha256:9d9274de90e73ba2e215935f0dfbd09eb5c2fe248ba7a6b3052e45969de496fb`;
candidate remains `sha256:cd4677302c525c03f02fefe65da2944ec07c6d4bb52aa0bf611a54dc504e71d1`.

Planned sequence: guarded Caddy replacement/restart preserving configuration and
TLS storage; root-owned lab launcher selects the exact new immutable image ID,
retaining the old tag/image/launcher; refresh versioned backup helper for the new
runtime/image layout; bounded disposable provider and sandbox checks while apps
remain stopped; start actual apps behind gates, test real generation, health,
mount visibility and routes, then pause before public reopening.

Initial checks already passed:

- Astra no-key protocol check: retained Codex 0.154.0, seven tools, strict config,
  thread startup and read-only/no-network sandbox. No model turn started.
- Both notifier dry runs: zero queued games, no email sent, delivery-state file
  bytes unchanged. Actual timers/jobs remained stopped.

Root-authored bounded chess integration helper staged as
`/home/ec2-user/chess-security-stage-20261116/ops/run_chess_security_integration.py`,
SHA256 `b029d837fb1e36c522e5d14d6512a4b34bdb1c44db9e7dbb05b8e41dc6e09793`.
Four local fixture tests passed. It preserves separate EnvironmentFile directives,
removes application lifecycle hooks, uses fresh operator-only game directories,
requires explicit paid-mode selection and enforces a bounded temporary unit.

## Activation complete

- Caddy 2.11.9 security binary activated and running under its actual systemd
  file binds. All maintenance gate checks pass. Configuration, new-game pause
  and seccomp bytes unchanged. Original binary retained as
  `/home/astra/.local/bin/caddy.pre-security-20261117`.
- Lab launcher now selects immutable candidate image ID `cd467730...` directly.
  Only its image token changed; permissions remain root:root 0755. Prior launcher
  retained as `/usr/local/libexec/gpt2-codex-sandbox.pre-security-20261117`.
  Old production image tag remains intact. Launcher SHA256 now
  `27bb9bcc0039037669acb41e5b129d682ebbd4c7376e8039fc5c011890de8f6e`.
- Versioned `backup_host_security_20261117.py` and verifier staged alongside
  historical tools. New stopped-state preflight passes against new image,
  immutable launcher, full GPT-2 `.venvs` parent and exact active/rollback
  layout. 26 tests cover guards and symlink-target coverage. No new full backup
  was created; retain the verified pre-runtime backup and snapshot.
- Both Astra and Arcturus completed two paid test move actions in fresh private
  operator games (one deterministic opponent move between them), with saved
  thread continuation and idle workers afterward. This is not a separate
  chat-only action/compaction test. Existing real player games were not used.

Private-lab diagnostic lessons, before real provider execution:

1. Its EnvironmentFile supplies settings, but production's `/bin/bash -lc`
   loads the account profile containing OPENAI_API_KEY. A probe must preserve
   that login-shell semantics; do not print/read the key into command text.
   First attempt refused before files/provider requests.
2. The deployed bridge calls the host callback with internal `_thread` during
   registration. An initial fixture rejected this; its separate development
   ledger has zero API admissions, production DB bytes unchanged, and no
   remaining container. The fixture must acknowledge this callback without
   writing a real chat row.
3. The fixed bridge instructions require emit_message first when Human addresses
   Codex. The revised test must honor this with an initial acknowledgement,
   then native arithmetic/file proof, then a final explicit message. Use a
   separate $1 development ledger and bounded request/action limits.

## Private bridge and actual gated application tests passed

The corrected v2 private-lab test passed using the promoted image and real
provider in **13.557 seconds**. Its separate development ledger records six
provider requests and **$0.023614**. The model sent two explicit comments,
completed the native arithmetic/workspace-file proof, and registered its thread
through the expected callback. During this isolated check, the production
private database remained byte-identical and its budget ledger was not written. Neither of
the earlier login-shell or `_thread` fixture failures made provider calls.
These were diagnostic fixture corrections, not failures of a real user session.

Paid chess diagnostic units finished and were cleaned up. **All four actual
applications are now active behind the retained maintenance gates, with boot
enablement still disabled. Both notification timers/jobs remain inactive.**
Do not reopen traffic or restore timers yet. An all-stopped backup guard will
now refuse, as intended; do not weaken it for running applications.

The public GPT-2 v3 probe completed one real generation with 10 output tokens
within its 16-token cap. HTTPS progress and completion events, stable canonical
result retrieval, and export/import passed in **28.007 seconds**; the queue
returned idle. Earlier fixture attempts were rejected before generation:
`Host: localhost` was not allowed, then the request lacked its required date.
The corrected fixture uses `Host: gpt2-chat.com`, the matching Origin and date.

The active-service v2 checker passed inside all four real mount namespaces:
Python 3.12.16, certifi 2026.10.23 and certificate-backed TLS construction;
OpenSSL 3.5.9 for chess and 3.5.8 for GPT-2. Direct board, health, config,
monitor shell, game-list and replay routes returned 200; unauthenticated
operator/game APIs returned the expected 401. The first public replays loaded
successfully. Maintenance gates, configuration bytes and process identities
were unchanged throughout these checks.

Private lab state matches the November 17 drain baseline: **18 idle sessions,
six preserved pending human inputs, zero children and zero containers**. The
first checker incorrectly assumed pending-input count must be zero. It was
corrected to the recorded baseline; no user input was cleared or edited.

The combined focused suite passed **all 55 tests**: 15 proxy/image activation,
26 versioned backup/coverage, four chess integration and ten GPT-2 integration.
Machine-readable reports are retained in this directory. These are focused
startup, sandbox, provider and generation regressions, not full games or an
authenticated monitor UI test. Chess live checks establish two move actions
and saved-thread continuation, not a separate chat-only/compaction test. Mail
delivery was not retested: notifier validation used dry runs, with no email sent.

Final host inspection at **20:35:50 UTC (14:35:50 America/Chicago)** confirmed
all four applications active/boot-disabled, zero automatic restarts and successful
unit results. Caddy is active/enabled; both notifier timers remain off/disabled.
There are no failed units and no app/Caddy error-priority journal entries since
20:29 UTC. The GPT-2 input subnet jump, allow-port-8902 then default-DROP chain,
IPv6-disabled internal network and ICC-disabled isolation remain correct.
See [active regressions](active-regression.json),
[final service status](final-service-status.json),
[public generation](public-generation.json) and
[private provider evidence](private-provider.json).

## Reopening checkpoint

Gated regressions are complete. Report results and return to the session prompt
as Mike requested. Keep traffic gated and original boot/timer settings held in
the maintenance checkpoints until his next continuation. After that approval,
run the reviewed `astra-up.sh` and `arcturus-up.sh` sequentially; they reopen
their routes and restore saved boot/timer settings after health checks. Then
run the GPT-2 maintenance helper's `reopen --validated`, preserving every shared
proxy route. Do not create a new checkpoint or discard the retained one.
Then verify primary/alias HTTPS, public GPT-2 result access, monitor/replay/export
routes, app/timer boot enablement, clean logs and notifier delivery state.
Astra's separate new-game restriction remains intentional; do not open it.

No further AWS action is needed. Retain both snapshots, the verified pre-runtime
archive, original venvs, Caddy binary, launcher and old Docker image. Codex
0.154.0 is unchanged; its potential migration remains a separate audit.
