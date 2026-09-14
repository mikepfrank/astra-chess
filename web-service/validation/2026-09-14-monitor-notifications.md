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

Linux namespace/delivery validation, operator-access activation and final timer
verification are pending. Record the resulting private receipts and live
verification here before declaring activation complete.
