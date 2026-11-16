# November 16 maintenance preparation checkpoint

Mike resumed the approved maintenance plan, requested a heads-up immediately
before downtime, confirmed the private GPT-2 lab is idle with tabs closed/paused,
and will create/confirm the Lightsail snapshot himself. Continue to return to
the session prompt after each major step. The next checkpoint is all four apps
drained, stopped, boot-disabled and privately backed up, before OS installation.

## Preparation completed, no activation

- Fresh host check at 19:28 UTC: no failed units; 245 GiB disk free, about 11 GiB
  available RAM, no swap. All four app PIDs and shared proxy PID unchanged from
  yesterday; three public health endpoints returned 200. Public GPT-2 queue
  empty, private lab 18 idle sessions (six retain pending human inputs), zero
  sandbox children. Both chess lifecycle `--check` commands passed with zero
  active responses/replay builds/reserved tokens.
- OS remains AL2023 `2023.9.20251208`, kernel `6.1.158-180.294`. The pinned
  `2023.12.20261112` preview still lists 252 upgrades and 22 installs (395 MB).
  All 274 retained RPM sizes/SHA-256 values match the signed-package manifest.
  The staged Caddy SHA-256 still matches the November 15 tested candidate.
- [Shared GPT-2 Python candidate](gpt2-python-preparation.md): inactive final
  venv, certifi 2026.10.23 only dependency change, 206 public and 381 private
  application tests passed. Repeat runtime checks after the OS changes.
- [Private sandbox image](gpt2-image-assessment.md): inactive Node 22.23.5 image,
  15 Debian package updates/27 available package-CVE fixes, exact Codex 0.154.0
  files/protocol retained; credential-free sandbox/stdio probes passed.
  Assessment has explicit residual/unassigned-advisory limits, not a clean
  vulnerability bill of health. Production image tag unchanged.
- [GPT-2 lifecycle helper](gpt2-maintenance.md): 25 safety tests passed; staged
  at `/home/ec2-user/chess-security-stage-20261116/ops/gpt2_maintenance.py`.
  Live `check` passed; `prepare` saved a root-private checkpoint and validated
  both candidate Caddy gates. No traffic gating/reload occurred during prepare.
- `backup_host_security.py`: 11 guard tests passed plus independent review.
  Refuses until all four stopped checkpoints exist, apps/timers boot-disabled,
  no active notifier/preview/sandbox, required sources present and rollback
  image tag matches. Its live read-only check correctly refused while apps ran.
  Backups include editable `GPT-2-tools`, old runtime/image tag, secrets privately,
  all app state, monitor state, effective configuration and maintenance checkpoints.
  Owner-run read-only SQLite quick checks precede private archives; archive
  hashes/listing and fsync of files/final manifest/directories precede success.

No deployed application, interpreter, image tag, OS package, launcher or unit
has changed at this preparation checkpoint. No real model call, generation or
email occurred. Inactive staging/test artifacts and the private preparation
checkpoint are the only host changes. Repository-only scripts and evidence do
not constitute a deployed software update.

## Immediate next sequence

Give Mike the promised heads-up before first gate. Use the staged helper:
`gate-public`, `gate-lab --owner-idle`, `stop-lab`, then
`stop-public --timeout 1200`. The helper operation lock prevents parallel calls.
Public result retrieval remains available for at least 600 seconds of continuous
idle; private gate requires 60 seconds of actual quiescence despite owner consent.
Then run existing Astra/Arcturus `down` helpers sequentially, verify every stopped
checkpoint, and run the staged backup helper. Save a separate drain/backup record
with actual outcomes. Pause for Mike's fresh snapshot before any installation.

Keep downtime bounded by coordinating at each prompt; do not silently continue
through the snapshot checkpoint, reboot, runtime promotion or public reopening.
If draining/backup fails, report the exact state and recovery path, retaining
checkpoints rather than forcing shutdown or resetting application data.
