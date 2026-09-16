# Operator tools and preserved deployment procedures

The inventory, notification and rehearsal tools below preserve reusable parts
of the first hosted deployments. Run
them from a checkout containing the complete repository, using the application's
Python virtual environment. They do not start model turns, run tactical searches,
change game clocks, restart services or update Git. Inventory and migration
rehearsal do not read credentials; the optional notification sender reads its
own explicitly configured mail credentials.

The directory also contains explicitly operated repair/activation tools and a
maintenance-gate context manager; their individual sections define their side
effects. The dated [September 14 deployment archive](history/2026-09-14/README.md)
preserves the chat and parallel-worker deployment sources and dependency chain.
Those archived files refuse direct execution and are not current deployment
entrypoints. See also the [housekeeping record](../../validation/2026-09-14-housekeeping.md)
for retained audit helpers and exclusions.

| Tool | Source access | Writes |
|---|---|---|
| `report_games.py` | One read-only SQLite transaction | Standard output only |
| `rehearse_replay_migration.py` | Read-only SQLite backup and replay HTML reads | A new private copy, migrated using the checkout's replay code |
| `notify_new_games.py` | Read-only SQLite game inventory | Separate private notification state; explicitly configured operator email |

The notification tool has a separate [setup and operations guide](../../docs/GAME-NOTIFICATIONS.md).
It is an opt-in mail sender; the read-only report and migration rehearsal do not send mail.

## Preserved Arcturus audit helpers

The September 15 UI release adds `tests/check_ui_controls.py FULL_COMMIT_SHA`
for an exact clean-checkout regression receipt. Together with the native mocked
four-action reasoning audit, its receipt is required by
[deploy_arcturus_ui.py](deploy_arcturus_ui.py). The deployment helper requires
explicit installed/candidate SHAs and the exact `/home/or-chess/ui-staging/SHORTSHA`
directory; it validates the changed-file allowlist, waits for an idle snapshot,
gates Arcturus admissions, backs up private data/configuration and checks every
game/table/file digest across an Arcturus-only restart. It preserves the original
Astra/Caddy processes and installed units/timers. Code rollback never restores a
player database. Use the validation record for the actual activated revision;
running a helper is not itself proof of successful deployment.

The tool-output repair additionally requires an exact-commit native visibility
receipt at `var/native-tool-visibility.json`, produced by
`tests/audit_tool_visibility.py`. This proves that long Unicode user comments
survive in the actual mocked-provider requests, both immediately and after
process restart. It does not send messages or make paid calls.

The head-to-head score feature uses this same deployment path. Its totals are
derived from the existing account-owned completed games; no migration or
initialization write is needed. The regression runner includes result counting,
account/persona/model isolation and model-context delivery checks.

Private RTF chat export also uses this deployment path. It reads one owned game
snapshot without changing game data or scheduling a model action. Its regression
checks cover transcript order, Unicode/RTF escaping, ownership and read-only
behavior; browser checks exercise the save picker and normal download fallback.

The following helpers were promoted from ignored scratch storage during the
September 14 housekeeping checkpoint. Their new CLI/import boundaries were
checked offline; preservation did not repeat live email or service-namespace
tests. Run only the check actually needed for an authorized operation.

| Helper | Scope and invocation from `web-service/` |
|---|---|
| [check_chat_policy.py](../../tests/check_chat_policy.py) | `.venv/bin/python tests/check_chat_policy.py FULL_COMMIT_SHA`; offline fixture suite, exact clean tracked revision required; writes `var/chat-tests.json` |
| [audit_arcturus_public.py](../../tests/audit_arcturus_public.py) | `.venv/bin/python tests/audit_arcturus_public.py`; bounded public HTTPS/config/replay/redirect checks and anonymous rejected origin/CSRF probes; no credentials or player actions |
| [audit_or_chess_notifier_namespace.py](../../tests/audit_or_chess_notifier_namespace.py) | `sudo .venv/bin/python tests/audit_or_chess_notifier_namespace.py`; Linux-only transient namespace/WAL/isolation fixture and private receipt; no mail by default |
| [check_arcturus_mail.py](check_arcturus_mail.py) | `sudo .venv/bin/python tools/ops/check_arcturus_mail.py --stage /home/or-chess/mail-staging/CHECKPOINT --recipient ADDRESS --live`; sends three real verification/reset/notification messages using disposable records |

The namespace audit reads the installed notifier configuration; sending one
synthetic message additionally requires `--send-test-email --recipient ADDRESS`.
The explicit address must match the configured authorized recipient. The
three-message mail check defaults to the separate Arcturus notifier credentials;
`--source-config` can select another explicitly intended private configuration.
Both mail helpers validate before sending and preserve real account/game data.
Inspect `--help` for selectable paths. SMTP acceptance alone does not establish
inbox receipt or enable application password recovery for general recipients.

