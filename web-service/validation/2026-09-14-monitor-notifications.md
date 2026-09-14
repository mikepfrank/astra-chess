# Both-site monitors and Arcturus alerts, September 14, 2026

## Initial live inspection

The original Astra operator binding remains active on the existing protected
operator account. The signed-in browser monitor showed 18 player games,
8 finished and 10 unfinished, at 21:33 UTC; seven known deployment fixtures were
excluded. Its hourly `astra-game-notify.timer` was enabled and waiting, with the
latest run at 21:00:52–21:00:54 UTC reporting success. Its independent notification
checkpoint contained 25 reported IDs and no pending message. No original-site
configuration or baseline change was needed.

Arcturus already served the monitor shell and authorization implementation, but
had no configured operator account or notification scheduler. Its existing
protected Dr. Thanos account was identified through the previously confirmed
live game's owner, rather than display-name matching. The initial browser
request was anonymous and correctly showed the sign-in page. Operator IDs and
fixture IDs belong only in private runtime configuration.

## Prepared changes and checks

Separate Arcturus notifier unit/timer templates use the existing standard-library
sender and SES transport, with a private Arcturus configuration and reporting
state outside game data. Its sender is `notifications@arcturuschess.com`, with
Arcturus subject/body branding and the already authorized operator recipient.
The timer runs hourly at five minutes past, with up to 60 seconds of jitter;
the original Astra hourly schedule remains unchanged. Runs with no new games
send no mail. Existing Arcturus games were baselined once without sending a
historical digest. The initial baseline contained 14 game IDs.

The unit never loads the game service's environment or model keys. It mounts
the actual SQLite database read-only, permits SQLite sidecar metadata work,
and hides private player/replay directories and OpenRouter budget files. It
uses the existing 128 MiB, 10% CPU, 16-task notifier limits. The game's own
two-worker, Max-reasoning configuration is unchanged.

Windows checks passed: 7 operator-monitor tests, 6 operator-report tests,
20 notification tests and 4 new notifier-unit tests. The intercepted browser
suite also passed authorization handling, escaped player names, filtering,
replay status, visible-only 30-second polling, nonoverlapping refreshes, stale
recovery, logout clearing, mobile/desktop layouts and safe sign-in return.
These checks used synthetic data and sent no mail.

## Linux namespace and delivery validation

The staged Arcturus notifier unit passed an isolated transient-service check
using its own namespace and resource settings. The actual game database could
be read through the ordinary `mode=ro` inventory connection, while opening its
main file for writing was denied. Separate disposable databases exercised both
absent WAL sidecars and an active WAL connection: both snapshots were readable,
their main database files remained read-only, and their main-file bytes were
unchanged. The fixtures did not create or modify any actual game.

The notifier could not read the game service environment, private player/replay
directories or budget files, and no model credential appeared in its process
environment. A separate check entered the running game service's actual mount
namespace and confirmed that the mail configuration and notification state
were not readable there. `America/Chicago` timezone loading passed. Kernel
limits matched the unit: `cpu.max=10000 100000`, `memory.max=134217728` and
`pids.max=16`.

After those checks, the existing `load_config`/`handoff` delivery path sent
exactly one synthetic message to the authorized operator recipient with subject
**Arcturus monitor activation TEST - no action required**. SMTP accepted it;
inbox receipt has not yet been confirmed. This message reported no actual new
games. The 14-ID notification baseline remained byte-for-byte unchanged, and
all three live service PIDs were unchanged throughout the check. The transient
service exited successfully and was cleaned up. Private sanitized receipts are
in the notifier state's `activation-check-20260914` directory; the attempt
marker prevents silently repeating the test delivery.

## Operator-access activation

Commit `898cba7` was activated after 42 focused Linux checks passed. The private
`monitor-access-20260914T214823Z` maintenance backup and activation receipt record
that all 14 saved game documents, all database table contents and private data
files were preserved. Only the Arcturus application restarted; original Astra
and Caddy processes were unchanged. The existing protected Dr. Thanos account
is the Arcturus operator, with three known deployment fixtures excluded from
its monitor. No password or immutable operator identifier is published here.

The signed-in board displayed the Monitor link. At 21:49:21 UTC, its authenticated
monitor showed 11 player games: one finished, ten unfinished, and zero active
responses. This is a dated snapshot, not evidence that those unfinished players
were online. Max reasoning, two-worker concurrency and game clock policy were
unchanged by monitor activation.

The original signed-in Astra page refreshed successfully at 21:50:14 UTC and
still showed 18 player games (8 finished, 10 unfinished). Final public HTTPS
checks on both canonical hosts returned 200 for `/health` and `/monitor/`, and
401 for anonymous `/api/operator/games`. Both monitor shell and private API
responses carried `Cache-Control: no-store`.

## Scheduled alerts activated

At 21:50:18 UTC, the tracked Arcturus notifier service and timer were installed
and passed `systemd-analyze verify`. An ordinary manual notifier run completed
with exit status zero; the reporting checkpoint still contained the same 14
IDs and no pending message. No historical or duplicate test digest was sent.
The timer was enabled, active and waiting, with its next run scheduled for
22:05:33 UTC at that snapshot.

The original Astra timer remained enabled, active and waiting. Its most recent
run completed successfully at 21:00:52–21:00:54 UTC, and its next run was
scheduled for 22:00:46 UTC. Original-site mail configuration and unit files were
byte-for-byte unchanged. All three game/Caddy process IDs were unchanged by
notifier installation. The private `activation-check-20260914/timer-activation.json`
receipt records these checks.

Both sites now have active operator monitors and scheduled new-game alerts.
The Arcturus SMTP activation test was accepted, but recipient inbox confirmation
and its first scheduled run after activation have not yet been observed.
