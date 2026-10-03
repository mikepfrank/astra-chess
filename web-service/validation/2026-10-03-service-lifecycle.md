# October 3: Arcturus migration lifecycle helpers

Requested: prepare/install `arcturus-down.sh` and `arcturus-up.sh`, but leave
actual invocation to Mike for his Lightsail host upgrade. The reference is the
separate hosted Astra worktree at `90e778dcccdbf70f07a21962b8f1afdd20d9afb0`,
including its proven 30-second HTTPS readiness retry after proxy restart.

Read-only discovery confirmed installed Arcturus `7f27840`, active PID 83871,
enabled/active notification timer, and inactive notification service. Astra was
already inactive/disabled with its timer inactive/disabled; its maintenance
checkpoint was in phase `stopped`. Shared Caddy PID was 466253.

Adaptation preserves both independent services. Arcturus has two direct routes
to 127.0.0.1:8792, both gated atomically and probed over HTTPS. Caddy validation
still runs as `astra`; inventory and v3 budget validation run as `or-chess`.
The saved maintenance map contains only Arcturus's two blocks. Current other
blocks (including Astra maintenance/www redirects) survive reopening/rollback.
App/notifier boot settings are retained. A 30-second stable drain covers worker
state, reservations, replay builds, all app descendants and notifier activity.
Final identity/activity/notifier checks precede stop; errors never force-stop
work. Startup handles changed host PIDs and restores previous timer settings.

No application/game logic, systemd units, credentials or budget policy changes
are part of this update. The operation uses no provider requests. Runtime files
stay private; scripts do not initialize/migrate/modify the monthly ledger or
copy/restore game state. The lifecycle checkpoint is separate from Astra's.

Local regression: 95 tests passed (46 mocked lifecycle, 6 inventory/rehearsal,
43 existing monthly-budget checks). The same 95 tests passed on the staged Linux
checkout at exact commit `1cc6b2a91429d11182bc6dc4476d8057566fb909`. Both wrappers
passed Linux `sh -n`. Mocked coverage includes interrupted drains, quiet-interval
reset, second-host gating, alternate upstreams, two workers, orphan notifier
children, missing budget, saved boot settings, changed startup PIDs, scoped
rollback and delayed HTTPS readiness. CLI `--check` refusal does not mutate or
recover a service automatically.

The staged helper's read-only preflight passed on system Python, with current
Caddy validation, both direct/public host health checks, inventory and local
v3 ledger validation. A temporary file with both Arcturus maintenance blocks
also passed Caddy adaptation/validation as Astra. It was removed without ever
installing it or restarting Caddy.

Installed the additive operator code/documentation by a clean fast-forward,
without a runtime restart. Installed both `/home/ec2-user/arcturus-{down,up}.sh`
wrappers owned by ec2-user, mode 0700, with exact byte equality to the tracked
source. Executed **only** `--check` through each installed wrapper as ec2-user;
both passed. No actual shutdown/startup action, provider call or email test was
performed, and `/var/lib/arcturus-chess-ops/maintenance.json` remains absent.

Before/after comparisons confirmed all sampled unit states/identities unchanged:
Arcturus PID 83871, Caddy PID 466253, Astra inactive/disabled, its notification
timer inactive/disabled, and Arcturus timer active/enabled with notifier inactive.
SHA-256 comparisons confirmed the current Caddyfile, Astra maintenance
checkpoint, v3 budget, private app/notifier configuration and notifier state were
unchanged. Private receipts are retained under
`/home/or-chess/ui-staging/1cc6b2a/web-service/var/` as
`lifecycle-preflight.json` and `lifecycle-install.json`.

A mocked cycle/read-only check does not claim a completed live shutdown/startup
cycle. Mike retains control of those actual actions before/after the snapshot.