## Repair existing Arcturus replay branding

[`repair_arcturus_replay_branding.py`](repair_arcturus_replay_branding.py) repairs
one explicitly selected finished Arcturus game's existing HTML snapshots and
adds only `player_name` to its publication metadata. It never captures the
latest game conversation: private and shared copies retain their own chat,
move and evaluation snapshots, archive IDs, tokens, listing flags and timestamps.
Mentions of Astra inside chat and private records remain unchanged.

Run a read-only plan from the reviewed experimental checkout first:

```sh
.venv/bin/python tools/ops/repair_arcturus_replay_branding.py --data-dir /home/or-chess/.local/share/or-chess --game GAME_ID
```

After stopping only `or-chess.service` and taking the deployment's full private
data backup, repeat the plan at that stable boundary. Apply requires its exact
hash and a new private backup directory outside the live data tree:

```sh
.venv/bin/python tools/ops/repair_arcturus_replay_branding.py --data-dir /home/or-chess/.local/share/or-chess --game GAME_ID --apply --expect-plan PLAN_SHA256 --backup-dir /home/or-chess/backups/NEW_REPAIR_DIRECTORY
```

The CLI refuses apply outside that installed data directory or while the unit
or its descendants run. It saves a coherent SQLite backup and exact changed
HTML, then updates only known branding fields. All other database rows and
columns, query/game evidence, Codex records and the spending ledger must retain
their hashes. Changed input invalidates the plan; unsupported HTML, symlinks or
retired replay metadata require review. Legacy `/replay/` links are counted and
left unchanged. A caught failure rolls back publication metadata and written
HTML; keep the service stopped for manual recovery if rollback cannot verify.

Deploy the matching persona-aware renderer and index code before restarting.
The application rebuilds the generated index from publication metadata. Verify
the same public links, chat choices and script-hash CSP after restart. The tool
does not operate Caddy or the original Astra application, regenerate evaluations,
change the game or clock, or consume model tokens.

## Read-only game and resource report

From `web-service/` on Linux:

```sh
.venv/bin/python tools/ops/report_games.py \
  --data-dir /home/astra/.local/share/astra-chess \
  --timezone America/Chicago --markdown
```

On Windows, use `.venv/Scripts/python.exe` and the desired data directory.
The default timezone is UTC. Named IANA timezones use operating-system timezone
data or the optional Python `tzdata` package; if neither is available, use UTC
or add `tzdata` to the operator's virtual environment. The service does not need
an added runtime dependency for this tool.

Use `--json` for structured output. Add one `--qa-name "Exact display name"`
argument for each known test account that should be marked as QA. Matching is
exact and case sensitive. The script deliberately does not classify names such
as `Weekend tester`, or every name containing “test”, as QA: those can be real
players. Names not explicitly marked QA count as player games; this is an
operator classification, not proof of identity.

The report includes saved game status, human color/outcome, ply and last SAN
move, last player activity, worker state, private/shared/listed replay variants,
and the UTC daily usage ledger. It omits conversation text, internal reasoning,
account IDs, authentication records, share tokens/URLs, and credentials. The JSON
contains private game identifiers for operator lookup. Treat the report as an
operator artifact; it is not a public page or a new privacy policy.

`--require-idle` exits with status 2 if the snapshot contains an active response,
replay construction, or reserved tokens. Status 0 means this snapshot was idle;
it does **not** reserve the server or make a later restart safe. Read-only
queries do not establish whether a human is currently online. A finished game
can still have an active post-game conversation.

## Rehearse replay migration on a private copy

This tool generalizes the original ignored
`var/qa/probe-replay-variants-migration.py`. It runs the replay migration belonging
to **the checkout containing the tool**, against a copy. Run it from staged new
code when checking a planned upgrade. It does not deploy that code.

Choose a fresh destination outside the source data directory. Its parent must
already exist. Existing directories, paths inside the source, symlinks, and
junctions in replay trees are refused; nothing is recursively deleted or reused.
For example, first create a private operator directory under the service user's
home, then choose an unused child name:

```sh
mkdir -m 700 /home/astra/replay-rehearsals
.venv/bin/python tools/ops/rehearse_replay_migration.py \
  --data-dir /home/astra/.local/share/astra-chess \
  --copy-dir /home/astra/replay-rehearsals/before-next-upgrade
```

The copy contains a full SQLite backup, including private messages and identity
records, plus `replay-archives/` and `public-replays/` HTML files. On Linux the
new root directory is mode 0700 and its database/result are mode 0600. On
Windows, choose a parent directory whose ACL already limits access to the
operator. Never commit, publish, or place this copy under a web root.

