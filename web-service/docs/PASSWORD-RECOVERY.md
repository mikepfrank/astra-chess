# Password recovery and email delivery

Recovery is optional for password-protected accounts. Guest accounts remain tied
to their browser until the player adds a password. An email address is not a
login name and is never supplied to the chess model or included in replays.

## Player flow

- A player may supply a recovery address when registering with a password or
  protecting an existing guest account. The site sends a confirmation link.
- Existing protected accounts can add, change, resend confirmation for, or
  remove a recovery address from **Your account**. These changes require the
  current password. A previously verified address remains usable until a
  replacement is confirmed.
- Confirmation links expire after 24 hours and require an explicit confirmation
  on the site. Loading the page alone does not confirm an address or sign in.
- **Forgot your password?** asks for the player name and sends a one-hour reset
  link only to that account's verified recovery address. Its public response
  does not disclose whether the account exists or email was sent.
- Resetting the password signs out existing sessions and invalidates other reset
  links and pending recovery-address changes. Saved games and player memory are
  retained; sign in again with the new password.

Addresses saved before email confirmation was implemented remain unverified.
The player must sign in and confirm the address before using it for recovery.
No migration silently assumes that an old address belongs to the player.

## SMTP configuration

The game service's SMTP settings are separate from the hourly notification
monitor's private JSON file. Configuring the monitor does not enable recovery.

| Setting | Purpose |
| --- | --- |
| `ASTRA_SMTP_HOST` | Outbound SMTP endpoint; SES Oregon uses `email-smtp.us-west-2.amazonaws.com`. |
| `ASTRA_SMTP_PORT` | `587` for STARTTLS; `465` for implicit TLS. |
| `ASTRA_SMTP_FROM` | Visible sender on the verified domain, such as `accounts@example.com`. |
| `ASTRA_SMTP_USER` | Dedicated SMTP username from the SES credential CSV. |
| `ASTRA_SMTP_PASSWORD` | Dedicated SMTP password, not the IAM user name or an AWS secret key. |
| `ASTRA_SMTP_FEEDBACK_ADDRESS` | Optional monitored address for bounce/complaint notices, supplied as the SMTP message's Return-Path. |

Keep these values in an `astra`-owned mode-0600 environment file in a private
configuration directory. The service manager reads it before hiding the home
directory. Do not put it in the repository, writable game data, worker homes,
command arguments, screenshots, or logs. Codex and tactical subprocesses use
environment allowlists that exclude SMTP credentials. This does not constitute
complete operating-system isolation between processes sharing the same Unix UID.

Use TLS for authentication and delivery. Leave recovery SMTP unset until the
provider is ready to send to ordinary players and the isolated delivery test
has passed. When it is unavailable, the interface should explain this rather
than promise a working recovery channel.

## Amazon SES prerequisites

1. Verify the sending domain and use its DKIM records. Preserve existing website
   DNS records and a valid existing DMARC policy. The operator-notification
   [setup guide](GAME-NOTIFICATIONS.md) records the initial GoDaddy procedure.
2. Request **production access** in the sending region, selecting
   **Transactional** email. Sandbox access permits only verified recipients
   and the SES mailbox simulator; it is enough for an operator test, but not
   general player recovery. Wait for approval before enabling general delivery.
3. In **Suppression list**, confirm account-level suppression is enabled for
   **Bounce and complaints**. Do not override it with a configuration set that
   disables suppression.
4. In the sending identity's **Notifications** settings, keep **Email feedback
   forwarding** enabled. Set the application's feedback address to a mailbox
   the operator monitors. Verify this mailbox while still in the sandbox.
5. Test normal delivery and a deliberate SES mailbox-simulator bounce. Check
   receipt of the forwarded feedback, not only SMTP acceptance.

