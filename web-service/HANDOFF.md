# Handoff: the hosted Astra Chess service

For the separate `codex/openrouter-chess` experimental branch, start with the
[September 13 alternate-model orientation](OPENROUTER-EXPERIMENT.md). The hosted
baseline and its deployment history are preserved below.

## September 13, 2026: Arcturus experimental branch

**Latest UI: the clock-side ERROR indicator is bold, bright red.** It follows
Arcturus when the board flips and clears when the worker recovers or the private
view is reset. Desktop/mobile visual checks confirmed the style, flip and
error-to-thinking transition using synthetic data with all network requests
intercepted. This static-only update needs a browser refresh, without a service
restart. Mike deferred investigation of the sporadic underlying errors.

**Latest operation: Arcturus's daily token allowance is 200 million**, activated
at 22:02 UTC through its private `ASTRA_MAX_DAILY_TOKENS=200000000` environment
setting. The shared application default remains 20 million for other deployments.
The current day's 18,156,279-token ledger was retained; the former 20M ceiling
could not admit another 2M reservation. Only Arcturus restarted after an idle
check and coherent private backup. Running-process and service-namespace checks
confirmed 200M/day, 2M/action and 500 actions/day. Game data, conversation,
clocks, usage and saved thread matched after restart; original Astra/Caddy PIDs
were unchanged. The $50 experiment guard and 250K compaction setting remain.
See [the allowance update record](experiments/arcturus-daily-allowance-2026-09-13.json).

**Compaction repair and 250K trigger deployed at 21:32 UTC, code `43a494e`.**
A user's game at ply 11 repeatedly failed with `invalid_tools`.
Read-only inspection found a healthy service, preserved board/conversation and
seven retries that each entered compaction without making a provider request.
Fresh credential-free fixtures with Windows Codex 0.154.0-alpha.6.2 and deployed
Linux 0.154.0 confirmed that `thread/compact/start` sends a normal Responses
request with `tools: []`, unchanged persona instructions, and the configured
model/reasoning. The deployed gateway required all seven chess tools, rejecting
this summarization request before inference. The deployed repair admits exactly
the empty-tool compaction form, retains prompt/model/budget checks, and rejects
tool output during compaction. Ordinary turns still require all seven tools.
See [the original incident record](experiments/arcturus-compaction-incident-2026-09-13.json).

Mike requested a 250,000-token compaction trigger. GLM profile v3 uses that
trigger and the verified 1,310,720-token context window. One explicit compatible
upgrade permits existing v2 games to resume with these runtime settings while
preserving their original profile, thread and exact prompt/persona snapshots.
Runtime settings are recorded separately in bridge and provider-request evidence.
The action token guard is now 2 million, with smaller operator overrides honored;
daily and dollar budgets are unchanged. Requests allow 8 MiB while each streamed
event remains limited to 2 MiB and output to 8,192 tokens.

The complete Windows service suite ran 347 tests successfully, with two Windows
symlink tests skipped. Actual Windows and Linux Codex fixtures completed
compaction, restored seven-tool requests, and resumed the same thread against a
mocked provider. The installed Linux service namespace also passed this lifecycle
and reported the new runtime limits. A coherent stopped-service backup preceded
the update. Every saved database table, private game file and budget file matched
after restart; the original Astra and Caddy PIDs remained unchanged. Both public
health endpoints returned HTTP 200. Mike was told the existing game is ready for
Retry; no move or paid request was made during repair validation. See the
[repair validation record](experiments/arcturus-compaction-repair-2026-09-13.json).

The isolated `codex/openrouter-chess` worktree is
`Chess/openrouter-worktree`. Its model profile selects OpenRouter
`z-ai/glm-5.3-flash:nitro` with high reasoning and throughput-oriented provider
routing. The original `main` and `codex/hosted-chess` checkouts, Astra deployment
and original chess journals remain independently operated.

