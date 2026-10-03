# Stop and resume Arcturus for a Lightsail host migration

Use these installed entrypoints from the `ec2-user` shell. They use existing
sudo access, the system Python standard library and the existing application
environment. No packages or sudoers changes are required.

```sh
# Read-only readiness check; no service changes or paid requests.
~/arcturus-down.sh --check

# Before stopping the instance and taking its final snapshot:
~/arcturus-down.sh

# After migration, on the replacement instance:
~/arcturus-up.sh
```

`--check` also works with `arcturus-up.sh`. The default drain/startup timeout is
1800 seconds; override it with `--timeout 1800` (minimum 35). Shutdown waits for
30 **continuous** quiet seconds. A busy sample resets that interval. Unfinished
games may remain saved; they do not have to reach a result before migration.
Never take the final snapshot unless shutdown reports success.

## Scope and persistence

The helper controls `or-chess.service` and `or-chess-game-notify.timer`.
It allows an existing notification job to finish rather than stopping it.
Application inventory and budget validation run as `or-chess`; Caddy adaptation
and validation run as **astra**, because the proxy remains Astra-owned.

Both direct Arcturus routes, `arcturuschess.com` and
`arcturus.astraplayschess.com`, enter maintenance together. The
`www.arcturuschess.com` redirect and all Astra blocks remain unchanged. Both
maintenance routes must return the expected marker over HTTPS. Unexpected extra
routes to port 8792, complex blocks or independently changed blocks are refused.

The service-specific operation lock and durable checkpoint live under
`/var/lib/arcturus-chess-ops/` (root-owned, mode 0700). The checkpoint records both
original site blocks, application identity and original boot/timer settings.
Proxy editing uses the **same** `/run/lock/astra-caddy-config.lock` as Astra's
helpers. Neither helper should run concurrently with manual proxy edits or
older deployment tools that do not honor that lock.

Shutdown closes both public routes, then stops/disables the notification timer
and disables application boot startup without stopping the running app yet. It
waits for no queued/active responses (including compaction and post-game chat),
replay builds, reserved tokens, worker descendants or notification activity.
It rechecks the gate, process identity, activity and notifier before stopping
the app. There is no force-stop fallback on errors, timeout or Ctrl+C.

Startup keeps both routes gated until the app passes direct health checks for
both Host names. It restores only Arcturus's saved blocks into the **current**
Caddyfile, checks HTTPS health for both names, and restores the original
application/timer boot settings and timer activity. It never restores a whole
historical Caddyfile, rewrites games, changes credentials, resets a budget, or
starts Astra. The existing version-3 monthly budget ledger must validate before
either operation; this check imports its local reader without fetching usage.
No model or email test requests are sent.

Shared Caddy has `admin off`, so entering/leaving maintenance briefly restarts
`astra-caddy.service`. This interrupts proxy connections but does not stop
either application's work. The retained Astra readiness fix polls for actual
HTTPS readiness for up to 30 seconds after each proxy restart, including
rollback; systemd `active` alone is not proof that HTTPS is listening.

## Errors and recovery

A drain timeout leaves Arcturus running behind maintenance, app/timer disabled
for reboot, with its checkpoint retained. Rerun `arcturus-down.sh` to keep
waiting or `arcturus-up.sh` to reopen. Startup-health failure leaves maintenance
in place. A proxy change failure attempts a scoped rollback and verifies HTTPS
readiness again. An error restoring timer settings after reopening retains the
checkpoint so a second startup command can finish without restarting the app.

Do not delete the checkpoint to bypass a refusal. Unexpected proxy changes,
failed notifier jobs, changed application identity during drain, missing budget
state or unreadable activity require inspection. Successful startup retains a
completed private audit and removes only the active checkpoint. Exit codes are
0 success, 1 operational refusal, 2 bad arguments and 130 interruption.

```sh
~/arcturus-down.sh --check
sudo systemctl status or-chess.service or-chess-game-notify.timer astra-caddy.service
sudo journalctl -u or-chess.service -u or-chess-game-notify.service -n 80 --no-pager
```

Keep journal output private; it can contain player information.

## Snapshot and cutover checklist

These helpers prepare the service; they do not create a snapshot or migrate the
host. Astra was already stopped with its own helper when these scripts were
prepared. Leave it stopped until its separate startup is intended.

1. Run Arcturus shutdown and require success. Confirm Astra remains stopped.
2. Stop the old Lightsail instance, then snapshot it and create the larger
   instance from that snapshot. Keep the old instance stopped through cutover.
3. Preserve the full filesystem, ownership and modes, including:
   `/home/or-chess/astra-chess`, `.local/share/or-chess` (database and sidecars,
   games, per-game Codex continuations, replay files, version-3 monthly ledger),
   `.local/share/or-chess-runtime`, `.config/or-chess`, `.config/or-chess-monitor`,
   `.local/state/or-chess-monitor`, and `/var/lib/arcturus-chess-ops`.
   Also retain Astra's own checkpoint, shared Caddy configuration/TLS storage,
   installed units and the `ec2-user` entrypoints. Paths beginning with a dot
   here are relative to `/home/or-chess`.
4. Reassign the existing static IP and verify the replacement instance's cloud
   firewall separately. These scripts do not change network rules, DNS or IPs.
5. Confirm the shared proxy is running on the replacement. Run the read-only
   check, then `~/arcturus-up.sh`. Start Astra separately when desired.

The cloned application/timer remain disabled at boot until their startup helper
restores the saved settings. Do not run either site's startup helper on the old
instance as well: two writable copies would diverge and could send duplicate
notifications. Startup accepts new host process IDs; shutdown still requires
its original process identity to remain stable while draining.

## Installation and validation

The source is in this branch's `web-service/tools/ops/`. After installing the
reviewed commit at `/home/or-chess/astra-chess`:

```sh
sudo install -o ec2-user -g ec2-user -m 700 \
  /home/or-chess/astra-chess/web-service/tools/ops/arcturus-down.sh /home/ec2-user/arcturus-down.sh
sudo install -o ec2-user -g ec2-user -m 700 \
  /home/or-chess/astra-chess/web-service/tools/ops/arcturus-up.sh /home/ec2-user/arcturus-up.sh
```

The wrappers invoke the fixed helper path through `sudo -n /usr/bin/python3 -I
-B`; `ec2-user` need not traverse the application's private home itself.

```sh
python -m unittest discover -s tests -p test_arcturus_service_lifecycle.py -v
```

Tests use a fake host and never call real systemd, change the deployed proxy or
send API requests. See the [validation record](../../validation/2026-10-03-service-lifecycle.md)
for current results and installation evidence. A passed read-only preflight is
only a snapshot; it does not reserve idle time or prove a real stop/start cycle.
