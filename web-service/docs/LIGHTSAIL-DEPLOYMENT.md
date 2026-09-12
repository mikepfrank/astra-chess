# Lightsail deployment checkpoint

For instructions to reproduce this deployment on your own host, start with the
[deployment walkthrough](../DEPLOYMENT.md). This checkpoint preserves the
first installation's settings and observed results.

Updated on 2026-09-10 for the Linux alpha, whose player interface is labeled
public beta. [Astra Plays Chess](https://astraplayschess.com/) is reachable over
verified public HTTPS on the existing Amazon Linux 2023 host, under the `astra`
account. Both application and proxy services are enabled and active. A real
two-turn player check passed under the application service's exact sandbox
settings. The remaining validation limits are listed below.

The remote checkout is `/home/astra/astra-chess`, branch
`codex/hosted-chess`, at runtime application revision `923ce41`. This is an installation and validation
record; subsequent changes should record their tested revision separately.
The earlier [dependency inventory](LIGHTSAIL-DEPENDENCIES.md) remains the
pre-installation proposal. The installation used a private managed Python
instead of adding the proposed system Python packages.

## Installed components

| Component | Verified installation |
| --- | --- |
| Python installer | `uv 0.12.12`, bootstrapped with user-level pip under `/home/astra/.local` |
| Python runtime | Managed CPython 3.12.14 under `/home/astra/.local/share/astra-chess-runtime/python` |
| Application environment | `/home/astra/astra-chess/web-service/.venv`, with the pinned `requirements.txt` and optional replay package `chess==1.11.2` |
| Runtime libraries | SQLite 3.53.1 and OpenSSL 3.5.8, supplied by the managed Python runtime |
| Codex | Standalone 0.154.0 bundle under `/home/astra/.codex/packages/standalone/releases/0.154.0-x86_64-unknown-linux-musl` |
| Reverse proxy | Caddy 2.11.4 at `/home/astra/.local/bin/caddy`; official archive verified against its SHA-512 checksum; active on ports 80 and 443 |
| Service configuration | `/home/astra/.config/astra-chess/service.env`, mode `0600`, in the private configuration directory |
| Durable application data | `/home/astra/.local/share/astra-chess` |
| Proxy configuration and TLS state | `/home/astra/.config/astra-chess/Caddyfile` and `/home/astra/.local/share/astra-caddy` |
| System-level installation | Only two service units: `/etc/systemd/system/astra-chess.service` and `/etc/systemd/system/astra-caddy.service` |

The system Python installation was left unchanged. Keep the complete Codex
release directory together: its native code-mode host, bundled bubblewrap and
`rg` are part of the runtime. Node and npm are not needed by this standalone
installation.

## Completed validation

The installed unit passed `systemd-analyze verify`; the only reported warning
concerned an unrelated legacy `acpid` unit. A transient unit with the exact
application sandbox properties passed the filesystem and runtime preflight:

- The repository and managed Python runtime were readable and read-only.
- The operator's `.ssh`, Codex authentication and configuration file were
  hidden from the service filesystem view; application data was writable.
- The API credential was present in the service environment, and Python's
  password-hashing `scrypt` operation worked. Credential presence alone is
  not a model-access test.
- The cgroup reported `cpu.max` as `100000 100000`, `memory.max` as
  `2147483648`, and `pids.max` as `64`: one CPU of aggregate capacity, 2 GiB
  of memory and 64 tasks. The application is configured for one worker.

A no-key Codex 0.154.0 protocol check also passed inside the same namespace:
strict configuration, the seven application tools, Astra with Ultra reasoning,
400,000-token context and 300,000-token compaction threshold, empty execution
environments, and read-only/no-network tool permissions. That protocol check
does not establish that a paid model turn or code-mode execution succeeds.

The final Linux suite completed 160 tests: OK, with three Windows-only skips
(Windows process cleanup and two DPAPI credential checks).

The live two-turn check passed inside the exact unit settings: Astra played
`e4`, the human reply was `a6`, and Astra continued with `d4`, preserving the
same Codex thread. This exercised real model turns under the hard OS limits,
separately from the no-key protocol check.

TLS HTTP integration checks passed for registration and cookies, three isolated
games, refusal of a fourth unfinished game, illegal-move rejection, reload,
resignation and rejection of a foreign Origin. These HTTP checks made no AI
calls; they validate the web integration rather than additional model play.
They passed through local Caddy with public-hostname certificate verification,
then again from the Windows laptop through the public HTTPS endpoint using
`tests/http_deployment_check.py --origin https://astraplayschess.com --live-http`.

After the user opened Lightsail TCP 443, an external laptop request to
`https://astraplayschess.com/api/config` returned HTTP 200 with
`player_available: true`, model `gpt-6-astra` and reasoning `ultra`.
`https://www.astraplayschess.com` returned HTTP 301 to the apex site with valid
TLS. The API availability flag reports configuration presence; the separate
live two-turn check above establishes that model play succeeded.

External plain HTTP returned HTTP 308 to HTTPS. Public browser QA also passed:
guest registration, the White/Black selector, creation of a human-first game,
rendered board and piece assets, restoration of the same game after reload,
resignation, and availability of the post-game chat input. The browser test
game was resigned without moves or messages, and the QA guest signed out.

## Public routing and service operation

The user purchased `astraplayschess.com` through GoDaddy. Its apex A record
resolves to `54.190.167.232`; `www` has a CNAME and redirects to the apex.
Caddy listens on ports 80 and 443 and forwards application traffic to
`127.0.0.1:8788`. The application uses `ASTRA_ORIGIN=https://astraplayschess.com`
and `--proxy-headers`, trusting forwarded client addresses and scheme only from
the proxy at `127.0.0.1`.

The installed `astra-caddy` unit runs the user-local binary with
`CAP_NET_BIND_SERVICE`. Its executable, configuration and TLS state remain
under `/home/astra`; the only two system-level service additions are the units
listed above. The earlier `http://localhost:18788` SSH preview is obsolete and
does not match the current application origin. Its temporary laptop SSH tunnel
was stopped. Use the public HTTPS address. Caddy obtained valid Let's Encrypt
certificates for both hostnames and manages renewal automatically; its admin
API is disabled in the installed configuration.

Operator commands for the installed services:

```sh
sudo systemctl start astra-chess.service
sudo systemctl start astra-caddy.service
sudo systemctl status astra-chess.service astra-caddy.service --no-pager
sudo journalctl -u astra-chess.service -n 100 --no-pager
sudo journalctl -u astra-caddy.service -n 100 --no-pager
sudo systemctl stop astra-caddy.service
sudo systemctl stop astra-chess.service
```

## Permissions, backup and rollback

The service runs as `astra`; its repository and runtime mounts are read-only
inside the service namespace. The account can maintain its checkout outside
that namespace. Keep repository updates under the owning account, with normal
Git ownership checks, and stop the service before changing its executable
code or tactical engine. Do not make the whole home directory visible to the
service to solve a Git or runtime path problem.

PID 1 reads the private environment file before constructing the namespace.
The service receives the configured environment without access to that file
through its filesystem. Keep credentials, private game records and Codex
session data out of Git. Do not paste environment contents or unreviewed logs
into a deployment report.

Back up the **whole application data directory with the service stopped**.
This keeps the database, any SQLite companion files, game evidence and Codex
session files together. Run these commands individually, confirming that the
stop completed before running the archive command. Caddy can remain running
during this brief application maintenance window.

```sh
sudo systemctl stop astra-chess.service
sudo systemctl is-active astra-chess.service
sudo -u astra sh -c 'umask 077; install -d -m 700 /home/astra/backups/astra-chess; tar -C /home/astra/.local/share -czf "/home/astra/backups/astra-chess/state-$(date -u +%Y%m%dT%H%M%SZ).tar.gz" astra-chess'
```

`is-active` should print `inactive` and return a nonzero status before the
backup proceeds. After the backup attempt, restore service availability even
if the archive command failed, and inspect the resulting status:

```sh
sudo systemctl start astra-chess.service
sudo systemctl status astra-chess.service --no-pager
```

Keep backups private and outside the repository and live
data directory. Record the source revision and preserve the environment file
separately in secure operator storage; neither belongs in a public archive.
Include the Caddy configuration and private TLS state in the deployment's
secure backup plan. Restore the complete matching application data set only
while the application service is stopped, then start it and check its status.
These are manual backup instructions; offsite backups are not configured.

To roll back the system-level installation, stop and disable both units:

```sh
sudo systemctl disable --now astra-caddy.service astra-chess.service
```

Remove only `/etc/systemd/system/astra-chess.service` and
`/etc/systemd/system/astra-caddy.service`, or restore their saved predecessors
if any exist, then run `sudo systemctl daemon-reload`. Leave other services,
the repository, managed runtimes, credentials and application/proxy data intact.
This is a unit rollback, not a data deletion or a Python rollback.

## Operator policy changes

On September 10, 2026, the operator doubled this host's daily token allowance
from 20,000,000 to 40,000,000 using `ASTRA_MAX_DAILY_TOKENS=40000000`. This was
the first increase; the current override is recorded below. The repository
default remains 20,000,000; the separate 3,000,000
per-action reservation and 500-action daily limit are unchanged. Previously
recorded usage remains charged.

Later that day, the operator authorized lowering automatic compaction from
300,000 to 250,000 total-context tokens while retaining the 400,000-token
window. The [current policy](CODEX-INTEGRATION.md) explains the pricing margin
and why the threshold is soft. Revision `73040c0` was deployed on September 10
at 17:56 UTC after all responses were idle. All 29 bridge tests passed locally;
the installed Codex 0.154.0 also passed the strict configuration and thread-start
protocol check under the service's systemd restrictions, confirming the 400,000
window and 250,000 threshold without credentials or a model request.

The deployment preserved all 11 saved game records, including moves, messages,
thread identifiers and clock accounting. The public configuration endpoint
confirmed Astra/Ultra was available after restart. Existing games receive the
new setting on their next Astra response; no manual compaction was forced.
The private operator audit is stored at
`/home/astra/.local/share/astra-chess/operator-checks/compaction-policy-250k-2026-09-10.json`.
The original 300,000 validation above remains a historical record of the
settings actually checked.

At 19:31 UTC on September 10, the operator raised this host's daily allowance
again, from 40,000,000 to **100,000,000 tokens**, using
`ASTRA_MAX_DAILY_TOKENS=100000000` in the private service environment file.
The running process's environment was checked after restarting at an idle
boundary, with zero outstanding reservations. All 11 saved game records and
their clock accounting were preserved, along with the daily ledger's 63
admitted actions and 30,554,740 charged tokens. Increasing the allowance did
not reset usage. The 500-action daily limit, 3,000,000-token per-action
reservation, 400,000 context window and 250,000 compaction threshold remain
unchanged. This is the current Lightsail override; the generic installation
default remains 20,000,000 tokens per UTC day.

The private audit is stored at
`/home/astra/.local/share/astra-chess/operator-checks/daily-limit-100m-2026-09-10.json`.
The initial attempt rolled back because its loopback health request lacked
the public Host header. For this deployed configuration, loopback probes must
use `Host: astraplayschess.com` and `X-Forwarded-Proto: https`; the corrected
probe confirmed Astra/Ultra was available. Public HTTPS was also checked.

## Standalone replay library — September 10, 2026

Revision `15881ae` was deployed at 22:25 UTC. Finished games now offer **Save
replay** with optional conversation, independent HTML download and public
listing, and owner-controlled removal. The public list is `/games/`; the ten
already-published experiment replays and their index are mirrored at
`/experiments/`. The original tracked archives and their Netlify copies remain
unchanged. [REPLAY-WORKFLOW.md](REPLAY-WORKFLOW.md) preserves the template,
procedure, endpoints and backup requirements; player instructions explain the
controls without adding model tools or publishing authority.

The full suite passed 180 tests on Windows (two platform-related skips) and on
Linux (three platform-related skips). Linux tests ran from a separate staged
copy before changing the live checkout. Isolated HTTP/browser checks exercised
generation with and without chat, actual offline HTML downloads, independent
publication/removal, immutable public versions, revoked links, account ownership,
reload, synchronized chat, hostile-text escaping, script-hash CSP and narrow
layouts. Public HTTPS browser checks confirmed the new index, all ten historical
pages, the first human replay's 71-message timeline and the Li draw's final frame.

Both deployment attempts waited for zero active responses and reservations. The
first restored the previous revision because the operator's HTTP-header check
used case-sensitive lookup; the corrected check passed. The final deployment
preserved all 13 games, clock records and the complete usage ledger. The running
daily allowance remains 100,000,000 tokens. No user game was published by these
checks, and no model request was needed. Players make their own download and
publication choices after refreshing the page.

Private operator evidence is under
`/home/astra/.local/share/astra-chess/operator-checks/`: the staged release and
Linux log in `replay-release-15881ae/`, database backup in
`before-replay-library-2026-09-10-retry.sqlite3`, and deployment audit in
`replay-library-deployment-2026-09-10.json`. The new archive/publication tables
are additive; the backup and original game records were retained.

## Unified replay sharing — September 10, 2026

Revision `5cb1a2d` was deployed at 22:57 UTC. A single **Save/share replay**
dialog now offers independent downloads and sharing; new shares are unlisted
unless the owner chooses **Also publish to public game list**. Removing a listing
keeps its link usable; disabling the link revokes access. Earlier legacy links
remain separately manageable inside the same dialog. Existing public entries
remain listed; the additive unlisted table is never read by the older index code.

All 186 tests passed on Windows (two platform-related skips) and in a separate
Linux staging directory (three platform-related skips). Browser tests exercised
the complete unified flow, both chat choices, offline downloads, unlisted
discovery exclusion, same-URL visibility changes, older-version relisting and
independent legacy revocation. Read-only public HTTPS checks verified the served
controls and library without creating an account, game or publication.

Deployment waited for zero active responses, replay builds and token reservations.
It preserved all 14 games and their clock records, usage rows, existing replay
metadata and HTML snapshots. The 100,000,000-token daily allowance remains active.
Private evidence under `/home/astra/.local/share/astra-chess/operator-checks/`
includes the `unified-replay-release-5cb1a2d/` staging directory and Linux test log,
`before-unified-replay-20260910T225727Z.sqlite3` backup, and
`unified-replay-deployment-20260910T225727Z.json` audit.

## Independent replay versions — September 10, 2026

Revision `bec65c2` was deployed at 23:57 UTC. The replay dialog retains independent
Moves only and With chat versions, with scoped updates, sharing and deletion.
The public index contains one entry per game and prefers chat only when both
versions are explicitly listed. Previously generated downloads and shared
snapshots migrate with their IDs, bytes, URLs and visibility preserved.

The final Linux release passed 194 tests (three platform skips) in
`operator-checks/replay-variants-release-bec65c2/`. The Windows full run passed
193 tests (two platform skips) before the final older-client ambiguity guard;
it took approximately ten minutes. All 28 final replay-library tests then passed
together on Windows, including that guard. Complete disposable-game browser checks
covered both variants, offline downloads, public-list priority/fallback,
unlisted-chat privacy, update isolation, independent deletion and reload.

A private-copy rehearsal in `operator-checks/replay-variants-migration-*/`
verified migration and repeat-start behavior against the host's actual saved
data without live writes. Deployment waited for zero active responses, replay
builds and reservations. All 16 games, clocks, usage rows and original replay
contents were preserved; the running daily allowance remains 100,000,000 tokens.
Public HTTPS checks verified the served controls. Backup and audit files are
`before-replay-variants-20260910T235714Z.sqlite3` and
`replay-variants-deployment-20260910T235714Z.json` under `operator-checks/`.

The one-time migration retires old standalone replay metadata to prevent deleted
links from being resurrected. Rolling back application code alone makes migrated
standalone links unavailable until this version is restored. If the old release
accepts new replay writes, the next upgrade refuses startup pending operator
reconciliation. Prefer a forward fix after accepting writes; never restore an
old complete database over newer player activity. The replay workflow documents
the current storage and variant-scoped routes.

## Remaining limits and checks

The September 12 [notification-monitor preparation](GAME-NOTIFICATIONS.md#september-12-lightsail-preparation-checkpoint)
added an independent `astra-game-notify.service` and hourly timer, running as
`astra` with separate configuration/state and no model calls. Source `4b32c87`
passed 13 focused Windows tests and 13 Linux tests; actual namespace and SQLite
sidecar checks passed. Later that day, the
[SES activation check](GAME-NOTIFICATIONS.md#september-12-ses-activation-checkpoint)
passed in the installed service sandbox, and the timer was enabled. SES accepted
a synthetic test and the first real digest; the initial 20-ID baseline advanced
to 21 reported game IDs without a pending batch. The operator confirmed receiving
both messages. Installation and activation did not restart the chess
service. Stop the monitor too before replacing/restoring its database.

- Human players have completed Linux games since initial deployment. An
  explicitly observed live Linux automatic-compaction cycle and heavy-load
  behavior remain unverified; see the [September 11 handoff](../HANDOFF.md).
- Both services are enabled, but a host reboot has not been performed to verify
  startup after reboot.
- Operator-notification SMTP is configured separately. Password-reset SMTP and
  offsite backups are not configured. Ordinary player recovery mail also needs
  SES production access and an end-to-end reset test before general use.

The completed checks establish specific working paths and enforced limits;
they do not prove comprehensive isolation between mutually untrusted tenants.