Model and persona are now separate. `ASTRA_PERSONA` selects the name and voice
for **new games**: Arcturus is the GLM default; Astra remains the original
profile's default. The supplied Arcturus v1 draft is preserved verbatim, with a
separate integration note that treats its anecdotes and prices as creative prior
context, keeps `chess_status` authoritative and preserves the existing chess
method. It grants no additional tools, filesystem work or publication rights.
Read [the prompt/persona architecture](prompts/README.md) before changing it.

`player_profiles.py` creates private prompt/persona snapshots at game creation.
The supervisor passes the verified binding privately to the Codex bridge and
gateway; public state contains the persona name/ID/version and separate model
identity. Existing games continue with their saved persona and exact prompt,
even if defaults or source drafts change. Pre-persona games resolve the frozen,
hash-checked legacy prompt and retain their original Astra or GLM display name.
Model, tool-schema, runtime and engine compatibility checks still apply.

Windows regression, persona and deployment-helper checks have passed. Local
wire checks exercised the actual Codex executable against a mocked provider,
including the exact composed prompt and seven chess tools. The earlier paid
GLM smoke test accepted two moves across a thread resume and reported
`$0.00629936`; that pre-persona operational check is not an Arcturus strength or
long-game compaction result. See [the experiment record](OPENROUTER-EXPERIMENT.md)
for its dated evidence and limits.

**Arcturus is live at https://arcturus.astraplayschess.com**, using the separate
`or-chess` Linux account, `or-chess.service`, private data and runtime, and
loopback port `8792`. Initial activation deployed code through `e1d5cf8`; the later
documentation/operations checkpoint records its validation without restarting
the application. The checkout was transferred with Git bundles rather than
pushed to GitHub. The original Astra application and shared Caddy proxy kept
their existing processes during activation; only the separate hostname was
added with a validated, same-inode Caddy configuration write and SIGUSR1 reload.

Linux namespace preflight, real Codex 0.154.0 wire audit, 80 focused tests and a
paid two-action Arcturus test passed. Arcturus played `1.d4 a6 2.Bf4`, with two
engine queries, saved-thread continuation, and the full persona prompt verified
on all ten requests. Reported inference cost was `$0.00600888`. A first failed
attempt exposed a verified dated model identifier in OpenRouter routing
metadata; `1168a23` fixes this without relaxing response-model validation.
The [Linux smoke report](experiments/arcturus-linux-smoke-2026-09-13.json)
preserves that failure and the successful retry.

The public hostname passed certificate, session-cookie, origin, illegal-move
and persistence checks using three private disposable QA games. Both public
hostnames were checked from Windows; the browser displays Arcturus branding and
is ready for the user to join. No original-site game records were modified.
See [the deployment guide](docs/OPENROUTER-DEPLOYMENT.md) and
[validation record](experiments/arcturus-validation-2026-09-13.json) for details.
Playing strength and long-game context compaction still need separate trials.

The existing $50 experiment ledger was transferred without resetting its baseline;
all paid host checks and the service must use the same private ledger. Stop
local paid experiments before moving ledger authority to Linux; the local
preview was stopped at this checkpoint. Keep the real
OpenRouter key in the service process and use only the temporary gateway token
in Codex. The guard stops new work with $5 remaining but is not a provider hard
cap. Session cookies omit `Domain`, so the deployed Astra and Arcturus hostnames
have separate host-only cookies; local services on different ports of the same
hostname still share browser cookie scope.

## September 11 hosted-service baseline

Prepared September 11, 2026, at a stopping point in Mike Frank's hosted-service
session. This is an orientation for continuing this branch or making a separate
experimental fork, not live game state or an instruction to start a game.

