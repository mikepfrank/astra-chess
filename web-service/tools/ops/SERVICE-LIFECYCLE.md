# Stop and resume Astra for maintenance

These helpers are for the existing Lightsail installation. Run them as
`ec2-user`, using that account's existing sudo access; they do not install new
sudo permissions or require login as `astra`. The shell entrypoints invoke
`/usr/bin/python3 -I -B` as root. Caddy validation and the application inventory
run as `astra`. The source is
`/home/astra/astra-chess/web-service/tools/ops/`.

## Commands

From the `ec2-user` shell, with the entrypoints installed in its home directory:

```sh
# Inspect services and game activity without changing files or services.
~/astra-down.sh --check

# Enter maintenance, wait for accepted work, then stop Astra.
~/astra-down.sh

# Optionally choose a drain timeout in seconds (1800 is the default).
~/astra-down.sh --timeout 1800

# Start Astra, check health, and reopen access.
~/astra-up.sh
```

Use the installed copies in `ec2-user`'s home: that account cannot directly
traverse Astra's private home directory. The wrappers use sudo to reach the
source helper. `--check` also works with `astra-up.sh`. A successful read-only
check is only a snapshot: it does not block new requests, reserve an idle period,
or stop the service.

To install the entrypoints on a prepared replacement host after checking out this
branch (the wrappers have fixed paths to the helper in that checkout):

```sh
sudo install -o ec2-user -g ec2-user -m 700 \
  /home/astra/astra-chess/web-service/tools/ops/astra-down.sh /home/ec2-user/astra-down.sh
sudo install -o ec2-user -g ec2-user -m 700 \
  /home/astra/astra-chess/web-service/tools/ops/astra-up.sh /home/ec2-user/astra-up.sh
```

## What shutdown does

1. Checks the expected systemd units, saved game activity, cgroup v2 process
   state, and supported proxy configuration. Saves a private checkpoint and a
   full Caddyfile backup under `/var/lib/astra-chess-ops/`.
2. Replaces only Astra's main hostname block with an HTTP 503 maintenance
   response. Validates the whole candidate Caddy configuration, applies it,
   and verifies the maintenance response over local HTTPS. Alternate proxy
   routes to Astra's port are refused because they could bypass maintenance.
3. Stops and disables `astra-game-notify.timer`, and disables
   `astra-chess.service` at boot without stopping its current process yet.
4. Waits for a continuous 30-second quiet period: no active or queued AI
   responses (including post-game chat), replay builds, reserved tokens,
   child workers, or running notification job. The default wait is 30 minutes.
5. Rechecks the gate, worker identity, activity and child processes immediately
   before stopping Astra. Verifies the stopped state before reporting that the
   final migration backup may be taken.

Unfinished games need not finish first. Saved boards, clocks, conversations and
Codex continuations remain available when the service returns. The app and
notification timer stay disabled across reboot until the resume helper restores
their saved boot settings.

**Caddy is shared with Arcturus.** These helpers never stop or restart the
Arcturus application or its notification timer. They preserve the other site
blocks. However, Caddy's admin API is disabled on this host, so applying or
removing maintenance requires a brief restart of the shared proxy. Web requests
to both sites can be interrupted during that restart; independently running AI
turns continue.

After each proxy restart, including rollback, the helper gives HTTPS a
30-second readiness window. Caddy's `Type=exec` systemd unit can report
`active` before the HTTPS listener is ready. An initial connection refusal
therefore triggers another probe, not immediate rollback. Only the expected
maintenance marker or a successful health response completes this check.
Individual systemctl calls have their own bounded command timeout.

## Resume and recovery

`astra-up.sh` starts Astra behind maintenance, waits for local health, restores
the saved Astra proxy block, verifies HTTPS health, and restores the previous
app/timer boot settings and timer activity. It does not restore an entire old
Caddyfile, so unrelated site edits made during maintenance are preserved.
Successful completion retains a private audit and removes the active checkpoint.

A timeout or Ctrl+C is not permission to force-stop a worker. The helpers have
no force-stop fallback. Maintenance and a checkpoint may remain after an error;
read the message and inspect the state before proceeding. A drain timeout leaves
Astra running behind maintenance. A startup-health failure leaves maintenance
in place. An early proxy failure attempts to restore the previous proxy block
without stopping Astra; a failure while restoring the timer after reopening
may intentionally leave Astra online with the recovery checkpoint retained.

Rerun `astra-down.sh` to continue draining, or `astra-up.sh` to reopen the service
or finish recovery. Do not take the final data copy until shutdown reports
success. Do not delete the checkpoint to bypass a refusal, particularly if the
Astra proxy block or app process has changed independently.

Useful diagnostics from `ec2-user`:

```sh
~/astra-down.sh --check
sudo systemctl status astra-chess.service astra-caddy.service astra-game-notify.timer
sudo journalctl -u astra-chess.service -u astra-caddy.service -n 80 --no-pager
```

Keep logs private; they may include player data. Exit status is `0` on success,
`1` on an operational failure, `2` for invalid arguments, and `130` for Ctrl+C.

## Coordinate other operators

The helper serializes its own operations and uses
`/run/lock/astra-caddy-config.lock` while editing/applying the shared proxy.
An Arcturus adaptation should cooperate with that same lock. Do not manually
edit or apply Caddy configuration in parallel with either helper. Unexpected
changes are refused, but a lock cannot protect against an operator who ignores
it. Each service needs its own app/timer names, site blocks and checkpoint;
changing only the wrapper's name is insufficient.

## Migration boundary

These scripts do not migrate the host or back up application data. After a
successful shutdown, make a coherent private copy of the full
`/home/astra/.local/share/astra-chess/` tree, including SQLite companion files,
game/query evidence, per-game Codex state and replay files. Preserve private
application configuration, notification configuration/state, and
`/var/lib/astra-chess-ops/` as well. Follow the
[deployment walkthrough](../../DEPLOYMENT.md#operations-updates-and-moving-to-another-host)
for runtime, ownership, TLS and validation requirements.

Keep the old app and timer stopped through cutover. Never let both restored
copies accept player requests or send scheduled notifications. These helpers
assume the existing paths, units and shared Caddy layout; prepare and verify
those deliberately on the new host before using the resume helper there.
Do not replace another service's Caddy configuration or TLS state blindly.

## Validation scope

The 30 fixture-based lifecycle tests passed on both Windows and the Lightsail
host's system Python; the six existing operator inventory/migration tests also
passed on Windows. They check control flow and
refusal/recovery paths without running systemd or changing the deployed service:

```sh
python -m unittest discover -s tests -p test_service_lifecycle.py -v
```

On October 3, 2026, the live read-only `--check` passed with system Python
3.9.25. Caddy validated both the current configuration and a temporary
maintenance candidate; direct and HTTPS health checks passed. The live Caddyfile
and all three service PIDs (Astra, Caddy, Arcturus) remained unchanged. None of
these checks is evidence of a completed live stop/start cycle. Perform the
first actual cycle only when maintenance is intended.

Both wrappers were installed in `/home/ec2-user/` and their `--check` commands
passed. No service was stopped, restarted, enabled or disabled for installation
or validation. No new sudo permissions or packages were installed.

The first user shutdown attempt exposed a proxy-readiness race: an immediate
curl exit 7 caused rollback before the new Caddy process started listening.
Astra and Arcturus retained their original app PIDs. The readiness correction
adds regression coverage for initial connection refusal, delayed readiness,
permanent failure, deadline accounting, and verified rollback. A `preparing`
checkpoint from this early failure can be reused; do not delete it to retry.
