# Operator inventory and replay migration rehearsal

These tools preserve the reusable parts of the first hosted deployments. Run
them from a checkout containing the complete repository, using the application's
Python virtual environment. They do not start model turns, run tactical searches,
change game clocks, restart services or update Git. Inventory and migration
rehearsal do not read credentials; the optional notification sender reads its
own explicitly configured mail credentials.

| Tool | Source access | Writes |
|---|---|---|
| `report_games.py` | One read-only SQLite transaction | Standard output only |
| `rehearse_replay_migration.py` | Read-only SQLite backup and replay HTML reads | A new private copy, migrated using the checkout's replay code |
| `notify_new_games.py` | Read-only SQLite game inventory | Separate private notification state; explicitly configured operator email |

The notification tool has a separate [setup and operations guide](../../docs/GAME-NOTIFICATIONS.md).
It is an opt-in mail sender; the read-only report and migration rehearsal do not send mail.

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
4. At the coordinated idle boundary, stop the application and re-check the
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

## Validation

```sh
.venv/bin/python -m unittest discover -s tests -p test_operator_tools.py -v
```

The focused tests exercise read-only enforcement and content minimization,
explicit QA classification, worker/build/reservation accounting, escaped report
text, migration preservation on a private copy, refusal to overwrite existing
directories, and copy-race detection. They use temporary fixtures and do not
contact the deployed service.
