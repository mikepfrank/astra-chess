# Private game monitor

`/monitor/` shows the operator a current table of player games: player name,
human side, last move, result or waiting state, and saved/shared replay status.
It reads existing records; it does not invoke a model, search the chess engine,
send messages, alter clocks or change games.

## Access and configuration

The monitor uses the same password-account login and cookie as the game site.
Configure `ASTRA_OPERATOR_USER_ID` with the immutable ID of an existing
password-protected account. Leave it empty to disable access. Do not grant
access by matching a display name, by letting users submit an operator flag, or
by including the ID in browser source. A new installation has no default
operator account.

An operator can find the ID by inspecting the local `auth_users` table, selecting
only `id`, `name` and whether `password_hash IS NOT NULL`. Never print password
hashes, session tokens, email addresses or the full service environment merely
to configure the monitor. Put the ID in the service's private environment file.

`ASTRA_MONITOR_EXCLUDED_GAME_IDS` optionally lists known deployment fixture IDs,
separated by commas. These exact games are excluded from the player table and
player totals. Do not classify every name containing `test` as a fixture: such
names can belong to real players. Exclusion does not delete records or modify
the hourly notification monitor's baseline.

The site shows an operator-only **Monitor** link. The monitor's sign-in link
returns through the existing login dialog to this fixed page. It does not accept
arbitrary redirect destinations.

## Privacy boundary

The page shell contains no game data. Its `/api/operator/games` endpoint requires
a valid session for the configured account, and that account must still be
password-protected. Anonymous callers receive 401 and other accounts receive
403. Responses are not cached. A revoked or expired session loses access.

The response uses a small explicit set of report fields. It never includes
conversations, private model reasoning, recovery addresses, passwords, cookies,
user memory, server paths or raw game state. Replay columns describe whether
versions were saved or shared; this does not grant access to another player's
private replay or conversation. The endpoint reads the same SQLite inventory
as the existing [operator report helper](../tools/ops/README.md).

## Refresh behavior and interpretation

The page refreshes every 30 seconds while visible, with a manual refresh button.
Requests have a deadline and do not overlap. Returning to the tab requests a
fresh snapshot. A temporary connection failure leaves the last snapshot visible
and marks it stale; authentication failure clears private data.

Unfinished games are saved game states, not evidence that their players are
online. A suspended game can be resumed. Active response counts describe the
site's AI responses; a human may be away while their game waits for a move. The update time
identifies the snapshot being displayed.

Any daily token figures come from the service's UTC admission ledger and include
cached input. They are not dollar costs. An idle dashboard is not a reserved
maintenance window: gate incoming requests and recheck work before stopping the
application, as described in the [deployment walkthrough](../DEPLOYMENT.md).

## Separate Astra and Arcturus installations

The private pages are [Astra's monitor](https://astraplayschess.com/monitor/)
and [Arcturus's monitor](https://arcturuschess.com/monitor/). Sign in to each
site with its existing password-protected operator account. The domains have
separate cookies, account databases, operator bindings and game inventories;
signing in to one does not sign in to the other. Use Arcturus's canonical domain
for new sessions, even though its older subdomain remains available.

The original Astra binding lives in its private `operator.env` systemd drop-in,
described in the September 12 checkpoint below. Arcturus uses its own
`ASTRA_OPERATOR_USER_ID` and exact fixture exclusions in
`/home/or-chess/.config/or-chess/service.env`. Identify an account through its
known immutable ownership records and confirm it is password-protected; a
display name alone is not authorization. Neither installation changes the
other site's accounts or reporting baseline.

The browser page and the [new-game email notifier](GAME-NOTIFICATIONS.md) are
independent. The page refreshes the current inventory; email checks for newly
created IDs on its hourly schedule. Configuring the page does not send mail,
and enabling notifications does not grant browser access.

## Validation

Use synthetic data for backend authorization, exclusion, response-field and
read-only tests. The intercepted browser check is
`node tests/browser/monitor.cjs`; see the [browser QA guide](../tests/browser/README.md)
for optional tooling. No real game or model action is needed to test this page.

## September 12, 2026 Lightsail activation

Runtime revision `ef626dd` was deployed after the full Windows suite passed
239 tests (two platform skips), 53 focused Linux tests passed, and the monitor
and recovery browser checks passed against synthetic requests. No new runtime
dependencies or paid model calls were required.

The existing operator account is bound in the private, astra-owned 0600 file
`/home/astra/.config/astra-chess/operator.env`, together with the exact known
fixture exclusions. The systemd drop-in
`/etc/systemd/system/astra-chess.service.d/20-monitor.conf` loads that file.
Account and fixture IDs are deliberately absent from this guide.

The proxy and notification timer were paused first. Two idle checks and a
service process-tree check found no workers before the application stopped.
A full private data archive and coherent SQLite backup were saved under
`/home/astra/.local/state/astra-chess-backups/monitor-20260912/`. After startup,
digests of all 15 preexisting non-reset tables, using their original columns,
matched the backup. The proxy and hourly notification timer were then resumed.

Public HTTPS checks confirmed health, no-store monitor responses and anonymous
API denial. The live browser's existing operator login displayed all 14 player
games, with seven known fixtures excluded. No live game, clock, player message
or account was used as a test mutation. Recovery code was installed in this
release, but player recovery mail remains disabled pending the separate
[activation prerequisites](PASSWORD-RECOVERY.md).

## September 14, 2026 both-site verification

At 21:33 UTC, the existing signed-in Astra monitor displayed 18 player games:
8 finished and 10 unfinished, with seven explicit deployment fixtures excluded.
The original operator binding required no change.

Arcturus's protected operator binding was activated at **21:48:23 UTC / 16:48
CDT**, using revision `898cba7`. Three exact known deployment fixtures were
excluded. The refreshed live board displayed the operator-only Monitor link;
backend and synthetic browser authorization checks passed before deployment.
At 21:49 UTC, the signed-in Arcturus monitor displayed 11 player games: one
finished and ten unfinished. The two sites' private pages are now available
through their own operator logins.

The brief Arcturus-only admission gate enclosed the final idle checks, backup,
configuration activation and application restart. All 14 game documents,
database table digests and private files were preserved. The original Astra
and Caddy PIDs stayed unchanged, and the gate restored the exact prior Caddy
configuration. See the
[activation receipt](../validation/2026-09-14-monitor-notifications.md) for
the live inventory and authorization checks.
