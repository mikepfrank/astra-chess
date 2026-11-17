# Next maintenance window — not authorized to begin tonight

Mike authorized preparation only while heading to bed. Leave all four services
and notification timers running. Resume downtime/deployment only when he returns
and resumes the sequence; the passage of a date is not authorization to start.
His manual post-OS tests passed for private GPT-2, public GPT-2 and Arcturus.
Astra remains online, but new games are intentionally disabled for cost reasons;
its new-game pause must remain unchanged.

## Before downtime

1. Read the latest handoff, current candidate recheck results and the original
   [runbook](../2026-11-15-security-stage/maintenance-runbook.md). All old
   maintenance checkpoints were archived when services reopened; they are not
   a reusable stopped-state reservation. Verify current service identities,
   activity, exact deployed source revisions and candidate paths again.
2. Give the promised downtime heads-up. Coordinate Mike's availability for the
   major-stage pauses and AWS tasks. Private lab tabs must be fully closed
   after their current work finishes; even paused embedded tabs can poll.
3. Use the reviewed lifecycle helpers for fresh admission gates and graceful
   drains. Public GPT-2 retains results for 600 continuous quiet seconds; private
   lab requires its original strict quiet checks. Chess helpers require their
   own quiet intervals. Do not force cancellation or bypass a failed guard.
4. Make a fresh consistent application backup including games and lab activity
   since the pre-OS backup. Retain the existing manual snapshot and discuss any
   additional post-OS snapshot with Mike, who handles AWS console tasks. Do not
   repeat the already-completed OS upgrade or assume automatic snapshots enabled.
   Report/pause at the agreed drain/backup checkpoint.

## Gated activation and regression

- Preserve exact deployed source revisions. Do not pull the unrelated hosted
  branch into Astra. Update only the reviewed dependency pin when deploying the
  corresponding candidate; retain current models, personas and settings.
- Activate each chess final-path Python/venv candidate while its app and notifier
  are stopped, keeping a uniquely named original venv for rollback. Preserve
  Astra's unversioned old-Python alias. Never relocate a prepared venv.
- Switch the shared GPT-2 venv only while **both** GPT-2 applications are stopped.
  Follow [its checklist](../2026-11-16-security-prep/gpt2-activation-checklist.md);
  retain the editable tools reference and exact frozen/deployed source selection.
- Replace Caddy with the verified security binary, retaining its old executable.
  Validate as `astra`, preserving config, TLS state, all routes and Astra's
  independent new-game admission policy. Because systemd binds the executable
  file, activation needs a controlled proxy restart, not only a configuration
  reload. This briefly affects every hosted domain.
- Activate the exact reviewed GPT-2 image through its root-owned launcher;
  preserve its Codex 0.154.0 package, custom seccomp, internal network, firewall,
  UID, mounts and resource limits. Retain the old image; do not globally prune.
- Test real production mount visibility and permissions before reopening, plus
  bounded provider/tool/thread/accounting checks in disposable state, actual
  private gateway isolation, public generation/stream/result behavior, and
  notifier dry runs. No real user game or private lab session should serve as
  a destructive test fixture. Maintain pending inputs and budget/delivery ledgers.
- Astra's monitor drop-in adds a second EnvironmentFile. Diagnostic replicas
  must preserve those as separate directives; joining both paths into one
  systemd-run property failed during the previous preflight. Arcturus's current
  installed checker still correctly requires no unreviewed drop-ins.
- Report and pause before the separately agreed reopening checkpoint. The chess
  `up` helpers reopen immediately after basic health, so invoke them only after
  richer checks finish. Restore GPT-2 with its reviewed validated reopen path.
  Confirm HTTPS, app/timer boot enablement, logs and notification delivery state.

Keep rollback focused on code/runtime/config changes. Do not replace newer game,
chat or budget data with an older backup merely to undo a software deployment.
No additional host reboot is expected for these component swaps.

## Codex remains separate

The retained 0.169.0 archive still matches
`3b8ed091149cc63a59046b9f094bcfa21cdb4dda15ede441ce369bcee4a71ba0`.
It was not promoted or newly integration-tested tonight. Its full chess protocol,
actual tool availability, reasoning/wire, thread/compaction and accounting audit
remains outstanding; the GPT-2 lab's npm/container integration also needs its
own audit. Keep this migration separate from the urgent runtime/trust/proxy
patches. Merely expanding a version allowlist is not adequate validation.
