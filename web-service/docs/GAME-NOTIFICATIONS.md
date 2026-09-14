# Hourly new-game email notifications

The independent operator monitor checks the saved game list once per hour and
sends one plain-text email only when it finds new game IDs. It uses Python's
standard library, no LLM, no tactical search and no additional installed mail
server. Each installation runs under its own Lightsail account even when the
development laptop is off.
This is a new-game notification, not a page-visit tracker or a model-usage alert.
The original Astra scheduler and the separately configured Arcturus scheduler
have independent databases, recipients, private configuration and checkpoints.
The dated checks at the end distinguish earlier staged mail tests from actual
activation.

The sender is [`tools/ops/notify_new_games.py`](../tools/ops/notify_new_games.py).
The scheduler templates are [`astra-game-notify.service`](../deploy/astra-game-notify.service)
and [`astra-game-notify.timer`](../deploy/astra-game-notify.timer), with separate
[`or-chess-game-notify.service`](../deploy/or-chess-game-notify.service) and
[`or-chess-game-notify.timer`](../deploy/or-chess-game-notify.timer) templates for
Arcturus. Each timer is
independent of the chess service: installing it does not restart a player's turn.

Alternate deployments can set `site_name` (for example, `Arcturus chess`) in
their own private monitor configuration. The default remains `Astra chess`;
the subject defaults to the site name unless `subject_prefix` is supplied.
An optional bare `feedback_address` supplies the SES SMTP Return-Path header
for forwarded bounce/complaint notices, while the envelope sender remains
`from_address`. Use a monitored, verified operator mailbox during sandbox tests.
SES can rewrite delivered Message-ID and Return-Path headers; submitted values
are not a substitute for checking received authentication and feedback.

Each installation needs separate data/config/state paths and its own baseline.
Changing branding preserves already queued bytes. Changing sender, recipient,
or feedback address refuses a pending send until its existing destination is
restored or the operator explicitly reconciles the queue. Legacy queues without
a feedback address continue unchanged when the new setting is absent.

## Deployment variants

| Setting | Original Astra | Arcturus |
| --- | --- | --- |
| Account | `astra` | `or-chess` |
| Data | `/home/astra/.local/share/astra-chess` | `/home/or-chess/.local/share/or-chess` |
| Private mail configuration | `/home/astra/.config/astra-chess-monitor/config.json` | `/home/or-chess/.config/or-chess-monitor/config.json` |
| Private reporting state | `/home/astra/.local/state/astra-chess-monitor` | `/home/or-chess/.local/state/or-chess-monitor` |
| Timer | `astra-game-notify.timer` | `or-chess-game-notify.timer` |
| Hourly schedule | Top of the hour, plus up to 60 seconds of jitter | Five minutes past the hour, plus up to 60 seconds of jitter |
| Sender domain | `astraplayschess.com` | `arcturuschess.com` |

For Arcturus, use the
[`or-chess-notification-config.example.json`](../deploy/or-chess-notification-config.example.json)
template with its own authorized operator recipient and private SES credentials.
It selects `notifications@arcturuschess.com` and Arcturus subject/body branding.
The five-minute offset avoids deliberately scheduling both sites' digests at
the same moment. Each timer catches up once after downtime; no-news runs remain
silent. Messages do not contain links to either site's private monitor.

The commands below describe the original Astra installation. When setting up
Arcturus, substitute all account, data, configuration, state and unit names
together using the table above. Initialize the new Arcturus state once before
enabling its timer; never copy or reinitialize Astra's existing checkpoint.
Configuring notifications does not enable player verification or password-reset
email in either web application.

Both notification timers were verified enabled and active on September 14 at
21:50 UTC. The Arcturus activation receipt is recorded at the end of this guide;
its SMTP test was accepted by SES, with inbox receipt still unconfirmed.

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