**Branch:** `codex/hosted-chess` in
[mikepfrank/astra-chess](https://github.com/mikepfrank/astra-chess/tree/codex/hosted-chess).
**Application subtree:** `web-service/`. The latest gameplay/replay implementation
at this checkpoint is `bec65c2`; `b3c9a65` records its deployment and validation.
The commit containing this handoff adds documentation and reusable development
tools. Use Git history, not a copied document's date, to identify later changes.

The [root handoff](../HANDOFF.md) describes the original chess.com experiments
before the service existed. Its project intent remains relevant; its statement
that no service has been implemented is historical. This document is the
entry point for the hosted branch. Keep the **whole repository**: the service
imports the root engine, replay builder and historical replay assets.

## Start here in a new session

1. Read this file and [the repository instructions](../AGENTS.md), then check
   branch, working-tree changes and recent commits before editing.
2. Read the relevant maintained references below. Dated validation reports
   preserve earlier settings and test counts; they are not current defaults.
3. Work in an isolated checkout/worktree. The current Windows development
   checkout is `Chess/hosted-worktree`; leave the original `Chess` checkout,
   original experiment journals and any actively playing worker alone.
4. Inspect live state read-only before operations. Do not assume an unfinished
   game means a worker is running, or that an idle game has been abandoned.
5. Use disposable data for tests. Do not run a paid model smoke test, send a
   player message, start a game or publish a replay merely to orient yourself.

| Need | Maintained reference |
| --- | --- |
| Local launch, configuration and product overview | [README](README.md) |
| Reproduce the Windows-to-Linux deployment | [Deployment walkthrough](DEPLOYMENT.md) |
| Authority, identities, recovery and security boundaries | [Architecture](docs/ARCHITECTURE.md) |
| Verified recovery email, SMTP and SES delivery feedback | [Password recovery](docs/PASSWORD-RECOVERY.md) |
| Private table of current and past games | [Operator monitor](docs/OPERATOR-MONITOR.md) |
| Driver protocol, audited versions, context and token accounting | [Codex integration](docs/CODEX-INTEGRATION.md) |
| Replay versions, routes, migration and privacy semantics | [Replay workflow](docs/REPLAY-WORKFLOW.md) |
| Installed host, later policy changes and deployment evidence | [Lightsail checkpoint](docs/LIGHTSAIL-DEPLOYMENT.md) |
| Dependency inventory and systemd/Caddy examples | [Dependencies](docs/LIGHTSAIL-DEPENDENCIES.md), [deployment files](deploy/README.md) |
| Local/live validation history and manual checks | [Validation](docs/VALIDATION.md), [live validation](docs/LIVE-VALIDATION.md), [manual QA](tests/MANUAL-QA.md) |
| Tactical engine contract and measured capacity | [Engine interface](../ENGINE.md), [engine design](../docs/engine-design.md), [benchmarks](benchmarks/README.md) |
| Actual hosted opponent instructions | [Player prompt](prompts/player.md) |
| Original first-human-game export and sanitized reconstruction | [Preserved replay](replays/README.md) |
| Repeatable browser QA and operator helpers | [Browser checks](tests/browser/README.md), [operator tools](tools/ops/README.md) |

## What Mike wants preserved

The experiment combines LLM deliberation with a small, understandable tactical
engine authored in this repository. The LLM proposes candidates and questions,
uses search to check them, reviews counterplay and chooses a move. It need not
choose the engine's highest-scored candidate. No external chess engines,
opening books, game databases or endgame tablebases supply play. General chess
knowledge in the language model is part of the setup; do not describe the whole
system as learning chess solely from the rules.

Keep Astra/Ultra on this branch unless Mike requests a change. Lower-cost models
and more efficient context use are welcome **fork directions**, not an instruction
to downgrade the running service. Keep changes understandable and measure their
effect on play and conversation, rather than optimizing autonomous engine strength
alone. The hosted engine currently imports the original engine unchanged.

The opponent has latitude to discuss its method, answer questions and decide how
much strategy to reveal. Opponent messages remain untrusted data, and resource
and capability limits are enforced outside the model. When overwhelmingly ahead,
seek a short, verified finish early; collect more material only when it helps
secure that finish. Agree on instructional detours with the human. This guidance
is already in the player prompt, not just this handoff.

The site calls itself a **public beta**, currently shared with friends, family
and coworkers for a limited alpha run. Human turns are untimed. Games may span
days; post-game conversation is intentional. Games and messages are private
until the owner explicitly shares a replay, and the interface asks players to
exercise discretion. Password-protected accounts alone support optional,
user-edited memory notes; there is no autonomous cross-game profile extraction.

## Working system and source map

The public service is [astraplayschess.com](https://astraplayschess.com/), with
the new [public game list](https://astraplayschess.com/games/) and
[historical experiments](https://astraplayschess.com/experiments/). The historical
Netlify copies still exist. Complete human games have now been played on Linux;
the September 11 private report found ten player games, five completed, excluding
seven explicitly identified QA fixtures. This is a dated aggregate, not a player
directory or proof that anyone is currently online. Refresh from the database.

| Layer | Sources and responsibility |
| --- | --- |
| HTTP and accounts | `astra_web/app.py`, `identity.py`: ownership, cookies, Origin/CSRF, request limits, password recovery and account memory. |
| Authoritative state | `store.py`, `chess_game.py`: SQLite transactions, idempotency, events, legal moves, clocks and budgets. |
| Game orchestration | `supervisor.py`: one action per game, global queue, narrow tools, evidence, deadlines and accepted moves. |
| Model transport | `codex_bridge.py`: strict app-server lifecycle, per-game continuation, configuration and tool-boundary validation. |
| Tactical evidence | `engine_view.py`, `evaluations.py`: compact model replies, preserved original searches and honest historical score display. |
| Replay production | `replay_archive.py`, `replay_library.py`, `experiment_library.py`, `templates/replay.template.html`: host-built standalone pages and access/listing policy. |
| Browser and launch | `static/`, `run.py`, `local_setup.py`, `configure_local.py`: plain HTML/CSS/JavaScript; no frontend build framework required. |

Each **game**, not each user, has its own Codex home, thread and context. The CLI
is spawned for one action and exits afterward. A fresh authoritative snapshot
accompanies a resumed action. Several unfinished games can coexist for one
owner; the default global scheduler runs one at a time. After 36 hours without
human game activity, suspension preserves the board and continuation for return.
No CLI needs to remain alive throughout that interval.

Hosted recovery uses SQLite plus private per-game files. The root
`resume_chess.py` and original play skill concern the earlier browser-controlled
bot trials; they do not recover or authorize changes to hosted games. Private
Codex rollouts, saved engine queries and durable event records are evidence that
must survive a deployment, not material to place in a public replay or Git.

## Current operating policy

These values describe the September 11 checkpoint. Recheck effective host
configuration before changing capacity or making cost claims.

| Setting | Source default / current deployment |
| --- | --- |
| Driver | Fixed `gpt-6-astra`, `ultra`; these are not general environment selectors. |
| Player availability | `disabled` by default; operator enables `codex`. Never silently substitute a test/engine-only player. |
| Reviewed CLI releases | Windows `0.153.4`; Linux `0.154.0`. Other versions fail closed pending protocol audit. |
| Context / automatic compaction | 400,000 raw tokens, 380,000 usable; 250,000 **total-context** soft trigger. |
| Daily token allowance | Generic default 20,000,000; laptop and Lightsail explicitly configured to **100,000,000**. |
| Per-action / daily admission | 3,000,000-token reservation and 500 actions/day by default; failed attempts and chat also consume resources. |
| Scheduling | One active worker; three unfinished games per owner; ordinary/critical allocations 120/240 seconds. |
| Tactical queries | At most eight per action, with host-controlled time and paths. |
| Chess clock | Astra starts with 90 minutes; +30 minutes after its 40th verified move; +30 seconds per verified own move from move 1. |

The 250K trigger replaced 300K after Mike noted long-context pricing above a
272K input boundary. The rationale and dated sources are in the integration
reference. It is **not** a hard cap on billed input: request growth and compaction
can cross it. Context-window settings do not enlarge a model output-token cap.
Verify current provider pricing before recommending budgets for another instance.

The token ledger includes repeated/cached input and compaction, so it is neither
newly generated tokens nor an exact dollar meter. Admission reserves the full
action allowance against its UTC day. Unknown usage and crash recovery charge
conservatively; retrying refunds eligible **clock time**, not paid usage. Avoid
explaining a resource-limit error as an API rate-limit error without evidence.

## Behavior that earlier iterations taught us to preserve

- **Retries and clocks:** a harness failure is retryable without changing accepted
  moves. Retry restores recorded charges for failed attempts on the same
  unfinished own turn, with deduplication; no credit from previously completed
  turns. Queue time is free. Avoid restarting the service during an active turn.
- **Progress and compaction:** THINKING distinguishes deliberation from CALCULATING
  during engine work. Validated compaction start/end events show COMPACTING and
  pause the clock and turn allocation. Duplicate/stale events cannot award time.
  The bridge still has an independent 300-second emergency wall timeout; a
  compaction pause does not remove every external runtime bound.
- **Evaluations:** the default-off box uses evidence for Astra's last accepted
  move, persists through the human reply and does no fresh search. Verified goal
  mates override heuristic pawn scores. Displayed winning mate distance is after
  Astra's move; the note reads "Mate-in count = your maximum remaining turns."
  Hide the box at the starting position and checkmate. Preserve score perspective
  for Astra playing either color and do not infer a forced mate from chat text.
- **Conversation:** post-game chat stays enabled under the ordinary message and
  resource limits. The emoji picker inserts text at the caret; it is not a
  separate messaging channel. Reload restores the saved game rather than
  resetting it, including from another browser after protected-account login.
- **Replays:** generation is explicit, after game end, and uses a bounded host
  worker without a model call. Download and sharing are independent actions.
  Moves only and With chat remain independent saved versions, including newer
  post-game chat only when regenerated. Sharing defaults to an unlisted URL;
  public listing is a separate opt-in. One public entry per game prefers With
  chat **only when both versions are explicitly listed**. Private/unlisted chat
  never replaces a listed moves-only replay.
- **Replay deletion:** unlist keeps the URL; disable link revokes access but keeps
  the private download; delete version removes that version only. Updating one
  private version preserves its older shared copy until explicitly reshared.
  Failed refresh leaves the previous download available. Legacy share links
  are independently manageable. See the workflow for exact route semantics.

The replay-variant migration is an operational boundary: old metadata is retired
once so deleted links cannot resurrect. Existing IDs, tokens, bytes and visibility
are preserved. Code-only rollback cannot serve migrated standalone links; writes
by an old release then cause the new release to refuse startup pending operator
reconciliation. Prefer a forward fix after player activity. Do not restore an
old complete database over newer games. Rehearse migrations on a private copy.

## Deployment and private data

The current shared-purpose host runs Amazon Linux 2023, with two vCPUs and 8 GB
RAM. The service's dedicated account is **astra**, not the early typo "alpha".
Windows SSH alias `lightsail` reaches `ec2-user`; use `sudo -n -iu astra` for
account operations. Keep installations primarily under this account, as Mike
requested. Do not disturb the other services on the machine.

| Item | Current host location |
| --- | --- |
| Repository | `/home/astra/astra-chess`, branch `codex/hosted-chess` |
| Private environment | `/home/astra/.config/astra-chess/service.env` (0600) |
| Data / database | `/home/astra/.local/share/astra-chess/astra.sqlite3` and siblings |
| Game continuation / queries | `players/<game-id>/` and `games/<game-id>/queries/` under the data directory |
| Replay HTML | `replay-archives/` for private versions, `public-replays/` for shared snapshots; database controls access |
| Python | Private runtime under `/home/astra/.local/share/astra-chess-runtime`; application `.venv` |
| Codex | Complete `0.154.0-x86_64-unknown-linux-musl` bundle under `/home/astra/.codex/packages/standalone/releases/` |
| Services | `astra-chess.service` on loopback `127.0.0.1:8788`; `astra-caddy.service` for HTTPS |

The application uses an API key with the fixed OpenAI API provider. The operator's
interactive Codex/ChatGPT Pro login is not the hosted application's credential.
Never print the whole environment/profile/auth file, place credentials in source,
copy private rollouts into docs, or expose keys to the browser. Windows local
setup uses DPAPI-encrypted storage under ignored `var/secrets/`, not a Linux key.

The systemd unit exposes read-only source/runtime/bundle mounts and a writable
private data directory, with a 2 GB memory limit, 100% aggregate CPU quota
(one logical CPU), and 64 tasks. The complete Codex bundle is required for its
code-mode host and sandbox helpers. See deployment docs for the exact namespace
checks; per-game directories alone do not prove isolation between hostile tenants.

For a runtime update: stage and validate the exact pushed commit, wait for no
queued/thinking/calculating/compacting game workers, no building replay jobs and
no outstanding token reservations. Stop only the application, recheck saved
state, take a coherent private backup, fast-forward its clean checkout, restart
and verify state preservation. An idle snapshot alone cannot exclude new requests.
Loopback HTTPS-proxy
checks need `Host: astraplayschess.com` and `X-Forwarded-Proto: https`. Normalize
header names before comparing them. Earlier failed operator health checks used
the wrong Host/header casing; they were not evidence that the app was broken.
Documentation/tests/tools-only updates need no service restart. See the operator
README for the checklist, report command and migration-copy rehearsal.

## A basis for forks, not a production model switch

Clone the entire repository and branch from this checkpoint into a new worktree.
Give the experiment a separate data directory, port, origin, credentials/config
and service name as appropriate. Start **new games** in it; never point a new
driver at production homes or copy real player data into a public test fixture.
An engine experiment should preserve an identifiable baseline and its evidence.

The principal transport seam is async
`CodexPlayer.run(game_id, snapshot, tool_handler, emit, thread_id=None)` plus
`close()`. The supervisor owns rules, tools, clocks and evidence. Driver callbacks
include durable `_thread`, `_usage` and `_compaction` lifecycle events alongside
seven allowlisted chess tools. An alternate driver must preserve early
continuation persistence, cancellation/process cleanup, public/private output
separation, usage accounting and authoritative state reconciliation.

This is not an arbitrary SDK/model-name substitution: protocol schemas, model
checks, code-mode assumptions, effective configuration and capability denial
are currently Codex-specific. Unknown capabilities fail closed. The test
`player_factory` is not a production provider registry. There is no per-game
driver selector or guard against changing global model settings underneath an
old game; a future implementation should bind driver/model identity to each
game and explicitly design any migration.

For cost work, first measure uncached versus cached input, output/reasoning,
compaction, latency and engine depth separately. Preserve full original evidence
while reducing redundant provider payloads. Compare playing quality and the
conversation experience on a fixed set of positions/games, not just token totals.
Cheap wins may come from better tactical questions or context representation;
do not assume more engine complexity or a lower reasoning setting is harmless.
Capability work should retain owner authorization, replay privacy and clock
invariants, with migrations and recovery tests when durable state changes.

## Evidence, remaining work and preserved machinery

September 12 addition: an independent [hourly new-game email monitor](docs/GAME-NOTIFICATIONS.md)
uses no model calls and keeps its notification history outside the application
data directory. It requires dedicated SMTP configuration and delivery testing
before its timer is enabled. The September 12 Lightsail activation passed a
real SES SMTP test and first digest, then enabled its hourly timer; see the
guide's dated activation checkpoint. Its presence in the repository does not
establish that outbound mail is configured on another host. See its guide for setup,
retry semantics, SQLite sidecar permissions and the additional units to stop
when replacing/restoring the database. It does not enable password-reset mail.

September 12 recovery checkpoint: verified recovery addresses, account settings,
confirmation and reset delivery are implemented. See the
[recovery guide](docs/PASSWORD-RECOVERY.md) for the exact lifecycle and setup.
Windows passed 232 tests with two platform skips; an isolated Linux staging
copy passed 46 focused identity, recovery, service and diagnostic-environment
tests. Browser checks cover the lifecycle and delayed authentication/cookie
races. A coherent copy of the deployed database preserved all 15 existing
non-reset tables through two migration passes. Existing sessions remain valid;
old reset tokens are intentionally retired and legacy email stays unverified.

Real SMTP confirmation and reset messages for a disposable operator-owned
account were accepted by SES; confirmation, reset, session revocation and new
login passed. The operator confirmed both recovery messages reached Gmail's
inbox. An intentional SES mailbox-simulator bounce was submitted to verify
forwarding; receipt of that notice remains unconfirmed. AWS production access
has been requested and approval is still pending. Suppression for bounces/complaints and
identity email feedback forwarding are confirmed enabled. Recovery code was
subsequently installed with the monitor release below; recovery mail remains
disabled. Complete the remaining provider/delivery checks and use the documented
gated maintenance procedure when installing private application SMTP settings.

September 12 private dashboard checkpoint: runtime `ef626dd` installed
`/monitor/`, using the existing password-account cookie and one privately
configured immutable operator account ID. It refreshes every 30 seconds while
visible and reads game inventory without model calls or game mutations. The
[monitor guide](docs/OPERATOR-MONITOR.md) records authorization, field limits,
exact fixture exclusions, refresh behavior and installation. Operator IDs and
fixture IDs live only in private `operator.env`; the systemd `20-monitor.conf`
drop-in loads it. A public page shell alone grants no access to the report.

The full Windows suite passed 239 tests with two platform skips; 53 focused
Linux tests and synthetic monitor/recovery browser checks passed. The proxy
and notification timer were paused, two idle checks and process inspection
confirmed no workers, and a coherent database plus full data backup preceded
the restart. All 15 preexisting non-reset table digests using original columns
matched after startup. The live browser confirmed the authorized dashboard;
anonymous API access was denied. The hourly notifier is active again. No Astra
turn was interrupted. Recovery schema/code is now deployed, but SMTP remains
unset and `email_reset_available` remains false while SES approval and
bounce-feedback delivery confirmation are pending.

At runtime revision `bec65c2`, the final Linux suite passed **194 tests** with
three platform skips. Windows passed the preceding **193-test full suite** with
two skips, then **28 replay-library tests** after the last ambiguity guard; there
was not a full final 194-test Windows rerun. Browser checks covered both retained
versions, independent downloads/URLs, listing preference/fallback, failed-refresh
retention, legacy links, chat escaping, offline playback and emulated narrow
layout. Async UI checks covered stale responses and blocked variant switching.
The dated replay/deployment references contain the exact checks and boundaries.

Real human Linux games now work. An explicitly observed Linux automatic-compaction
cycle, heavy-load behavior, startup after host reboot and comprehensive hostile
tenant isolation remain separate validation gaps. Offsite backups are not
configured. Password recovery has passed isolated delivery/lifecycle checks but
awaits live activation as described above. Operator notifications have separate mail
configuration; their current installation evidence is in the notification guide.
CPU benchmarks are dated measurements, not a promised concurrent-player capacity.

This checkpoint promotes portable browser QA and read-only game reporting/private
copy migration rehearsal from working helpers. Commands and targeted validation
live with those tools. All six new operator-tool tests and all four promoted
browser checks passed on Windows against synthetic local data; Python/JavaScript
syntax and local documentation links also passed. No production game or model
call was used for this checkpoint. The tracked no-key protocol audit and service checks also
remain available. Paid `live_*` model checks are opt-in, not part of ordinary unit
discovery. Rerun relevant checks for changed behavior; a docs-only checkpoint
does not justify spending tokens or interrupting live games.

Ignored fixture databases, access tokens, screenshots, downloads, logs, caches,
virtual environments and real player homes intentionally remain outside Git.
Dated one-shot deployment scripts with hardcoded revisions or reset commands are
superseded by the documented procedure, not reusable deployment entry points.
The public repository preserves source, sanitized historical examples, tests and
the reconstruction workflow; operator backups and private game records are a
different responsibility. On return to this session, refresh the checkout and
live state rather than treating this snapshot as an outstanding action queue.
