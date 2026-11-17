# Handoff: Arcturus development worktree

## November 17: proxy/image and gated regressions complete — PAUSE BEFORE REOPEN

Mike authorized the next update/regression stage. Caddy 2.11.9 is activated;
the private GPT-2 launcher selects immutable image
`sha256:cd4677302c525c03f02fefe65da2944ec07c6d4bb52aa0bf611a54dc504e71d1`.
Original binary, launcher and old image/tag remain for rollback. Configuration,
Astra new-game restriction and sandbox policy are preserved. Versioned November
17 backup helpers now cover GPT-2's venv symlink targets and new image/launcher;
their stopped-state preflight passed. No new full archive was created.

Both chess services passed two paid disposable move actions with thread
continuation; notifier dry runs sent no mail and preserved delivery state.
The corrected isolated private-lab test passed in 13.557 seconds: six provider
requests, $0.023614 charged to its separate development ledger, two explicit
comments, native workspace proof and thread callback. Production private DB
bytes were unchanged and its budget ledger was not written. Earlier login-shell
and `_thread` fixture corrections made zero provider calls.

**All four applications are active behind maintenance gates and boot-disabled;
both notification timers/jobs remain inactive. Pause before reopening.**
Real-process runtime/TLS checks passed, as did direct health/board/config/monitor/
game-list/replay routes and expected unauthenticated API denial. Public GPT-2
completed one 16-token-cap generation (10 output tokens), HTTPS progress/complete
streaming, stable result retrieval and export/import in 28.007 seconds; queue
returned idle. Private lab retains its baseline 18 idle sessions and six pending
human inputs, with zero children/containers; no pending inputs were edited.
All 55 focused helper tests passed. Configuration, gates and process identities
were preserved during the checks. Final 20:35:50 UTC (14:35:50 Chicago) inspection
found zero automatic app restarts, no failed units and no app/Caddy error-priority
journal entries since 20:29 UTC; GPT-2 firewall/network isolation remains intact.

No new snapshot is needed. After Mike's next explicit continuation, use reviewed
`astra-up.sh` / `arcturus-up.sh` to restore their routes/boot/timers, then GPT-2
maintenance `reopen --validated`. Verify public HTTPS, enablement and logs.
Never unlock Astra's separate October 11 new-game restriction. Codex 0.154.0
remains unchanged and its possible migration is a separate future audit.
Tests cover two move actions/thread continuation, not full games, authenticated
monitor interaction or real mail delivery; notifier checks were dry runs only.

See [current stage and evidence](web-service/validation/2026-11-17-proxy-image-regression/README.md).

## November 17: Python/certificate environments promoted — paused before proxy/image

Mike confirmed fresh pre-runtime snapshot and restart. Post-boot OS/kernel,
maintenance gates, stopped checkpoints and GPT-2 isolation checks passed.
Both chess venv paths now select their tested private Python 3.12.16/OpenSSL
3.5.9 environments; both GPT-2 apps select the tested shared certifi venv on OS
Python 3.12.16/OpenSSL 3.5.8. All four now use certifi 2026.10.23. Original venv
directories are retained with `pre-security-20261117` names; Astra's old Python
alias is unchanged. Exact certifi-only source commits are deployed: Astra
`995a587063bb6a7719f53965f85a4dacfeac5f9c`, Arcturus
`fa184aba3a212fb542d59ef3592c7484b3a96caa` (separate pushed security branches).

24 helper tests, four runtime sandbox checks, both full chess preflights and
Arcturus's mock-provider wire audit passed. No real model requests/emails.
**All apps/timers remain stopped and boot-disabled behind maintenance gates.**
Caddy and GPT-2 container image are still the prior versions. Pause here as
requested; next promote those two artifacts, then real-process/generation/
provider/notifier regressions before the separate reopening checkpoint.
Codex migration remains deferred; never unlock Astra's new-game pause.

See [activation details, rollback paths and evidence](web-service/validation/2026-11-17-python-activation/README.md).
Before any subsequent backup, refresh the versioned backup helper bundle to
include GPT-2's now-symlinked candidate/rollback directories and the new image
identity; the existing pre-runtime archive/snapshot remain valid and retained.

## November 17: drain and backup complete — paused for Mike's fresh snapshot

Mike resumed the flow and confirmed all private lab tabs closed. All four apps
and both chess notifier timers are now stopped/boot-disabled with fresh retained
maintenance checkpoints and verified HTTPS gates. Public GPT-2's full 600-second
retention, private lab's strict quiet check and both chess quiet intervals passed.
No guard bypass, pending-input deletion or runtime candidate activation.

Fresh root-private backup `/var/backups/chess-security/20261117T174804Z` completed,
hashed and fsynced successfully: 821 SQLite checks passed; 101,160 archive members.
The new read-only verifier passed on-host: private modes/ownership, artifact
sizes, seven key archived files versus stopped live files, Docker tag/config ID.
19 local backup guard/verifier tests passed. See
[checkpoint and evidence](web-service/validation/2026-11-17-runtime-window/maintenance-progress.md).

**Pause for Mike's AWS console step:** stop `MPF_Lightsail_16GB`, create
`MPF_Lightsail_16GB-pre-runtime-2026-11-17`, wait for completion, start the same
instance and confirm SSH. Static IPv4 is `16.145.194.176`. Do not invoke up helpers
yet; preserve prior snapshot/backup. After confirmation verify stopped checkpoints
and staged artifacts survived boot, then proceed with controlled runtime updates
and regressions, retaining major-stage pauses. Do not repeat the OS upgrade or
unlock Astra's independent new-game pause. Codex migration remains separate.

