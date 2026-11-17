# OS security checkpoint complete — November 16, 2026

**Paused after the OS stage, as requested.** All four application services and
both chess notification timers remain stopped/boot-disabled, behind verified
maintenance gates. Do not run the reopening helpers yet. Application runtime,
certifi, Caddy and GPT-2 image candidates are still inactive; integrated
regression testing and reopening remain subsequent stages.

Mike confirmed completion of the stopped-instance manual Lightsail snapshot
`MPF_Lightsail_16GB-pre-security-2026-11-16` and restarted the same instance.
His console screenshot identifies `MPF_Lightsail_16GB` and attached static IPv4
`16.145.194.176`. SSH reconnected to that host. The pre-update backup at
`/var/backups/chess-security/20261116T232418Z` remains complete and root-private.

## Completed work and evidence

Before installation, all four apps/timers and their saved stopped checkpoints
were rechecked after the snapshot restart. All five scoped maintenance gates
passed; 274 staged RPM sizes/checksums matched their reviewed manifest. The
pinned transaction still proposed 252 upgrades and 22 installs, 395 MB.

`dnf --releasever=2023.12.20261112 upgrade --assumeyes` completed with exit 0
from 00:21:04 to 00:25:06 UTC November 17 (6:21–6:25 p.m. November 16 Chicago).
A root-owned systemd oneshot supervised it independently of SSH. Updating
D-Bus disconnected the `systemd-run` waiting client, but the installation
continued normally; its persistent result and final `Complete!` were checked.
Root-private execution log, wrapper and result remain in
`/var/log/chess-security-20261116/`.

SSH configuration syntax passed before reboot. The reboot was scheduled at
00:25:38 UTC, and SSH reconnection verified the new kernel at 00:26:26 UTC.
The old kernel versions remain installed for recovery.

| Component | Verified installed version |
|---|---|
| Amazon Linux | 2023.12.20261112 |
| Booted kernel | 6.1.190-237.442.amzn2023.x86_64 |
| SSM Agent | 3.3.5828.0-1.amzn2023 |
| System OpenSSL | 3.5.8-1.amzn2023.0.4 |
| OpenSSH server | 9.9p1-16.amzn2023.0.1 |
| System Python 3.12 | 3.12.16-2.amzn2023.0.1 |
| Docker / containerd / runc | 25.0.18 / 2.3.7 / 1.4.3 |

[Post-reboot verification](post-reboot-verification.json) records:

- All 274 reviewed package names/versions/releases/architectures installed.
  DNF automatically cleared its downloaded RPMs after success; the retained
  checksum manifest supplies the comparison. Do not expect the old download
  directory to retain those RPMs for future verification.
- No failed systemd units. SSH, SSM, Caddy, Docker/containerd and the private
  lab's network setup unit active. Four apps and two timers inactive/disabled;
  notifier jobs and preview inactive. All maintenance gates return their
  correct 503 markers.
- Private lab network remains internal, IPv4-only, exact 172.30.97.0/24 bridge
  with gateway .1 and inter-container communication disabled. Its source hook
  is the first INPUT rule; its scoped chain allows TCP 8902 then drops traffic.
  No sandbox containers run; the production image remains the original
  `9d9274de90e73ba2e215935f0dfbd09eb5c2fe248ba7a6b3052e45969de496fb`.
- Eleven launcher/seccomp/sudoers/proxy/admission/checkpoint files match the
  private backup in contents, type, owner/group and permissions. Sudoers syntax
  passes; Astra's independent new-game pause is preserved.

[Package checks](package-checks.json) record a refreshed pinned-release
`check-update` with no packages, zero available security advisories, successful
`dnf check`, RPM database verification and SSH syntax validation. This means
the reviewed OS release is current for its installed packages, **not** that
private runtimes, embedded binaries or Docker image contents are fully updated.

The transaction preserved the original SSH configuration byte-for-byte and
left the new vendor default as `/etc/ssh/sshd_config.rpmnew`; account-specific
key/CA integration was retained. Effective password, keyboard-interactive and
empty-password authentication are disabled; key authentication works. A
nonfatal restorecon warning named `/usr/lib/sysimage/rpm`, while this host's
actual RPM database is `/var/lib/rpm`; database/dependency verification passes.
SELinux remains Permissive. No security policy was relaxed by this maintenance.

The [read-only verifier](../../tools/ops/verify_os_security_20261116.py) received
an independent review, syntax checking and a successful live run. Its initial
RPM inventory assumptions were corrected for DNF cache removal and this host's
`curl-minimal` package. Its network checks prove configuration/state only;
container network behavior, nested sandboxing and application functionality
remain for the runtime/regression stage. No model calls or email tests ran.

## Next stage

Resume the [activation runbook](../2026-11-15-security-stage/maintenance-runbook.md)
at step 4 and the [GPT-2 checklist](../2026-11-16-security-prep/gpt2-activation-checklist.md)
at candidate re-verification/testing. Preserve existing fixture results before
rerunning the GPT-2 suites against the newly updated OS Python/OpenSSL.
Promote the tested private Python/venv, certifi, Caddy and container candidates
in controlled steps, validate behind the gates, then report/pause before public
reopening. Codex CLI promotion remains a separately audited compatibility stage.
Do not reset ledgers, change model settings, lose paused inputs or open Astra
new-game admission. The `up` helpers immediately reopen after basic health,
so richer regression tests must precede them.

## Automatic snapshots recommendation

Recommend enabling daily automatic snapshots at a quiet time. AWS retains the
[seven latest daily snapshots](https://docs.aws.amazon.com/lightsail/latest/userguide/amazon-lightsail-configuring-automatic-snapshots.html).
[Snapshot storage is $0.05/GB-month, with successive snapshots charging for changed data](https://docs.aws.amazon.com/lightsail/latest/userguide/amazon-lightsail-frequently-asked-questions-faq-billing-and-account-management.html);
it is not seven full 320-GB copies. For illustration, 100 GB of retained snapshot
data costs $5/month, plus retained changes; actual cost depends on block churn.
The host's pre-upgrade filesystem used 88 GiB, which is not an exact billable
snapshot-size forecast. Keep the manual pre-update snapshot through successful
regression testing. Running-instance automatic snapshots supplement consistent
application backups; [AWS recommends stopping for snapshot consistency](https://aws.amazon.com/lightsail/faq/).
No AWS snapshot schedule or other AWS configuration was changed by this stage.
