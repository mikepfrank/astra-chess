# Hourly new-game email notifications

The independent operator monitor checks the saved game list once per hour and
sends one plain-text email only when it finds new game IDs. It uses Python's
standard library, no LLM, no tactical search and no additional installed mail
server. It runs as `astra` on Lightsail even when the development laptop is off.
This is a new-game notification, not a page-visit tracker or a model-usage alert.

The sender is [`tools/ops/notify_new_games.py`](../tools/ops/notify_new_games.py).
The scheduler templates are [`astra-game-notify.service`](../deploy/astra-game-notify.service)
and [`astra-game-notify.timer`](../deploy/astra-game-notify.timer). The timer is
independent of the chess service: installing it does not restart a player's turn.

## Delivery contract

- Initialize once to record existing game IDs without emailing historical games.
  Games created after that baseline are eligible, including games that end
  before the next check. Matching uses IDs, not a timestamp cutoff, so games
  created at the same timestamp are not lost.
- A new-game digest lists the bounded player display name, human color, creation
  time, current saved status, last move and private game ID. It contains no chat,
  account email, authentication tokens, private reasoning or shared replay links.
  Only the operator-configured recipient receives it; players cannot change the
  recipient, subject settings or mail transport.
- The monitor keeps a private pending message, with stable bytes and Message-ID,
  before SMTP. It advances reported IDs only after the mail server accepts the
  message. Failure retains it for the next hourly attempt.
- SMTP acceptance does not prove inbox delivery. A crash after acceptance but
  before the checkpoint can cause a duplicate retry; this is not exactly-once
  email delivery. A changed recipient/sender cannot silently redirect a pending
  message: restore the intended settings or inspect the queue explicitly.
- At most 100 games and 64,000 encoded message bytes are sent per run. A long
  Unicode digest can use a smaller batch. Remaining IDs stay eligible for later
  runs, and the message reports the backlog count.
- No-news runs send nothing. The hourly calendar timer has up to 60 seconds of
  jitter and catches up once after downtime. A process lock prevents overlap.
  Notifications do not change games, clocks, replay visibility or token budgets.

## Mail provider

The September 12 setup recommends Amazon SES for dedicated site sending and
possible future password-reset mail. The operator must verify a sender and,
while SES is in its sandbox, the notification recipient. A verified domain
allows addresses on that domain to send without individual mailbox verification.
SES identities and SMTP credentials are region-specific; this deployment uses
US West (Oregon), `us-west-2`.