SES forwards SMTP feedback to a supplied Return-Path header, or otherwise to
the envelope MAIL FROM address. The recipient's delivered message uses SES's
anonymized Return-Path. A branded sender without a real inbox therefore needs
an explicit monitored feedback destination. See the official
[email feedback guide](https://docs.aws.amazon.com/ses/latest/dg/monitor-sending-activity-using-notifications-email.html).

SES suppresses further delivery to matching hard-bounce/complaint entries;
SMTP acceptance alone does not prove inbox delivery. Review incoming feedback
and the SES suppression list. Do not repeatedly clear suppression entries to
force sending: investigate the cause and confirm the address is valid and its
owner wants these messages. Gmail does not share complaint events with SES, so
this is not a complete record of every recipient's spam action. See
[account suppression](https://docs.aws.amazon.com/ses/latest/dg/sending-email-suppression-list.html)
and [production access](https://docs.aws.amazon.com/ses/latest/dg/request-production-access.html).

## Limits and failure behavior

Confirmation and reset sends share a durable SQLite admission ledger. Each
account and each destination address has a 60-second cooldown, a limit of five
sends per hour and twenty per day. Destination keys are hashed and case-folded
for throttling. Failed SMTP attempts consume admission to prevent retry storms.
Per-IP authentication limits also apply. A throttled reset request does not
invalidate an earlier valid link.

Tokens are random and stored only as hashes. Token consumption and account
changes use database transactions; password hashing and network calls do not
hold write transactions. Immediate SMTP failure invalidates the corresponding
link without exposing provider responses or secrets. There is no durable mail
queue: a crash between reserving a send and SMTP completion can require a later
resend after the cooldown. SES feedback covers failures after SMTP acceptance.

## Deployment and verification

Develop and test against disposable data first. Live games, clock ledgers,
messages and Codex continuations must survive the identity-schema migration.
Back up SQLite coherently before deploying; do not copy only its main file
while a WAL writer is active.

An idle snapshot alone does not prevent a player submitting a new move before
restart. Before a live restart, briefly gate incoming requests at the proxy,
let the still-running application finish all active responses/replay builds,
and verify no tokens remain reserved. Then stop the application, recheck the
saved state, back up, deploy, start and verify health before reopening access.
The current shutdown cancels active workers; increasing the stop timeout alone
does not make an in-flight restart safe. See the [deployment walkthrough](../DEPLOYMENT.md).

Run identity lifecycle, migration, concurrent token-use and SMTP isolation tests,
plus browser checks for recovery management, explicit confirmation, expired
links, cross-browser password reset and stale account responses. Test real
delivery with an operator-owned disposable account; never reset a real player's
password or email another player merely to test deployment.

## September 12, 2026 validation checkpoint

- Full Windows suite: **232 tests, two platform skips**. Focused Linux staging
  suite: **46 tests passed**, using the deployed Python environment with the
  new source in a separate checkout and low process priority.
- Browser QA used intercepted synthetic requests, including desktop/mobile
  recovery settings, explicit confirmation, expired links, reset, and delayed
  authentication responses. Auth mutations are serialized and reconciled with
  the session cookie; stale initialization/poll responses cannot override them.
- A coherent live-database backup was migrated twice in temporary storage.
  Digests of all 15 preexisting non-reset tables, using their original columns,
  stayed unchanged. Legacy reset tokens are intentionally invalidated and
  existing email addresses remain unverified.
- SES accepted two real messages for an operator-owned disposable account.
  The HTTP lifecycle confirmed its email, reset its password, rejected token
  reuse, revoked its old session and accepted a login with the new password.
  Test data and tokens were removed afterward. No real player was modified.
- The operator confirmed both recovery messages reached Gmail's inbox. A
  synthetic message to the SES bounce simulator was accepted; confirmation of
  the forwarded notice is still pending. Production access has been requested; approval is
  not yet confirmed. Account suppression and identity feedback forwarding are
  confirmed enabled in the console.

These checks did not restart the live application or enable recovery mail for
players. The remaining activation prerequisites are confirmed bounce-feedback
delivery, SES production approval and a gated update with private SMTP configuration.
