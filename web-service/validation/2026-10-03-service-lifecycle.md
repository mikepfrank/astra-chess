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
43 existing monthly-budget checks). Linux tests, read-only preflight and
installation checks are pending. A mocked cycle/read-only check does not claim
a completed live shutdown/startup cycle.
