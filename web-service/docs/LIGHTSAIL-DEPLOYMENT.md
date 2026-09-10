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
from 20,000,000 to 40,000,000 using `ASTRA_MAX_DAILY_TOKENS=40000000`. That change
is applied. The repository default remains 20,000,000; the separate 3,000,000
per-action reservation and 500-action daily limit are unchanged. Previously
recorded usage remains charged.

Later that day, the operator authorized lowering automatic compaction from
300,000 to 250,000 total-context tokens while retaining the 400,000-token
window. The [current policy](CODEX-INTEGRATION.md) explains the pricing margin
and why the threshold is soft. **Live rollout is pending at this checkpoint**;
do not infer that a running game already uses the new value. Apply it at an idle
service boundary without interrupting active players, then record the deployed
revision and validation result here. The original 300,000 validation above
remains a historical record of the settings actually checked.

## Remaining limits and checks

- A full game on Linux, an observed live Linux automatic-compaction cycle and
  heavy-load/concurrent-user behavior have not yet been exercised.
- Both services are enabled, but a host reboot has not been performed to verify
  startup after reboot.
- SMTP and offsite backups are not configured. Optional password resets use an
  external SMTP provider when configured; delivery has not been verified.

The completed checks establish specific working paths and enforced limits;
they do not prove comprehensive isolation between mutually untrusted tenants.