The Arcturus unit additionally unsets `OPENROUTER_API_KEY` and
`CHESS_GATEWAY_TOKEN`, hides the experiment's provider-budget files, and makes
its game service's private `service.env` inaccessible. It never reads that
environment file to obtain mail credentials. Verify these boundaries in the
actual unit namespace before enabling delivery.

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

### September 14 Arcturus staged notification check

Staged code `011c4b8` adds optional `site_name` body branding (default
`Astra chess`) and `feedback_address`, a single monitored mailbox used for the
Return-Path header. `subject_prefix` remains independently configurable and
defaults to the site name. Existing Astra configuration is compatible. A
pending digest keeps its exact saved bytes; a change to its feedback destination
requires deliberate queue review, just like a changed sender or recipient.

Fifty focused Linux mail, identity and monitor tests passed. During the
September 14 **05:38:53–05:40 UTC** operator-only check, a root-private disposable
monitor initialized an empty fixture baseline, observed one synthetic game and
handed off an **Arcturus chess delivery TEST** digest from
`notifications@arcturuschess.com` to Mike's authorized operator address. The
message used Arcturus body branding and the new sender domain for its
Message-ID, with the monitored feedback address set explicitly. SES accepted
the message. The checkpoint advanced once, and the next no-news run sent
nothing. Mike confirmed receiving all three messages from the combined check
and supplied a Gmail screenshot showing them in the inbox. Received-message
authentication headers were not inspected.

The check used the existing operator SMTP credentials in private disposable
storage; the original monitor's configuration, state and service were unchanged.
It opened no actual player database and made no LLM call. Temporary credentials,
accounts and token files were removed after the combined recovery/monitor check.
The private test receipt is under `/var/lib/arcturus-mail-check`; the
[sanitized validation record](../experiments/arcturus-mail-2026-09-14.json)
contains the checkpoint evidence.

At this checkpoint, Arcturus has no installed separate monitor configuration or
notification service/timer, and neither live application has recovery SMTP
enabled, rechecked at **05:41 UTC**, with all three live service PIDs unchanged.
The branding update `011c4b8` was tested only in staging; the live checkout is
`e73d81d`. SES remains in the sandbox, confirmed at **05:31 UTC** with limits of
200 messages/day and one/second. Sending notifications to a verified operator
can work within that sandbox; public recovery needs production access.
Activating Arcturus notifications requires separate `or-chess` configuration,
state, initial real-game baseline and units, plus the same namespace and delivery
checks described above. Do not reuse the original Astra monitor's checkpoint or
enable its timer for the Arcturus database.

### September 14 both-site activation follow-up

A fresh inspection found the original Astra timer enabled and waiting. Its
21:00:52–21:00:54 UTC run completed successfully, and its reporting checkpoint
contained 25 IDs with no pending message. The existing configuration and
checkpoint were preserved.

The separate Arcturus service and timer were activated at **21:50:18 UTC**,
using the already authorized operator recipient and dedicated private
configuration. Initialization recorded 14 existing game IDs without sending
a historical digest. Windows checks passed 20 notification tests and four new
unit-boundary tests, with no real email from those tests. Linux namespace checks
and a clearly identified synthetic SMTP handoff passed; SES accepted the test
message, but inbox receipt has not yet been confirmed.

The installed units passed `systemd-analyze verify`. A manual run of the exact
service completed successfully with no new games, preserving the 14-ID baseline
and leaving no pending message. `or-chess-game-notify.timer` was enabled and
active/waiting, with its next run at 22:05:33 UTC. The original Astra timer stayed
enabled and active/waiting, with its next run at 22:00:46 UTC. These are dated
activation checks, not a promise that a timer remains healthy indefinitely.

All three game/proxy service PIDs remained unchanged during notifier
installation. The original notification units and configuration were preserved.
Both web applications still have recovery SMTP unset: these independent
operator notifications do not enable public verification or password reset.
See the [activation validation](../validation/2026-09-14-monitor-notifications.md)
for the retained receipt and separate private monitor-page activation.