## November 17: preparation recheck complete — leave services running

Mike authorized **step 1 only** before bed; deployment/downtime remains paused
until he returns and resumes the sequence. All inactive candidate integrity and
post-OS tests passed: chess 279+591 passes with six expected Windows-only skips,
GPT-2 206+381 passes, isolated Caddy protocol/TLS tests, and candidate-image
no-key sandbox/schema/initialization. Total 1,457 passes, six skips, no failures.
Original reports preserved, no candidate rebuilds or promotions. Five app/proxy
PIDs unchanged (4105/4317/3982/4373/5194), zero restarts, health 200, timers
active/enabled, no failed units. No real inference/API calls/test emails ran.

Mike's own post-OS tests passed for private GPT-2, public GPT-2 and Arcturus.
Astra is online but new games remain intentionally disabled; do not unlock it.
See [recheck evidence](web-service/validation/2026-11-17-security-recheck/README.md)
and [the next-window checklist](web-service/validation/2026-11-17-security-recheck/next-window.md).
Pending security candidates are still inactive; real production namespace,
gateway/provider and final deployment checks remain for a new coordinated
maintenance window. Codex 0.169.0 still needs its separate compatibility audit.

## November 16 evening: all four services resumed; private updates still pending

Mike requested resumption after the OS upgrade, accepting troubleshooting as
needed. Astra, Arcturus, public GPT-2 and private GPT-2/Codex are now live and
boot-enabled; both chess notification timers restored and jobs have succeeded.
The reviewed up/reopen helpers archived all active maintenance checkpoints.
Public HTTPS checks pass from the host and laptop. Chess sandbox preflights,
a short GPT-2 generation/stream/result/export test and the original container's
no-key sandbox/initialization checks passed. No paid provider tests ran.
Astra's independent new-game pause remains intact.

**Pending:** staged private Python/certifi, Caddy and container-image updates
were not activated; Codex promotion also remains separate. These tasks need a
new coordinated drain now that services are live. Do not reuse the historical
stopped-service assumption/checkpoints below. Keep the snapshot/backup.
See [resumption details and evidence](web-service/validation/2026-11-16-security-resume/README.md).

## November 16: OS upgrade/reboot verified — paused before runtime activation

Mike confirmed snapshot `MPF_Lightsail_16GB-pre-security-2026-11-16`, attached
static IP 16.145.194.176, and restart of the same host. The pinned OS upgrade
completed successfully (252 upgrades, 22 installs), followed by reboot onto
AL2023 `2023.12.20261112`, kernel `6.1.190-237.442.amzn2023.x86_64`. All 274
reviewed RPM versions are installed; refreshed package/security checks find no
remaining updates for that pinned OS release. No failed units; SSH works.
Maintenance gates and stopped/disabled apps/timers persisted. GPT-2 network,
firewall, image, launcher/seccomp and saved checkpoints verified; Astra's
independent new-game pause remains. **Pause here at Mike's requested OS-stage
checkpoint.** Private Python/certifi/Caddy/image candidates remain inactive;
regression tests and reopening are next, using the runbook and GPT-2 checklist.
No model calls/emails or AWS automatic-snapshot configuration changes occurred.
DNF cleared download-only RPMs after success; retain their checksum manifest.
See [OS checkpoint and evidence](web-service/validation/2026-11-16-security-os/README.md).

## November 16: drain/backups complete — pause for AWS snapshot

Mike found and closed the remaining lab page. The strict private-lab quiet
check then passed, followed by clean lab/Astra/Arcturus shutdowns. All four
apps are now inactive/boot-disabled; notifier timers paused/disabled. Shared
Caddy is active with maintenance gates. Private backup at
`/var/backups/chess-security/20261116T232418Z` completed successfully: 821 SQLite
quick checks passed, 11.8-GB application archive plus 715-MB Docker rollback
archive hashed/flushed, seven critical archived files independently matched,
and root-only modes/image tag verified. No OS/software activation or reboot yet.
**Stop here for Mike's AWS snapshot.** He will create/confirm it in his console;
recommend stopped-instance snapshot with static-IP attachment checked first.
`ssh lightsail` currently targets 16.145.194.176. After he starts the same host,
verify all four apps/timers remain disabled/gated before the OS update stage.
See [the current progress record](web-service/validation/2026-11-16-security-prep/maintenance-progress.md).

## November 16: public GPT-2 stopped; awaiting private lab tab closure

**Current maintenance state:** public GPT-2 completed its 600-second retention
and is stopped/boot-disabled behind its generation gate. Private GPT-2 lab,
Astra, Arcturus and shared proxy remain running on original PIDs/software.
Private lab shutdown safely refused because a paused browser tab still polls;
Mike was asked to fully close all private lab tabs. Await confirmation and
successful actual quiescence before stopping it. No OS update/reboot/runtime
activation has occurred; no final backups/snapshot yet. Do not call `prepare`
again or discard the existing GPT-2 checkpoint.

[Exact state, helper paths and next commands](web-service/validation/2026-11-16-security-prep/maintenance-progress.md).
Use the separately staged `gpt2_maintenance-v2.py` for subsequent operations;
it adds clear closed-tab wording and progress without relaxing idle checks.
Next finish private/chess drains and durable backups, then return to the prompt
for Mike's AWS snapshot before installation. Keep the chess sites available
while waiting for the private lab closure.

## November 16: expanded preparation ready; downtime heads-up required