The tool checks idle state before copying and verifies source database/file
stability across the copy. If players or operators change the source meanwhile,
it stops and retains the private copy for inspection. This is a rehearsal, not
a complete service backup: Codex sessions, query evidence, API credentials, and
proxy TLS state are not copied. Prefer a coordinated maintenance window or a
coherent stopped-service backup when rehearsing migrations.

It verifies that migration preserves existing download IDs and HTML bytes,
shared URLs and visibility, every non-replay database table, and an opposite
variant that previously existed only as a shared snapshot. It runs recovery a
second time to verify idempotence. A successful copy receives a small
`result.json` containing counts and verification outcomes, without player names,
chat, tokens, or auth data. Failures leave the source untouched and retain the
new directory; inspect it before choosing a different unused destination.

The independent-variant migration retires old replay metadata. An older release
cannot serve those standalone links until the newer release is restored. If
the old release creates new replay records after rollback, the newer release
refuses startup for explicit reconciliation rather than silently reimporting
possibly revoked links. Legacy `/replay/` links remain separate.

## Preserved deployment procedure

Use [the deployment walkthrough](../../DEPLOYMENT.md#operations-updates-and-moving-to-another-host)
and [the concrete deployment checkpoint](../../docs/LIGHTSAIL-DEPLOYMENT.md#permissions-backup-and-rollback)
for service-specific paths, backups, units, and rollout history.

1. Record the current and candidate Git revisions, clean-checkout status,
   dependency changes, and engine fingerprint. Run appropriate tests against
   staged code, not by changing a running player's source tree.
2. Use the report to inspect all active and completed games, post-game workers,
   replay builds, and outstanding resource reservations. Coordinate maintenance;
   a single idle snapshot cannot prevent a subsequent player request.
3. For a replay schema change, rehearse the staged migration on a new private
   copy and inspect its result before touching the running service. Use a
   coherent earlier backup or the tool's source-stability checks; retry if
   concurrent activity prevents a consistent copy.
4. Gate new requests at the proxy and recheck that existing work has drained.
   At the coordinated idle boundary, stop the application and re-check the
   saved state before changing code. Take the definitive coherent private
   backup now, with the writer stopped, as described in the deployment
   walkthrough. Preserve game records, clocks, usage, legacy links, and replay
   identities/bytes. Keep the proxy and unrelated services unchanged unless
   their configuration is part of the approved change.
5. Apply the reviewed update, dependencies, and any required unit changes.
   Run service-boundary checks with
   [run_service_check.py](../run_service_check.py). Start the application and
   verify origin-aware health and representative pages, followed by external
   HTTPS and browser checks.
6. Compare protected records and replay identities with the pre-update snapshot.
   Save a private audit with the deployed revision, test results, backup
   location, and preservation checks. Record a concise non-sensitive checkpoint
   in the repository. Account for schema compatibility before any rollback.

The dated ignored `var/qa/deploy-replay-variants.py` and
`var/qa/deploy-unified-replay.py` remain one-use evidence. They contain fixed
expected revisions, host/user paths, service assumptions, and `git reset --hard`
rollback commands; they are **not** reusable deployment entrypoints. The existing
[guard_compaction_restart.py](../../tests/guard_compaction_restart.py) remains a
local-development checkpoint helper, with a fixed local `var/` path and a
written digest file. Use the read-only report for portable inspection; use the
full coordinated procedure for deployment, rather than treating that older
guard's limited digest as complete preservation evidence.

For the reviewed Arcturus host,
[arcturus_maintenance_gate.py](arcturus_maintenance_gate.py) provides a root-only
`arcturus_maintenance_gate()` context manager. It temporarily returns 503 with
`Retry-After: 30` for only the canonical and legacy Arcturus proxy blocks.
It validates the candidate, preserves Caddy's configuration inode and process,
and verifies original Astra routes. It has no standalone apply command.
Enter it before the final idle check; keep application rollback/restart cleanup
inside the context so the app is healthy before the gate restores access.
If work started just before gating, allow it to finish or leave the gate and
defer deployment. Never treat successful gate entry as evidence that existing
workers have stopped. Exact original bytes and a private recovery receipt are
saved on the host; interruption or host-loss recovery is described in the module.

## Validation

```sh
.venv/bin/python -m unittest discover -s tests -p test_operator_tools.py -v
```

The focused tests exercise read-only enforcement and content minimization,
explicit QA classification, worker/build/reservation accounting, escaped report
text, migration preservation on a private copy, refusal to overwrite existing
directories, and copy-race detection. They use temporary fixtures and do not
contact the deployed service.