Follow the official [identity verification](https://docs.aws.amazon.com/ses/latest/dg/creating-identities.html),
[sandbox limits](https://docs.aws.amazon.com/ses/latest/dg/request-production-access.html)
and [SMTP credential setup](https://docs.aws.amazon.com/ses/latest/dg/smtp-credentials.html).
Use dedicated sending credentials, not an AWS root key or the chess API key.
The SES SMTP password is different from an AWS secret access key. Sending only
to a verified operator does not require production access; password resets to
arbitrary players would require a later production-access request. Do not enable
optional dedicated IPs or deliverability add-ons merely for this small monitor.

The generic example uses SES on port 587 with required STARTTLS. The tool also
supports implicit TLS and a local sendmail executable if an operator already
has one. It refuses plaintext SMTP. Configuring this monitor does not enable
the application's separate password-reset email settings.

The September 12 SES setup used the Essentials plan. Leave the optional custom
MAIL FROM domain blank for this setup. Virtual Deliverability Manager was
included and enabled, with engagement tracking and automatic validation off;
optimized shared delivery stayed enabled. Skip dedicated IPs and tenant setup.
These selections do not replace identity
verification or prove that the monitor can deliver mail.

Verify both the operator recipient and the sending domain in the same SES
region. For a domain hosted in GoDaddy DNS, download the SES DNS-record CSV,
then convert the required records into BIND zone text saved with a `.txt`
extension before using GoDaddy's import. The CSV is not the zone file accepted
by that importer, and its upload rejected the `.zone` extension as an invalid
media type while accepting a byte-identical `.txt` copy. Preserve existing DMARC
policy and website records; review
the proposed records before import and add only the required SES records.
Wait for SES to confirm the identities before attempting the mail test.

In the SES SMTP credential selector, choose the IAM user option and create a
dedicated sending user. Download the credential CSV privately: its `SMTP user
name` and `SMTP password` fields supply the monitor's SMTP credentials; the
separate `IAM user name` is not the SMTP login. Keep this CSV outside Git and
application data, and never print its rows into a terminal, chat or tool output.
Transfer the resulting JSON configuration over an encrypted channel through
standard input to an installer that writes the private mode-0600 file. Do not
put credential values in command arguments or environment variables, enable
command tracing, or echo the configuration during transfer. Write UTF-8 JSON
without a byte-order mark and report only a sanitized installation result.

## Configure and initialize

On the host, working as `astra`, keep configuration and state outside the
application's writable data tree:

```sh
cd /home/astra/astra-chess/web-service
umask 077
mkdir -p /home/astra/.config/astra-chess-monitor
mkdir -p /home/astra/.local/state/astra-chess-monitor
chmod 700 /home/astra/.config/astra-chess-monitor /home/astra/.local/state/astra-chess-monitor
```

Initialize before enabling delivery. This requires no SMTP configuration and
refuses to overwrite an existing baseline:

```sh
env -u OPENAI_API_KEY -u CODEX_API_KEY .venv/bin/python tools/ops/notify_new_games.py \
  --data-dir /home/astra/.local/share/astra-chess \
  --state-dir /home/astra/.local/state/astra-chess-monitor --initialize
```

Copy [`notification-config.example.json`](../deploy/notification-config.example.json)
to `/home/astra/.config/astra-chess-monitor/config.json`, then supply the real
operator recipient, verified sender and SMTP credentials privately. The file
must be owned by `astra`, mode 0600. Do not paste a password into a shell command,
chat, Git, an HTTP URL or a screenshot. The example's placeholders are not a
working configuration; leave the timer disabled until delivery is tested.

Preview without sending or advancing state:

```sh
env -u OPENAI_API_KEY -u CODEX_API_KEY .venv/bin/python tools/ops/notify_new_games.py \
  --data-dir /home/astra/.local/share/astra-chess \
  --state-dir /home/astra/.local/state/astra-chess-monitor \
  --config /home/astra/.config/astra-chess-monitor/config.json --dry-run
```

Preview output contains private game details; do not commit it. Ordinary scheduled
output contains only delivery counts or sanitized errors. Failed-delivery errors
do not print transport responses, credentials or message contents.

## Install and operate the timer

An administrator installs the two small system units; their process runs as
`astra`, with account-local source/configuration/state and the existing Python
runtime. No `cron`, MTA, user-login session or Codex automation is required.

```sh
sudo install -m 0644 deploy/astra-game-notify.service /etc/systemd/system/
sudo install -m 0644 deploy/astra-game-notify.timer /etc/systemd/system/
sudo systemd-analyze verify /etc/systemd/system/astra-game-notify.service /etc/systemd/system/astra-game-notify.timer
sudo systemctl daemon-reload
```

After configuration, a successful test email and exact-unit validation:

```sh
sudo systemctl start astra-game-notify.service
sudo systemctl enable --now astra-game-notify.timer
systemctl list-timers astra-game-notify.timer --no-pager
sudo journalctl -u astra-game-notify.service -n 30 --no-pager
```

An empty interval produces no email, so use a clearly identified synthetic test
message to verify delivery without fabricating a production game or editing the
baseline. The module's `load_config()` and `handoff()` support that operator test;
it does not advance notification state. Do not call handoff outside an explicitly
authorized email operation.

Stop notifications with `sudo systemctl disable --now astra-game-notify.timer`.
An already-running send may still complete; also stop `astra-game-notify.service`
when necessary. Preserve `state.json` across updates, restarts and host migration;
deleting/reinitializing it can skip or repeat notifications. A failed timer action
is diagnosed through the journal and retried on the next hourly activation.
Changing the mail recipient with a pending batch requires deliberate queue review.

## Filesystem and process boundaries

The monitor opens SQLite with `mode=ro` and `PRAGMA query_only=ON`, and closes
the read transaction before SMTP. SQLite WAL sidecars can be absent between
application transactions. A fully read-only directory then prevents even a reader
from opening the database; a September 12 disposable Lightsail check reproduced
this. The unit therefore permits SQLite sidecar creation/locking in the data
directory while mounting `astra.sqlite3` itself read-only. It hides the private
player/query/replay/operator-check subdirectories. Never substitute `immutable=1`
or copy only the database file while a writer is active.

This is a trusted operator utility with read-only SQL access, not a guarantee
that the containing directory cannot change filesystem metadata. Stop the timer
and oneshot alongside the application before replacing/restoring its database,
so no monitor retains a mount of the old inode. Routine code-only updates that
leave the database inode intact do not require a game-service restart.

Mail settings are mounted from one private home file, outside the game service's
filesystem view; the monitor never loads `service.env` or the Codex runtime.
Linux dump protection is set before opening configuration or state, and core
dumps are disabled. Its writable state directory is also hidden from the game
service. Limits are 128 MB memory, 10% aggregate CPU, 16 tasks and 120 seconds per
run. These restrictions reduce exposure, but two trusted programs sharing the
same Unix UID are not completely isolated from one another.

## Verification

```sh
.venv/bin/python -m unittest discover -s tests -p test_new_game_monitor.py -v
```

The focused tests cover baseline/no-news, same-timestamp game IDs, privacy and
header validation, pending retry bytes, successful/failed checkpoints, dry-run,
overlap locks, Unicode size limits, recipient changes, SMTP TLS ordering,
sendmail arguments and Linux dump protection. They send no real email.
Before enabling a new installation, also verify the actual systemd namespace
with absent and active WAL sidecars, private file visibility, game-record
preservation and a real mail handoff to the intended operator.

### September 12 Lightsail preparation checkpoint

Source revision `4b32c87` was pushed and synchronized. All 13 focused tests
passed on Windows, then all 13 passed in a private Linux staging directory.
The unit templates passed the host's systemd 252 verifier. Its unrelated
pre-existing `acpid.socket` legacy-path warning did not invalidate the units.

Both system units were installed, with the timer **disabled pending SES setup**.
Initialization recorded 20 existing database game IDs, including historical QA
games, as the baseline. A dry run with dummy mail settings passed in a copy of
the exact service namespace; it sent nothing and advanced no reporting state.
Separate disposable probes passed for absent and active SQLite WAL sidecars.
The application's mount namespace could not see the mail settings or monitor
state. Temporary check units/configuration were removed and their writer exited.
The game service retained its PID and healthy response throughout installation.

No real SMTP configuration or delivery was tested at this checkpoint. The
operator is completing Amazon SES verification separately. Do not infer that
notifications are running from the presence of installed files; verify the
timer's enabled/active state and a real mail handoff after credentials are set.

### September 12 SES activation checkpoint

The operator verified the recipient and sending domain in SES US West (Oregon).
All three Easy DKIM CNAMEs matched the downloaded records on both authoritative
DNS servers. The existing DMARC record was preserved. SES remains in its
sandbox, which is sufficient for this verified-recipient notification flow.

Dedicated IAM SMTP credentials were transferred through encrypted SSH standard
input into an `astra`-owned mode-0600 JSON file, in a mode-0700 directory outside
the repository and game data. Neither credentials nor the downloaded CSV were
added to Git. The live game service's mount namespace could not see the mail
configuration or the monitor's private reporting state.

At 20:39 UTC, SES accepted a clearly labeled synthetic test email from a
temporary copy of the exact notification service namespace. The test left the
20-ID baseline unchanged. At 20:41 UTC, the actual notification service sent
its first digest containing one new game, exited successfully, and advanced
the checkpoint to 21 reported IDs with no pending batch. The operator then
confirmed receiving both the test and the one-new-game notification. This
confirms receipt for these messages, not a guarantee of future inbox placement.

`astra-game-notify.timer` was then enabled and active, scheduled hourly with up
to 60 seconds of jitter; its next scheduled run at this checkpoint was 21:00:46
UTC. Temporary test units/scripts were removed. The game service retained its
existing PID and start time and continued returning a healthy response.
No game state, model configuration, or password-reset SMTP settings changed.

This activation exercised the installed mail path and durable first-digest
checkpoint; the prior 13-test Windows/Linux runs remain the unit-test evidence.
The setup documentation was updated without changing the sender implementation.
Always refresh live timer/state status instead of treating this dated snapshot
as proof that delivery continues to work indefinitely.