Mike resumed maintenance, will take/confirm the AWS snapshot himself, and
confirmed the private GPT-2 lab is idle with tabs closed/paused. He requested a
heads-up just before actual downtime and retains the pause after each major step.
[Today's preparation checkpoint](web-service/validation/2026-11-16-security-prep/README.md)
records inactive GPT-2 Python/image candidates, tests, live unchanged checks,
and the new reviewed lifecycle/backup helpers. The GPT-2 helper's `check` and
`prepare` passed; its root-private checkpoint exists but routes remain ungated
at this entry. All four services are still running on their old software.

Next: announce downtime, drain GPT-2 with full public result retention and
private idle checks, drain both chess services, make durable private backups,
then **return to prompt for the AWS snapshot before installing updates**.
Use any subsequent drain record as authoritative about actual current state.

## November 15: GPT-2 added to host maintenance scope

Mike supplied `C:/Users/MikeFrank/Documents/=== FILES ===/-- AI --/GPT-2` and
authorized including its public and private services. Read-only project/live
review is recorded in the
[GPT-2 maintenance addendum](web-service/validation/2026-11-15-security-stage/gpt2-maintenance-addendum.md).
Both services are healthy; public queue was empty, private sessions idle but
some retain pending human inputs. Mike is checking activity; don't treat this
snapshot as a reserved outage. Nothing was stopped or upgraded in this review.

Public GPT-2 requires a POST admission gate, queue drain and 600 seconds of
result retention before stop. Schedule that before chess helpers restart the
shared proxy. The private lab launches ephemeral Docker sandboxes, so empty
`docker ps` does not imply Docker is unused. Preserve its chat/thread/workspace/
budget state and verify isolation after Docker/reboot. Both share an OS-backed
Python 3.12 venv with old certifi; add its fix and assess the lab container's
separate dependencies before declaring preparation complete for the expanded
scope. Those extra candidates/tests are not yet staged. The updated runbook
retains Mike's required prompt checkpoint after every major maintenance step.

## November 15: security preparation complete — pause requested

Mike approved the maintenance plan, including critical/high-priority updates,
snapshot, reboot and small paid AI tests, but requested a status report and
return to the session prompt after **each major step**. Step 1 preparation is
complete. [Checkpoint and artifact inventory](web-service/validation/2026-11-15-security-stage/README.md).
**Stop before draining or activating anything until Mike resumes the next step.**

274 signed OS RPMs are downloaded; installed OS packages are unchanged. New
Python 3.12.16/OpenSSL 3.5.9/Expat 2.10.0 environments, certifi 2026.10.23 and
pip 26.3 are staged, including final unused paths inside both private runtime
trees. Active venvs and aliases remain unchanged. Astra 282-test and Arcturus
594-test suites passed with three Windows-only skips each. Patched Caddy 2.11.9
with Go 1.27.4, x/net 0.62.0 and compress 1.20.4 passed proxy tests/configuration
comparison. Codex 0.169.0 passed limited startup/schema probes but still needs
full integration audit; production stays on 0.154.0. Both sites remain healthy
on their original processes. No downtime, real model calls or emails occurred.

Next coordinate the AWS snapshot window and other workloads: GPT-2 public/Codex
services and additional shared-proxy hostnames are also active. Follow the
[runbook](web-service/validation/2026-11-15-security-stage/maintenance-runbook.md)
for drain/backup/snapshot and another prompt checkpoint before OS installation.
Preserve Astra's new-game pause. The separate local `astra-security-worktree`
branch `codex/astra-security-20261115` is based on live `60bc178`, with only the
certifi pin update; do not deploy unrelated newer hosted branch changes.

## November 15: host security-update survey

The migrated host and both chess services were inspected read-only. The
[survey, update table and staged maintenance plan](web-service/validation/2026-11-15-security-audit/README.md)
record 325 applicable OS security notices (one Critical), a Critical private
Python trust-bundle update, and private runtime/proxy/Codex maintenance needs.
Both sites were healthy at survey completion. The plan was subsequently approved;
the staging checkpoint above records execution progress and the required pauses.

Use the saved manifests as a baseline, then recheck before maintenance. The live
Astra revision is `60bc178`; preserve its intentional pause on new games and
Caddy import/drop-in. Its newer local branch head includes unactivated backend
work. Arcturus is live at `a98784c`. Codex remains 0.154.0 in both services and a
new CLI requires contract tests before allowlisting. Preserve all game state,
notifier state and the Arcturus monthly budget ledger.

## October 3: migration lifecycle scripts

**Installed at `1cc6b2a`.** `arcturus-down.sh` / `arcturus-up.sh`, adapted from the hosted Astra
reference at `90e778d`, for Mike's larger Lightsail instance migration.
**Do not run actual down/up during preparation.** Mike will invoke them around
his instance snapshot/cutover. Astra is already stopped/disabled behind its own
maintenance checkpoint; preserve that state. Arcturus remains running.

See [operator instructions](web-service/tools/ops/ARCTURUS-SERVICE-LIFECYCLE.md)
and the [validation record](web-service/validation/2026-10-03-service-lifecycle.md)
for current installation/check status. Both Arcturus hostnames are gated, only
their blocks restored into the current shared Caddyfile, and Caddy still runs
as Astra. Independent checkpoint `/var/lib/arcturus-chess-ops` and operation
lock, shared `/run/lock/astra-caddy-config.lock`. Preserve the full game,
continuation, credential, notifier and v3 budget state in the snapshot; no
budget or game migration/reset is needed. Keep the old host stopped after cutover.

Both wrappers are installed mode 0700 in `/home/ec2-user/`. All 95 focused tests
passed on Windows and Linux. System-Python `--check` passed for each installed
wrapper; actual two-domain maintenance configuration validated without applying
it. No services were restarted or boot/timer settings changed. Arcturus PID
83871 and Caddy PID 466253 stayed unchanged; Astra is still stopped. Caddyfile,
Astra checkpoint, monthly ledger and Arcturus private app/notifier configuration
and notifier state were unchanged by installation/checks. Actual down/up remain
uninvoked, awaiting Mike. No Arcturus maintenance checkpoint exists yet.

## September 23: monthly budget and beta label

**Live at `d21680d`, September 23, 20:27 UTC.** The OpenRouter guard changes from a $50 lifetime experiment allowance
to $100 per UTC calendar month. All spend since the original experiment baseline
is carried into the migration month; future months use provider UTC monthly
counters. The full $100 is available (old $5 reserve removed). Shared-key scope,
credential pinning and serialized checks remain. Arcturus's board badge/title
now say BETA/Beta. See the [validation record](web-service/validation/2026-09-23-monthly-budget.md)
for current test/deployment status and rollback considerations. Do not restore
an old version 2 budget over a version 3 ledger after model work has resumed.

Migration verified at 20:29 UTC: September spend $21.610289586, remaining
$78.389710414; original credential/baselines retained. Linux: 353 checks, 352
passed and one Windows-only skip; local budget 43/43 and bridge/gateway/service
85/85 passed, plus native mocked-provider audits. All 35 games and private data
survived the gated restart; only the subsequent budget record was intentionally
migrated. Public health and beta assets verified. No gameplay pause is pending.

## September 20: request metadata for future incidents

**Live at `67bd854`, September 20, 22:53 UTC.** Lightweight private OpenRouter request measurements record fixed category
counts, canonical JSON sizes/fingerprints, reasoning text/summary/encrypted
byte totals, request timing and available cached/reasoning token breakdowns.
These augment existing provider receipts after final gateway transformations;
they retain no additional conversation text and change no model parameters.
See the [validation record](web-service/validation/2026-09-20-request-metadata.md)
for schema, limitations, test and deployment status. Jordan's earlier incident
cannot retroactively acquire these measurements.

Linux passed 309 of 310 checks (one Windows-only skip), plus native reasoning,
tool-visibility and persisted-request metadata audits. All 32 game documents,
database/private files and configuration survived the gated restart unchanged;
original Astra/Caddy processes stayed running. No gameplay pause is pending.

## September 20: bounded deliberation guidance

**Live at `3108148`, September 20, 15:06 UTC.** A short generic instruction asks
Arcturus to keep independent assessment in quiet positions brief, then register
a candidate and consult the tactical engine.
The existing trusted developer policy delivers it to new and resumed Arcturus
games without changing saved persona/base prompt/tool identity or runtime
resource settings. The earlier reported stalled game had recovered through
move 15 after automatic compaction; its five length failures occurred before a
fresh tactical query. See the service handoff and
[validation record](web-service/validation/2026-09-20-deliberation-guidance.md)
for current deployment status and evidence.

Linux passed 305 of 306 checks (one Windows-only skip); native Codex audits
verified the full policy on actual mocked-provider requests, including resumed
games. The gated activation preserved all 32 games and private state, with
original Astra/Caddy processes unchanged. No gameplay pause is pending.

## September 18: conditional public-comment reminder

**Live at `31f3270`, September 18, 15:21 UTC / 10:21 CDT.** A durable reminder covers Arcturus actions that save ordinary assistant
notes without publishing a `chess_comment`. The gateway appends the reminder as
the final developer input on subsequent model requests, including resumed games.
Only a successfully stored public comment clears it; a trailing private final
note in that same action does not rearm it. Older games with notes receive a
bootstrap reminder. No extra model turn is scheduled. See the
[validation record](web-service/validation/2026-09-18-comment-reminder.md) for
current verification and activation status. Saved prompts/tool hashes stay fixed.
Linux passed 305 of 306 checks (one Windows-only skip), plus the native reasoning,
long-output and conditional-reminder audits. The gated restart preserved all 29
games, database/private-file digests, configuration, units and notification timers.
Original Astra/Caddy stayed running; no maintenance or gameplay pause is pending.

## September 17: explicit comments and optional note export

Live backend `bf5b746`: Arcturus sends sidebar text only through `chess_comment`.
Ordinary assistant messages remain private notes in the durable game record and
native Codex conversation. Export chat offers an unchecked notes option after
game completion; included notes use distinct muted italic formatting. Existing
visible messages and replay artifacts are preserved. The communication policy
applies on every start/resume without changing saved model/persona/tool identity.

All 28 stored games and private state survived the gated restart unchanged;
original Astra and Caddy stayed running. Linux passed 298/299 checks (one skip)
and native mocked-provider reasoning, tool-visibility and note-continuity audits.
See [web-service/HANDOFF.md](web-service/HANDOFF.md) and the linked September 17
validation record. A refresh loads the new export dialog; the next model action
already uses the new rule. The older checkpoints below are historical.

Mike subsequently authorized one historical test conversion: his completed
81-ply game now has 99 public messages and 222 optionally exported internal notes.
The backed-up September 17 repair preserved all moves/text/order and the other
27 games, with no process restart or paid call. See the September 17 service
validation note for evidence and the private recovery location.

## September 15 evening: current live checkpoint

Arcturus is live at code `aab2df8`: private head-to-head points appear near the
board heading and in the AI's next game context; Export chat in the footer
downloads a formatted RTF with accepted moves and all messages interleaved by
recorded ply. Historical completed games initialize scores without a migration.
The larger 65,536-token tool-output budget also remains active. See
[web-service/HANDOFF.md](web-service/HANDOFF.md) for current checks, deployment
receipts and one recorded intermittent native startup-ordering observation.
Latest activation preserved all 21 saved games and left original Astra/Caddy
processes, private configuration and timers unchanged. All work is on
`codex/openrouter-chess`; the checkpoints below are historical.

## September 15: monitor pages and move-thinking preference

The requested update is live at `3e2bb62` as of September 15, 17:43 UTC: the private monitor
defaults to ten rows with size/page controls, and current v4 Arcturus games have
a persisted High/Max selector for future move responses. Chat stays High; a
running response keeps its captured effort. Existing game identity, clocks and
threads are preserved. See [web-service/HANDOFF.md](web-service/HANDOFF.md) and
[the UI validation record](web-service/validation/2026-09-15-ui-controls.md) for
activation status. The compact selector is live at static revision `672b21c`,
using one row plus a short help line. It was fast-forwarded without restarting
any service; Python runtime code remains the tested `3e2bb62` release.
September 14 checkpoints below are historical.

## Current branch checkpoint — September 14, 2026

This checkout is **`openrouter-worktree` on `codex/openrouter-chess`**, the
Arcturus/OpenRouter hosted-service experiment. Start with
[web-service/HANDOFF.md](web-service/HANDOFF.md) for current status and
[OPENROUTER-EXPERIMENT.md](web-service/OPENROUTER-EXPERIMENT.md) for architecture,
profiles, limits and isolation. The September 9 local-chess handoff below is
historical context, not the current deployment or an instruction to resume play.

At the read-only **22:44:55 UTC** checkpoint, the clean Lightsail application
checkout was `ce668680f429290a07b3615774288895fa248ce1`; both applications returned
HTTP 200 health and both notification timers were active. Documentation commits
after that deployed revision do not imply another live code activation.

Current Arcturus v4 games use **High for chat / Max for moves**, 32,768 output
tokens per provider response, 250K context compaction, two concurrent game
workers, 200M daily tokens, and the existing $50 experiment spending guard.
OpenRouter chat has a 600-second host allowance and a bounded 900-second bridge
ceiling without chess-clock charges. The repeated hard-60-second chat failure
was fixed; the live retry completed in 206.8 seconds, and Mike confirmed seeing
the reply. High is not a guarantee of low latency. No game pause or deployment
is pending from that repair.

**Next work is not yet selected.** Image attachments via a `+` chat button were
assessed as feasible, but Mike explicitly deferred implementation. Preserve the
[feature proposal and compatibility questions](web-service/docs/FUTURE-FEATURES.md).
General password-recovery email remains disabled; working operator notifications
and successful isolated SES delivery tests are separate from that feature.

Resume in this worktree only; leave `../hosted-worktree`, the parent `main`
checkout and original Astra service/game data alone. Read fresh game/worker
state before an operational action; an unfinished game is not proof that its
player is online. Never reset a saved game, thread, clock or budget to repair a
provider failure. Use the service's owned persistence and tools, not the local
experiment's `resume_chess.py`, for hosted games. Keep credentials, raw private
logs and game records outside Git. See the service handoff for verification,
operator-tool and recovery pointers.

## Historical local experiment handoff — September 9, 2026

Prepared September 9, 2026, from the surviving conversation context and the
repository at `125c669`. This is a dated orientation, not live game state.
Check the current checkout and journals before relying on its status snapshot.
Detailed specifications and historical evidence are linked rather than copied.

## Purpose and the latest direction from Mike

Michael P. Frank (Mike), a reversible-computing researcher and AI enthusiast,
is exploring how an LLM's deliberation can work with a small, understandable
chess engine. Astra proposes plans and questions, directs bounded searches,
inspects candidate positions and opponent counterplay, and chooses the move.
The engine supplies systematic tactical search and inspectable evidence.

The original experiment began with unaided play against Chess.com bots, added
explicit prospective board visualization, then introduced a from-scratch Python
engine. Mike watches the games and values the commentary explaining decisions
and concrete examples of where tooling helped or failed. He also shares the
replays publicly. The player/model label is **Astra**, while **Codex** names the
agent harness. Preserve historical PGN identities; presentation overrides and
thinking levels belong in replay metadata.

The conversation after the first Li game established these priorities:

- **Keep the engine relatively simple and understandable.** Mike explicitly
  declined pursuing a reconstruction of classical Stockfish. The discussion of
  Stockfish techniques was hypothetical, not an implementation request.
- Explore better questions, selective depth/time allocation, future-position
  searches, and focused goals. Stronger autonomous engine play is not the sole
  objective; the interaction between deliberation and search is the experiment.
- No external chess engines, opening books, endgame tablebases, game-database
  lookup for move selection, or large self-training exercise are part of this
  method. The engine uses rules and authored evaluation/search code. Astra's
  general chess knowledge comes from the language model; the whole combined
  system should not be described as having learned chess solely from the rules.
- Keep experimental evaluation terms and extensions optional, measure their
  cost, and explain proposed changes. The recent wins/draw did not require
  enabling every optional feature. Preserve engine behavior during a trial.
- Keep all substantive tools, notes, records and reusable artifacts in the repo,
  so continuity does not depend on this chat, a local memory service, or a
  particular desktop installation.

**Current request:** prepare this handoff for a separate development session.
Mike intends to explore spin-offs, potentially an interactive web service where
people can play against Astra, eventually on an AWS host or other Codex CLI
environment. That work should proceed separately from the original playing
session. No service architecture or deployment has been selected or implemented
as part of this handoff.

## Read the existing sources in this order

| Need | Source |
| --- | --- |
| Project instructions and artifact locations | [AGENTS.md](AGENTS.md) |
| Layout, archive list, replay build commands | [README.md](README.md) |
| Fresh checkout, dependencies, portability and checks | [SETUP.md](SETUP.md) |
| Engine requests, results, examples and live interface | [ENGINE.md](ENGINE.md) |
| Exact evaluation formulas, algorithms, goals and options | [Engine design reference](docs/engine-design.md) |
| Deliberative play, verification and compaction recovery | [Play skill](skills/astra-chess-play/SKILL.md) |
| Replay generation, historical scores and publishing conventions | [Archive skill](skills/astra-chess-archive/SKILL.md) |
| Current clock policy and its historical boundary | [TIME-CONTROL-NEXT.md](TIME-CONTROL-NEXT.md) |
| Equipment inventory and validation history | [REPRODUCIBILITY.md](REPRODUCIBILITY.md) |
| Source ZIP/history bundle and GitHub workflow | [PACKAGING.md](PACKAGING.md) |
| Earlier improvement rationale and measured changes | [Proposal](IMPROVEMENT-PROPOSAL.md), [v0.2 changes](ENGINE-CHANGES.md) |

Date-scoped reports retain their original test counts and conditions. Do not
read an old proposal's future tense as proof that a feature is still absent;
check the maintained references and actual implementation.

## Status at this handoff

The repository is on `main`, tracking `origin/main` at
[mikepfrank/astra-chess](https://github.com/mikepfrank/astra-chess).
Before this documentation task, the working tree was clean at `125c669`.

There have been **11 original-session games**, with **nine standalone replay
archives** for games 2 and 4–11. See the [game list](README.md#replay-collection)
and [early records](early-games/README.md) for details. Game 1 was a Sven loss
at High; games 2–3 used Extra High; games 4–11 used Ultra. Explicit prospective
visualization began with the successful Nelson rematch, game 4. Engine assistance
began in game 8: a Wally loss, followed by v0.2 wins against Wally as White and
Black (games 9–10), then the Li draw (game 11). Astra played Black only in game 10.
Mike rechecked Chess.com on September 9, 2026 and confirmed Sven's displayed
rating is **1100**, matching the saved records. Use 1100 for both Sven games
and disregard any conflicting rating mentioned earlier in the conversation.

The latest completed game is **Li (displayed bot rating 2000), Astra White,
1/2–1/2 after 70.Kxe6 by insufficient material**. Its directory is
[engine-games/li-v02-classical/](engine-games/li-v02-classical/).
The read-only recovery check during this task reported `phase: finished`,
139 verified plies, no pending move, no active clock turn, and no consistency
issues within the helper's limited scope. This was not a fresh browser observation.

Mike's intended next original-session trial is a rematch against Li as Black.
At this handoff no new journal has been initialized and no rematch started.
A development session should leave that game to the original playing session;
this orientation does not dispatch another agent to play it. If the session
sequence is unchanged, that next trial would be round 12. Recheck before assigning
any round/slug. Spin-off user games should have their own identifiers and records.

The current rules/search/evaluation fingerprint matches the last Li query:

```text
96e9ed243d69eede25b24c4c22248753053ee162b51fd0eb4cc081f47a311174
```

It covers `rules.py`, `search.py` and `diagnostics.py`, not the wrapper, clock,
UI or full repository. Li began at machinery commit `b613424`; the completed record
was committed in `8470369`, its scored replay in `f5855c7`, and subsequent
documentation in `bdfd048` and `125c669`. Engine rules/search/evaluation remained
unchanged through that game and the later discussion. Verify again before play.

## Lessons that matter more than another list of heuristics

The [Li assessment](engine-games/li-v02-classical/experiment.md) contains the
full examples and their query links. Several deserve carrying into the next
session's operating approach:

1. **Use future-position queries to investigate the opponent's obvious reply.**
   Before 44.Re7+, a query after the hypothetical `Rh7 Ke3` exposed that taking
   h4 would allow `Ra1#`. The interface worked well when deliberately asked that
   question. This was ordinary analysis, not an all-defenses goal proof.
2. **A plausible plan needs tactical support, especially when sacrificing.**
   At 62.Re6, Astra overrode the preference for Rd4 to pursue a concrete pawn
   advance, without separately investigating `Re6 Kxh4`. The next rooted search
   sharply reduced the estimate. A representative principal variation was
   insufficient coverage of the opponent's resources.
3. **A positive score is not demonstrated endgame progress.** Rook and two
   connected pawns against rook produced favorable heuristic scores, but no
   established promotion route. Ask what improves king access, blockade,
   exchanges, or a forcing line. Repeated favorable shuffles should prompt an
   investigation of the defense rather than an impatient sacrifice. We have
   not established that the earlier position was theoretically won.
4. **Keep hypothetical and actual boards separate.** Before 25.a4, fresh
   inspection caught an intended rook move carried over from a variation where
   Black's pawn had moved; on the actual board it could capture the rook.
5. **The engine can catch very elementary deliberative errors too.** The
   move-20 comparison rejected Qg7+, which would hang the queen. Tool usefulness
   includes these corrections as well as sophisticated combinations.

Earlier useful counterexamples include the first engine trial's
[bishop trap and search-horizon failures](engine-games/wally-2026-09-07/experiment-notes.md)
and game 9's [tactical discoveries and bounded mate proof](engine-games/wally-engine-v02/experiment-notes.md).
These are evidence for investigating the method, not a library to consult for
live move advice. Neither bot ratings nor this small, changing experimental
sample establish an Astra Elo, win probability, or isolated effect of a setting.

The agreed next emphasis is more disciplined use of existing tools. The above
lessons do not silently enable new search options or change evaluation weights.
During Li, diagnostics were enabled; optional mobility/restricted-piece/
king-exposure evaluation terms and threat extensions stayed off. Its 91 queries
were ordinary analysis, with no goal probes, and completed depths 4–9.
A requested depth ceiling is not achieved depth.

## Essential workflow and evidence boundaries

The [play skill](skills/astra-chess-play/SKILL.md) is the executable procedure.
In brief: observe the real position and turn time; record an initial candidate
and concern; search; inspect prospective boards and opponent checks/captures/
threats; ask targeted follow-ups; record a choice and concise assessment; submit;
observe acceptance; verify; then observe the actual reply. Record whether the
engine changed the initial idea and the concrete reason, including failures.

Analysis supports arbitrary FENs and hypothetical `after` moves. Restricting
`root_moves` narrows the queried side's choices while retaining opponent replies.
Goal probes distinguish bounded adversarial `forced` results from cooperative
witnesses and `unknown` outcomes. A witness is not a forced line; a timeout is
not a refutation; a safety goal holds only through its tested horizon. Preserve
real position history for repetition: FEN alone does not contain it. See the
[goal reference](docs/engine-design.md#goal-oriented-queries).

Query labels are descriptive text, not natural-language instructions interpreted
by the engine. Astra translates a question into the supported structured fields.

Normal candidate scores favor the **query root's side to move**. That can be
Black, including after a hypothetical continuation. They are heuristic
centipawns, distinct from mate distances, bounded proofs, and actual game results.
Archived scores are original pre-move searches for the actual chosen move,
displayed on its subsequent board; they are not newly computed position grades.
Missing evaluations stay missing. The exporter and archive skill define the
exact matching/perspective rules.

Original live games use the **embedded sidebar browser**, at Mike's request,
so they do not interfere with his desktop. Do not substitute the main desktop
browser merely because a different computer-use tool is available. Reacquire
the current supported browser API and inspect fresh state; old tab IDs, element
handles, coordinates, local preview ports, and screenshots are not active state.
Site hints, takebacks, external engine advice, and other agents choosing moves
are excluded. Independent agents can help develop tools and audit completed
records, as in this handoff, without providing live move advice.

Compaction recovery starts with these read-only commands from the checkout:

```text
python resume_chess.py
python resume_chess.py --game GAME-SLUG
```

Reconcile `game.json`, `clock.jsonl`, query evidence and any unresolved
`continuation.md` with the actual board before acting. `choose` records a pending
move; the journal helper does not control or inspect the browser. A promotion
selector or lost tool response can mean the move is partly entered or already
accepted. Never replay it blindly or invent a submission timestamp. This happened
in game 9; Mike completed the promotion and explicitly authorized a clock credit.
That exception does not authorize automatic refunds in later games.

New trials explicitly select `--time-control classical --own-time-only`:
90 minutes initially, +30 minutes after the 40th verified own move, +30 seconds
per verified own move. Ordinary/critical targets are 120/240 seconds, including
40 seconds for review and entry. The normal initial query is 15 seconds, depth
ceiling 8, three candidates, diagnostics on. Available balances and query caps
still apply. See [the clock policy](TIME-CONTROL-NEXT.md) rather than copying old
fixed-clock commands. Opponent time is excluded; deliberation, commentary,
queries, UI entry, retries and compaction count. Refunds or extra discretionary
time require explicit user authorization and preserved original events; the
selected preset's ordinary increments and stage credit accrue automatically.

Li used **109:56.720** of earned own time and retained **45:03.280**, with no
refund or overall overrun. Search itself consumed **23:07.817**; the rest includes
deliberation, commentary, UI work and interruptions, not separately measured.
This motivates better-directed questions and a tighter surrounding workflow,
as well as any measured engine optimization. See the [time audit](engine-games/li-v02-classical/time-audit.md).

## Parallel development and a future hosted version

**Separate sessions in the same folder share the same files.** A new session
does not isolate edits, default scratch state, test outputs, journal writes,
installed skill copies, or CPU contention. In particular, changing search code
while the original session plays can invalidate the frozen-version experiment.

Recommended working arrangement, to establish with the new development session:

- Use a separate Git worktree or clone and a development branch (`codex/` is the
  branch convention for new work). Pin the experimental playing checkout to its
  chosen engine revision. No worktree or branch was created for this handoff.
- Keep each game's journals, clocks, requests, outputs and UI ownership separate.
  Use distinct paths and ports. Do not run cleanup, generated-file rewrites,
  global skill installation, or branch switches against the playing checkout
  during a trial. Coordinate integration between games.
- Treat the current helpers as local tools, not a complete concurrent service.
  Query locks and atomic JSON writes do not make the entire journal transaction
  safe for multiple writers. Give each game a single state owner. Heavy local
  development/benchmarks can also affect wall-clock-limited search depth.

Useful integration entry points are already present:

| Component | What it provides |
| --- | --- |
| [astra_chess.py](astra_chess.py) | Validated JSON query boundary, arbitrary positions/history, analysis/probes, reports and clock attachment |
| [astra_engine/](astra_engine/) | Importable rules, evaluation/search, diagnostics, reporting and clocks; exact source map in ENGINE.md |
| [play_engine_game.py](play_engine_game.py) | Standard-start, either-color journal and manual choose/submit/verify lifecycle; paths rooted in its checkout |
| [resume_chess.py](resume_chess.py) | Read-only durable-state summary and engine-fingerprint comparison |
| [export_evaluations.py](export_evaluations.py), [build_replay.py](build_replay.py) | Historical score extraction and standalone archive generation |

The report HTML is an evidence viewer that exports follow-up JSON; it does not
run searches, and review notes must be downloaded to persist them. The loopback
`serve_replay.py` serves one static page. Neither supplies a live-game service.

The core is standard-library Python with no network requirement. It is not a
bundled LLM, model API client, UCI-engine service, or unattended browser player.
A public interactive version still needs its own authoritative game transport,
LLM orchestration, per-game isolation, scheduling/resource limits, and deployment
design. The file-oriented local CLI is a useful integration boundary; it is not
an HTTP endpoint to expose unchanged. Those are future engineering decisions.

To preserve this experiment's character, a hosted player should retain the
deliberative query/review/choice loop and evidence of why a move was selected.
Serving only the engine's highest-scoring move would test a different system.
Label the engine revision, model/reasoning configuration, assistance policy and
time policy for each trial so changes can be interpreted. For a service with its
own board, acknowledgment of accepted moves can replace browser observation;
that adaptation must be implemented and tested, not assumed already supported.

## Portability, local memory and exported assets

This handoff includes the relevant surviving conversational context, especially
the simplicity constraint and post-Li operating lessons. No complete transcript
was reconstructed. The actual games and recorded turn assessments remain the
evidence; compaction summaries cannot recover details that were never recorded.

A scoped audit during this task found:

- A keyword search of the available local memory registry
  (`~/.codex/memories/MEMORY.md`) for chess, Astra, Wally, Nelson, Li's slug and
  replays found no matching entries. No additional critical chess memory was
  identified there to export. This is not a claim that every global memory,
  transcript or other session directory has been exhaustively audited.
- Both installed chess skill directories match the versioned copies byte for
  byte, including `SKILL.md` and `agents/openai.yaml`. The canonical
  [skills/](skills/) tree is sufficient; new hosts can read it directly or install
  the complete directories using their own supported skill mechanism.
- The known external visualization asset, `wally-evaluation-history.html`, is
  identical to the tracked
  [visualization.html](engine-output/wally-v02-evaluation/visualization.html).
  Its dataset, build wrapper, preview and checks are also represented in the
  repository inventory. There is no sole external copy of that chart.

For provenance, the original checkout was
`C:/Users/MikeFrank/Documents/ChatGPT/Chess`, installed skills were under
`C:/Users/MikeFrank/.codex/skills`, and the audited visualization directory was
`C:/Users/MikeFrank/.codex/visualizations/2026/09/05/01a07293-7104-7f12-a4ae-26bfbebe674a`.
These paths locate the local audit; they are **not dependencies for a new host**.
Prefer the actual checkout and runtime paths. Do not transplant old process IDs,
monotonic clock state, browser handles, credentials, or ephemeral preview URLs.

[SETUP.md](SETUP.md) distinguishes the standard-library engine from optional
rules-only replay validation (`chess==1.11.2`), PNG rendering (Pillow), and browser
checks (Node/Playwright). These packages and the host's model/browser integration
are not bundled. The original full runtime checks used Windows and Edge;
AWS/Linux/headless interactive play has not been validated. Follow the setup
instructions and establish verification status on the destination environment.

All nine replay pages are standalone and offline, with inline SVG pieces.
Mike verified the eight pre-Li archives on iPhone. Preserve that fix instead of
reintroducing Unicode pawn glyphs with device-dependent emoji rendering. The separate historical chart
uses a pinned D3 CDN and is not fully offline. A replay's HTML is an archive,
not an interactive opponent or a backend. See the [archive skill](skills/astra-chess-archive/SKILL.md).

The separate analysis-report template still uses Unicode piece glyphs. The
replay's iPhone fix should not be assumed to cover that interface; inspect it
on the intended devices if reusing it for a spin-off.

The collection is [astra-plays-chess.netlify.app](https://astra-plays-chess.netlify.app/),
with each replay deployed separately as its project's root `index.html`. Mike
handles Netlify uploads. Existing deployment names are in [replays/index.html](replays/index.html);
`astra-vs-li` remains a proposed name until deployment is confirmed. GitHub pushes
do not redeploy those pages. No `LICENSE` file had been added at this snapshot;
see the current repository and Mike's subsequent decisions for reuse terms.

## Verification and keeping this handoff useful

The last full Python run at the Li archive checkpoint passed **168 tests**, and
four offline replay browser suites passed with Edge. The subsequent documentation
task reran the Li browser suite and reproduced its HTML byte for byte. These are
recorded results, not a claim that this handoff task reran every test or that the
same checks already pass on another OS. Commands are in [SETUP.md](SETUP.md).

Preserve `.gitattributes`: source and evidence fingerprints depend on exact
bytes, and earlier packaging exposed a real line-ending/hash failure. Retain
saved query hashes instead of rewriting them to fit altered files. Temporary
outputs/dependencies stay ignored; only `scratch/README.md` is tracked under
scratch. Promote substantive evidence into the appropriate permanent directory.

Commit authored tools and notes at completion checkpoints. Portable packages
come from a clean committed tree via `package_repo.py`; old packages do not
automatically acquire later changes. The existing
[fresh-source validation](PACKAGING-VALIDATION.md) describes its own historical
checkpoint, not a current AWS deployment test.

For future handoffs, update the snapshot date, current work/ownership, engine
revision, latest experiment and open questions. Keep detailed live recovery
facts beside the game's journal and link them here. New source/state and Mike's
current instructions take precedence over this dated orientation.
