# Fresh runtime maintenance window — paused for manual snapshot

November 17, 2026. Mike resumed the maintenance flow and asked about a fresh
snapshot. Plan: fresh graceful drains and offline backup, then **pause for
Mike's post-OS/pre-runtime Lightsail snapshot**. Do not activate candidates or
repeat the OS upgrade before that checkpoint. Mike confirmed all private lab
tabs, including paused/embedded pages, are fully closed.

## Drain and backup complete

Around 17:31 UTC, the public GPT-2 generation gate was installed. Its full
600-second continuous-idle result-retention check passed, then it stopped
cleanly. Private GPT-2 passed its strict quiet checks and stopped. Sequential
Astra and Arcturus shutdowns each passed their 30-second quiet intervals.
All four apps and both notification timers are inactive and boot-disabled.
Notifier jobs and GPT-2 preview are inactive, and no private sandbox remains.
The scoped HTTPS maintenance gates passed at 17:48 UTC; see
[sanitized state](stopped-state.json). Preserve all three active checkpoints.

The producer preflight passed and the fresh backup completed in
`/var/backups/chess-security/20261117T174804Z`, exit 0 with `complete: true` after
checksums and fsync. All 821 database quick checks passed (Astra 299, Arcturus
438, private GPT-2 84). Application archive: 11,832,238,080 bytes and 101,160
members; Docker rollback archive: 715,110,912 bytes. See
[sanitized completion and hashes](backup-result.json). Archives, private
configuration and raw maintenance checkpoints remain on-host only.

Fresh read-only checks found both chess apps idle (zero active responses,
replay builds or reserved tokens), public GPT-2 idle, and private lab 18 idle
sessions with six preserved pending human inputs, zero children/containers.
All four apps and Caddy retained their prior PIDs and zero restarts; no failed
units. Root filesystem has 233 GiB available. The GPT-2 live venv remains its
original ordinary directory and production image remains the expected old ID.

Reviewed remote helper hashes match the local versions:

- `/home/ec2-user/chess-security-stage-20261116/ops/gpt2_maintenance-v2.py`:
  `80018c27bb074cd66782b9313346b5033bce808cc0a1058c543b92585b1f7912`.
- `/home/ec2-user/chess-security-stage-20261116/ops/backup_host_security.py`:
  `dba364ed5ab800ab3843d45710a9b9ae36237b82d848609d253027fe8b36f5e7`.

The downtime heads-up preceded gating. GPT-2 prepare created a new private
checkpoint and validated gates without changing traffic. No guard was bypassed
and no pending human input was cleared. Shared Caddy restarted only after public
GPT-2's retention interval finished, through the sequential chess helpers.

## Backup verification

A new read-only verifier was staged beside the unchanged producer:
`/home/ec2-user/chess-security-stage-20261116/ops/verify_host_security_backup.py`,
SHA256 `3482bb8aa764a0940bbbe27cc36d9ce01ed7203144c32a7e59ead3ecd7f146ef`.
It validates root ownership/private permissions, completed manifest and file
sizes, three primary databases, three maintenance checkpoints and Caddyfile
against their archived bytes, plus the Docker tag/configuration digest. It
reuses the exact producer's stopped-state guards before and after verification.
It does not extract files or print private contents. Producer hashes are not
independently recomputed for the full archives, nor are all Docker layers or
other archived files independently byte-compared.

`python -I -B -m unittest discover -s web-service/tests -p "test_*host_security*.py" -v`
passed 19 tests (11 producer guards and 8 verifier tests). Windows tests mock
POSIX metadata; the actual on-host run enforces ownership and modes.

The actual Linux verifier exited 0 with `verified: true`; all seven selected
files matched, artifact sizes matched, and Docker tag/configuration digest
passed. Root ownership/private modes and stopped-state guards passed before and
after. See [verification result](backup-verification.json). No runtime candidate
has been activated. This is the agreed prompt pause for Mike's manual snapshot.

## Manual snapshot handoff — ready now

Mike owns the AWS console step. A fresh snapshot is recommended to preserve the
already-updated OS and current data before runtime swaps; it is not an AWS
prerequisite for installing these updates. Retain the November 16 snapshot and
backup as well. No AWS snapshot or automatic-snapshot configuration is changed
by this helper sequence.

1. Confirm `MPF_Lightsail_16GB` with attached static IPv4 `16.145.194.176`.
2. Stop that instance and wait for Stopped.
3. Create manual snapshot `MPF_Lightsail_16GB-pre-runtime-2026-11-17`; wait for
   completion.
4. Start the same instance, confirm SSH works, and tell Codex. Keep the apps
   disabled/gated until controlled activation and regression checks; do not
   invoke the up helpers yet.

After confirmation, first verify the OS, maintenance checkpoints, stopped
apps/timers, gates, GPT-2 isolation and staged artifact identities survived the
boot. Continue the already-reviewed runtime activation/checklist with pauses
after major stages. Do not repeat the OS update or unlock Astra's new-game
admission policy. Codex CLI migration remains a separate compatibility audit.

AWS references: [snapshot procedure](https://docs.aws.amazon.com/lightsail/latest/userguide/lightsail-how-to-create-a-snapshot-of-your-instance.html),
[stop/start and static IP](https://docs.aws.amazon.com/lightsail/latest/userguide/lightsail-how-to-start-stop-or-restart-your-instance-virtual-private-server.html).
