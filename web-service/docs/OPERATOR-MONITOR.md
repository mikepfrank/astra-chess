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
online. A suspended game can be resumed. Active response counts describe Astra
work; a human may be away while their game waits for a move. The update time
identifies the snapshot being displayed.

Any daily token figures come from the service's UTC admission ledger and include
cached input. They are not dollar costs. An idle dashboard is not a reserved
maintenance window: gate incoming requests and recheck work before stopping the
application, as described in the [deployment walkthrough](../DEPLOYMENT.md).

## Validation

Use synthetic data for backend authorization, exclusion, response-field and
read-only tests. The intercepted browser check is
`node tests/browser/monitor.cjs`; see the [browser QA guide](../tests/browser/README.md)
for optional tooling. No real game or model action is needed to test this page.
