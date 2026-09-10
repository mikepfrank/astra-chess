# Host your own Astra Chess service

This walkthrough takes the working local application to a persistent Linux
service with a public HTTPS address. It follows the September 9–10, 2026
deployment on Amazon Linux 2023, with most software and all application state
under a dedicated account's home directory. It is also a starting point for
another Linux host with systemd and cgroup v2. Other distributions, ARM machines,
containers and alternative proxies require their own validation.

The [deployment checkpoint](docs/LIGHTSAIL-DEPLOYMENT.md) records what actually
passed on the first server. This document supplies the order of operations and
reusable commands. The [dependency inventory](docs/LIGHTSAIL-DEPENDENCIES.md)
and [capacity measurements](benchmarks/README.md) retain the earlier proposals
and observations; their dated instructions are superseded by this walkthrough.

Jump to [host setup](#1-preserve-the-local-version-and-prepare-the-host),
[Python](#2-install-private-python-and-application-packages),
[Codex](#3-install-and-pin-the-complete-codex-runtime),
[credentials](#4-provision-credentials-and-the-initial-private-origin),
[systemd checks](#5-install-the-application-unit-and-validate-its-actual-restrictions),
[private preview](#6-check-the-private-site-through-an-ssh-tunnel),
[DNS/firewall](#7-set-up-dns-and-the-public-firewall),
[HTTPS](#8-install-caddy-and-configure-https), or
[external verification](#9-verify-from-outside-the-server).

## What you will run

```text
Browser -- HTTPS --> Caddy :443 -- loopback HTTP --> Python/Uvicorn :8788
                                                     |
                                            authoritative game service
                                             /                 \
                                   private SQLite/files    per-game Codex state
                                                               |
                                                    OpenAI API + chess tools
```

The engine runs on your CPU; the language model runs through the OpenAI API.
No GPU, external chess engine, opening book or endgame database is needed.
The frontend is static HTML/CSS/JavaScript with no build step. SQLite requires
no separate database server, and the standalone Codex bundle needs no Node/npm
installation. The downloadable replay builder uses `chess` for notation
and rules; it does not replace the authored tactical engine.

Each game has its own durable Codex conversation and private files. A Codex
process runs for an action and exits afterward; it does not wait indefinitely
for a human move. One worker initially handles model actions sequentially
across games. An account can have three unfinished games, and games suspend
after 36 hours of human inactivity while retaining resumable state.

## Before starting

Have an SSH login with administrator access, a stable public IP, a domain whose
DNS you control, and an OpenAI API key with access to `gpt-6-astra`. The current
application fixes the model to Astra with Ultra reasoning; it does not silently
substitute another model. **An operator's interactive ChatGPT/Codex login is
not the service credential.** The bridge uses its own API provider and
`OPENAI_API_KEY`, even if the operator is already signed into Codex.

The tested server had 2 vCPUs and 8 GB RAM. Start with one active worker and
measure your host rather than treating this as a minimum specification. The
unit permits one logical CPU of aggregate work, 2 GiB RAM and 64 tasks for the
application and all its descendants. Those are caps, not reserved capacity.
Other workloads and burstable-instance CPU limits can affect engine depth.

Commands below use this reference layout:

| Setting | Reference value / what to change |
| --- | --- |
| Linux account and group | `astra:astra` |
| Full repository | `/home/astra/astra-chess`, branch `codex/hosted-chess` |
| Python | CPython 3.12.14, installed privately with uv 0.12.12 |
| Codex | Complete standalone 0.154.0 Linux x86-64 musl bundle |
| Caddy | Standalone 2.11.4 Linux amd64 binary |
| Private data | `/home/astra/.local/share/astra-chess` |
| Domain in examples | `chess.example.com` — replace with your own hostname |
| SSH address in examples | `ec2-user@SERVER_IP` — replace both as needed |

Keeping the account and paths above makes the supplied units and validation
tools directly usable. If you change them, adapt both units and
[`tools/run_service_check.py`](tools/run_service_check.py) and
[`tools/check_linux_service.py`](tools/check_linux_service.py). These helpers
currently name `astra` and the reference paths explicitly; they are not generic
installers. In particular, changing only `ASTRA_CODEX_BIN` is insufficient if
the executable's directory is hidden by the service's mount namespace.

Use the **administrator** shell for the few system operations explicitly
identified below. Use a login shell as **astra** for installation into its home.
Run each stage in order and stop on errors. These are fresh-install commands;
do not paste them over a running installation or an active game.

## 1. Preserve the local version and prepare the host

Commit and push your tested source branch before transferring it. Deploy the
full repository because the web service imports the engine and invokes
`../astra_chess.py`. Copying only `web-service/` will not work.

On the new host, inspect the OS, architecture, memory, disk and existing ports:

```sh
cat /etc/os-release
uname -m
free -h
df -h /home
systemctl --version
ss -ltn
git --version
python3.11 -m pip --version
```

The reference host already had Git, OpenSSH, curl, tar/gzip, CA certificates,
Python 3.11 with pip, systemd 252 and cgroup v2. Reuse existing utilities; if
something is absent, install only the missing prerequisites using your
distribution's packages. On Amazon Linux 2023, Python 3.11 can coexist with the
system Python. Do not replace `/usr/bin/python3`. Ports 80 and 443 must be free
for the supplied Caddy unit; if an existing proxy owns them, integrate the new
hostname into that proxy instead of stopping an unrelated service.

As **administrator**, create the account if it does not already exist:

```sh
sudo useradd --create-home --user-group --shell /bin/bash astra
sudo -iu astra
```

An existing account should be inspected and reused rather than recreated.
Direct SSH into `astra` is optional: an administrator can continue using
`sudo -iu astra`. The game account does not need sudo rights or AWS credentials.

As **astra**, create the private paths, then clone:

```sh
umask 077
install -d -m 700 /home/astra/.local/bin
install -d -m 700 /home/astra/.local/share/astra-chess-runtime/python
install -d -m 700 /home/astra/.local/share/astra-chess
install -d -m 700 /home/astra/.local/share/astra-caddy
install -d -m 700 /home/astra/.config/astra-chess
install -d -m 700 /home/astra/.cache/astra-deploy
git clone --branch codex/hosted-chess --single-branch https://github.com/mikepfrank/astra-chess.git /home/astra/astra-chess
cd /home/astra/astra-chess
git status --short
git rev-parse HEAD
```

Use your own fork URL if appropriate. For a private repository, configure a
repository-scoped read key or your approved Git credential method under the
operator account. Verify GitHub's host key when using SSH; do not disable host
key checking. The game processes do not require access to that Git credential.
Record the resulting commit alongside your deployment notes.

This starts a fresh hosted database. We did not transfer the laptop's user
accounts or active Codex sessions. Rebuild the virtual environment on Linux;
do not copy the Windows `.venv`, DPAPI credential or `var/local-config.json`.
For an old completed game, the [offline replay exporter](README.md#offline-game-replays)
can preserve a shareable archive independently of its original runtime.

## 2. Install private Python and application packages

As **astra**, use the existing Python 3.11 only to bootstrap uv, then use the
managed Python for the application:

```sh
python3.11 -m pip install --user 'uv==0.12.12'
export UV_PYTHON_INSTALL_DIR=/home/astra/.local/share/astra-chess-runtime/python
/home/astra/.local/bin/uv python install 3.12.14
ASTRA_PYTHON=$(/home/astra/.local/bin/uv python find --managed-python 3.12.14)
"$ASTRA_PYTHON" -m venv /home/astra/astra-chess/web-service/.venv
cd /home/astra/astra-chess/web-service
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip install -r requirements-replay.txt
.venv/bin/python -m pip check
.venv/bin/python --version
.venv/bin/python -m unittest discover -s tests -v
```

If user-level pip is unavailable or prohibited by your distribution, use uv's
[official installation instructions](https://docs.astral.sh/uv/getting-started/installation/)
to install the same reviewed release under `astra`, then continue from
`UV_PYTHON_INSTALL_DIR`. Its
[managed Python directory setting](https://docs.astral.sh/uv/reference/environment/#uv_python_install_dir)
keeps the interpreter and standard library within the unit's read-only runtime
mount. Do not use `sudo pip` or change the system Python to solve this step.

The full service now includes the rules-only `chess` dependency in
`requirements.txt` for the finished-game **Save replay** feature. The second
requirements file is the same dependency subset for standalone CLI builds;
installing it again is harmless. The full suite tests archive generation.
On the reference server, the final suite ran 160 tests successfully with three
Windows-only skips. Your selected revision may have a different test count;
record the actual result. These tests make no real model calls.

## 3. Install and pin the complete Codex runtime

Use the official standalone Linux installation route described in the
[Codex CLI documentation](https://learn.chatgpt.com/docs/codex/cli#install-codex).
The first server already had 0.154.0 installed, so we retained it and audited
the application against that version instead of replacing the operator's CLI.

The default installer follows the current release. The application currently
accepts only audited versions **0.153.4 and 0.154.0**, and the supplied Linux
units/check tools target **0.154.0**. As **astra**, pin that release explicitly:

```sh
(
    set -eu
    curl -fsSL https://chatgpt.com/codex/install.sh -o /home/astra/.cache/astra-deploy/codex-install.sh
    CODEX_NON_INTERACTIVE=1 CODEX_HOME=/home/astra/.codex CODEX_INSTALL_DIR=/home/astra/.local/bin \
        sh /home/astra/.cache/astra-deploy/codex-install.sh --release 0.154.0
    ASTRA_CODEX_RELEASE=/home/astra/.codex/packages/standalone/releases/0.154.0-x86_64-unknown-linux-musl
    test "$("$ASTRA_CODEX_RELEASE/bin/codex" --version)" = 'codex-cli 0.154.0'
    test -x "$ASTRA_CODEX_RELEASE/bin/codex-code-mode-host"
    test -x "$ASTRA_CODEX_RELEASE/codex-resources/bwrap"
    test -x "$ASTRA_CODEX_RELEASE/codex-path/rg"
)
```

The [official installer](https://chatgpt.com/codex/install.sh) and
[0.154.0 release metadata](https://releases.openai.com/codex/releases/0.154.0/release.json)
were inspected for this guide: `--release` is supported, and the installer
verifies the package and checksum manifest before installation. The complete
Linux x86-64 package's SHA-256 is
`fc6e3e3b85f2cf7d664520ee5c66a7fe4aa12bae7d46834f47e2f165fd0d6f78`.
The installer itself is a moving URL; retain the version and bundle checks.
This fresh-install recipe was source-checked, not executed over the live server.

Perform the version audit before adopting another release. Do not merely
broaden the allowlist to silence a compatibility error. On a shared operator
account, the installer also updates its launcher symlink; coordinate that
change or use a dedicated service account as shown here.

The reference bundle must contain all of these paths:

```text
/home/astra/.codex/packages/standalone/releases/0.154.0-x86_64-unknown-linux-musl/
  bin/codex
  bin/codex-code-mode-host
  codex-resources/bwrap
  codex-path/rg
```

Verify the executable as **astra**:

```sh
/home/astra/.codex/packages/standalone/releases/0.154.0-x86_64-unknown-linux-musl/bin/codex --version
```

Expect `codex-cli 0.154.0`. Keep the entire release directory at this location;
copying only `bin/codex` loses its native tool host and sandbox helpers. Pin the
unit to the versioned executable, rather than the operator's mutable launcher
symlink. The namespace and real model checks in step 5 establish more than a
successful `--version`. See [the Codex audit](docs/CODEX-INTEGRATION.md).

## 4. Provision credentials and the initial private origin

As **astra**, create the service environment file with a hidden key prompt.
The following example refuses to overwrite an existing file. The initial
origin matches the SSH tunnel in step 6; it will change when HTTPS is ready.

```sh
cd /home/astra/astra-chess/web-service
umask 077
.venv/bin/python - <<'PY'
from getpass import getpass, GetPassWarning
from pathlib import Path
import json
import warnings

warnings.simplefilter("error", GetPassWarning)
key = getpass("OpenAI API key for the chess service: ").strip()
if not key or not key.isascii() or any(ord(c) < 32 or ord(c) == 127 for c in key):
    raise SystemExit("A nonempty ASCII key without control characters is required.")
template = Path("deploy/service.env.example").read_text()
template = template.replace("http://127.0.0.1:8788", "http://localhost:18788")
target = Path("/home/astra/.config/astra-chess/service.env")
with target.open("x", encoding="utf-8") as output:
    output.write(template + "\nOPENAI_API_KEY=" + json.dumps(key) + "\n")
target.chmod(0o600)
print("Created private service configuration; key was not printed.")
PY
```

Systemd does not source `.bash_profile`, so a key available in an interactive
login is not automatically available to the service. PID 1 reads this private
file before constructing the game's restricted filesystem view. Do not place
the key in a command argument, Git, browser JavaScript or a URL.

Review the nonsecret limits from [the configuration table](README.md#configuration).
The supplied values allow one worker, 500 model actions per UTC day, a
3,000,000-token reservation per action and 20,000,000 daily tokens. Repeated
context/input tokens count too; these are generous accounting limits, not a
dollar spending cap. Reserve enough daily headroom for one full action.
The separate context settings are a 400,000-token window and a soft compaction
trigger at 250,000 total-context tokens. The nominal 22,000-token margin below
the long-input pricing boundary reduces exposure to that rate tier without
guaranteeing it. See the [current compaction policy](docs/CODEX-INTEGRATION.md)
and the [dated host overrides](docs/LIGHTSAIL-DEPLOYMENT.md#operator-policy-changes);
the supplied 20,000,000 daily default is separate from those operator choices.

Leave SMTP settings unset for the initial test. The interface then omits the
optional recovery-email setup. Password-protected accounts still work.

## 5. Install the application unit and validate its actual restrictions

As **administrator**, review and install the supplied unit:

```sh
sudo install -o root -g root -m 644 /home/astra/astra-chess/web-service/deploy/astra-chess.service /etc/systemd/system/astra-chess.service
sudo systemctl daemon-reload
sudo systemd-analyze verify /etc/systemd/system/astra-chess.service
sudo /usr/bin/python3.11 /home/astra/astra-chess/web-service/tools/run_service_check.py preflight
sudo /usr/bin/python3.11 /home/astra/astra-chess/web-service/tools/run_service_check.py protocol
```

The first helper checks Python, SQLite writes, password hashing, read-only
source/runtime access, hidden operator files and CPU/memory/task caps. The
second validates the installed Codex protocol and restricted tool configuration
without making a model request. Both use transient units with the installed
application unit's settings. The helper reads the main unit file, **not
systemd drop-in overrides**; adapt it before relying on it with override files.

All bind sources must already exist. `ProtectHome=tmpfs` hides other home paths
and selectively exposes the repository, Python runtime and Codex bundle as
read-only, plus private data as writable. The operator's SSH keys and Codex
login remain hidden. Do not fix missing runtime files by exposing the entire
home directory. See [the unit reference](deploy/README.md) for the rationale.

Next, explicitly exercise **two paid model turns** inside the same restrictions:

```sh
sudo /usr/bin/python3.11 /home/astra/astra-chess/web-service/tools/run_service_check.py live --live
```

This uses a separate private test game, including tactical queries and Codex
conversation resumption. It does not modify a player's game. It still consumes
CPU and API usage, so run it before admitting players or during a maintenance
window. A no-key protocol pass does not prove your key can access Astra, and a
live two-turn pass does not prove a full game or large-context compaction works.

Once the checks pass, start the application as **administrator**:

```sh
sudo systemctl enable --now astra-chess.service
sudo systemctl status astra-chess.service --no-pager
curl --fail --header 'Host: localhost:18788' http://127.0.0.1:8788/api/config
```

Expect an active unit and `player_available: true`. The availability flag checks
configuration presence; the preceding paid check establishes model access.
The unit binds only to loopback and trusts proxy headers only from `127.0.0.1`.
Do not use `--public`, Uvicorn reload or multiple Uvicorn workers here.

## 6. Check the private site through an SSH tunnel

On your **laptop**, open a separate terminal and leave this command running:

```sh
ssh -N -T -o ExitOnForwardFailure=yes -L localhost:18788:127.0.0.1:8788 ec2-user@SERVER_IP
```

Visit `http://localhost:18788` in your browser. This leaves a local development
server on `127.0.0.1:8788` alone. Cookies are separated by hostname, **not port**;
using `127.0.0.1` for both sites could replace the laptop game's session cookie.
The browser address must exactly match `ASTRA_ORIGIN`; `localhost` and
`127.0.0.1` are different origins. The server-side check in step 5 supplies
the matching Host header because the application checks hostnames too. No cloud
firewall rule for port 8788 is needed. If you already run another Astra service
at `localhost`, use a separate browser profile for this preview.

Create a QA guest, start as White, check the board and reload recovery, then
resign the test game. Starting as White does not request an AI action until
you submit a move or chat message. Starting as Black does request Astra's
opening move. Check the chat input remains available after resignation.

## 7. Set up DNS and the public firewall

Choose a hostname and replace `chess.example.com` throughout the remaining
examples. At its authoritative DNS provider:

| Record | Value |
| --- | --- |
| A for the chosen hostname (`@` for an apex domain) | Your server's stable public IPv4 address |
| Optional CNAME for `www.chess.example.com` (`www.chess` in the `example.com` zone) | `chess.example.com` |

Point these records to your server, not a static replay host. DNS can be managed
at a different provider from the server; static hosting is not required for
this service. For an apex such as `example.com`, the usual alias is instead
`www.example.com` (zone label `www`); change the Caddyfile to match.
Verify the public answers from your laptop with `nslookup`.
Do not publish an AAAA record unless IPv6 routing and firewall access also work.
An existing wrong AAAA record can make certificate issuance or client access
fail even while IPv4 works.

Allow inbound **TCP 80 and TCP 443** to the host in its cloud firewall/security
group and any host firewall. Leave port 8788 private. Retain your SSH access.
For Lightsail, use the instance's Networking page and add HTTP and HTTPS rules;
[AWS documents separate IPv4/IPv6 rules](https://docs.aws.amazon.com/lightsail/latest/userguide/amazon-lightsail-editing-firewall-rules.html).
Do not assume that opening port 80 also opens 443: this was the final blocker
in the first deployment. Configure both before trying public HTTPS.

## 8. Install Caddy and configure HTTPS

As **astra**, obtain the Linux amd64 archive and matching checksums from the
[official Caddy 2.11.4 release](https://github.com/caddyserver/caddy/releases/tag/v2.11.4):

```sh
(
    set -eu
    install -d -m 700 /home/astra/.cache/astra-deploy/caddy
    cd /home/astra/.cache/astra-deploy/caddy
    curl -fL https://github.com/caddyserver/caddy/releases/download/v2.11.4/caddy_2.11.4_linux_amd64.tar.gz -o caddy_2.11.4_linux_amd64.tar.gz
    curl -fL https://github.com/caddyserver/caddy/releases/download/v2.11.4/caddy_2.11.4_checksums.txt -o caddy_2.11.4_checksums.txt
    sha512sum --check --ignore-missing caddy_2.11.4_checksums.txt
    tar -xzf caddy_2.11.4_linux_amd64.tar.gz caddy
    install -m 755 caddy /home/astra/.local/bin/caddy
)
```

Confirm `caddy_2.11.4_linux_amd64.tar.gz: OK`. The first deployment used the
release's SHA-512 checksum. A SHA-256 digest will not match a SHA-512 list.
Use the correct architecture if adapting this guide. Caddy's
[binary installation guide](https://caddyserver.com/docs/install#static-binaries)
also links its asset-signature verification procedure.

As **astra**, write your Caddyfile (the following is an example file's contents,
not a shell command):

```caddyfile
{
    admin off
    servers {
        protocols h1 h2
    }
}

chess.example.com {
    encode gzip
    reverse_proxy 127.0.0.1:8788
}

www.chess.example.com {
    redir https://chess.example.com{uri} permanent
}
```

Save it at `/home/astra/.config/astra-chess/Caddyfile`, mode `0600`. Omit the
`www` block if you did not configure that name. The repository's
[`Caddyfile.example`](deploy/Caddyfile.example) contains the first deployment's
real hostname: replace it rather than requesting certificates for someone
else's domain.

```sh
chmod 600 /home/astra/.config/astra-chess/Caddyfile
/home/astra/.local/bin/caddy version
/home/astra/.local/bin/caddy validate --config /home/astra/.config/astra-chess/Caddyfile --adapter caddyfile
```

Before switching origins, finish the private QA game. As **administrator**,
stop the application. As **astra**, edit only `ASTRA_ORIGIN` in the protected
environment file to `https://chess.example.com` (no trailing slash or path),
preserving the credential and permissions. Return to the **administrator**
shell to install the proxy unit and start both services:

```sh
sudo systemctl stop astra-chess.service
```

Perform the environment-file edit now, then:

```sh
sudo install -o root -g root -m 644 /home/astra/astra-chess/web-service/deploy/astra-caddy.service /etc/systemd/system/astra-caddy.service
sudo systemctl daemon-reload
sudo systemd-analyze verify /etc/systemd/system/astra-chess.service /etc/systemd/system/astra-caddy.service
sudo systemctl start astra-chess.service
sudo systemctl enable --now astra-caddy.service
sudo systemctl status astra-chess.service astra-caddy.service --no-pager
sudo journalctl -u astra-caddy.service -n 60 --no-pager
```

Caddy uses its own private state directory and the capability needed to bind
ports 80/443. It obtains and renews certificates and redirects HTTP to HTTPS;
see [automatic HTTPS](https://caddyserver.com/docs/automatic-https). No separate
Certbot process is needed. The example uses HTTP/1.1 and HTTP/2, so UDP 443 is
not required. Its admin API is disabled; later configuration changes use a
controlled proxy restart. Confirm successful certificate issuance in its log.

Only the two unit files and their enablement links are added to system service
locations. Executables, packages, configuration, certificates and application
data stay under `/home/astra`; systemd still uses its normal journal and private
temporary-directory facilities. The original host needed no new system packages.

## 9. Verify from outside the server

From your **laptop**, substitute your hostname:

```sh
curl --fail --head http://chess.example.com/
curl --fail --dump-header - --output /dev/null https://chess.example.com/
curl --fail https://chess.example.com/api/config
curl --fail --head https://www.chess.example.com/
```

Use `curl.exe` in Windows PowerShell if `curl` resolves to an alias, and replace
`/dev/null` with `NUL`. Use GET for the application's HTTPS page: its GET-only
route may return 405 for a HEAD request. Expect
HTTP-to-HTTPS redirection, HTTPS 200, the player configuration, and an optional
`www` redirect. Keep certificate verification enabled. A local successful
request cannot prove the cloud firewall admits public traffic.

The explicit web check below creates a QA guest and three resigned games. It
checks secure cookies, isolated games, the unfinished-game cap, illegal move
rejection, saved state and foreign-Origin rejection, without making model calls.
Run from `web-service/` on a machine with its dependencies installed:

```sh
.venv/bin/python tests/http_deployment_check.py --origin https://chess.example.com --live-http
```

On Windows use `.venv/Scripts/python.exe`. `--connect-local` is available only
for a check run on the server: it sends the public hostname to local Caddy
while retaining certificate verification. It does **not** replace an external
network check.

Finally use the public page in a real browser: register, choose a side, play a
few turns, reload, inspect status/evaluation updates, and complete a game.
Observe compaction and multi-user behavior during subsequent trials rather
than assuming they are established by a short check. Sign out of QA accounts
before handing a shared browser to a real player. Close the temporary SSH
tunnel with Ctrl+C; its HTTP origin no longer matches the public configuration.

## Operations, updates and moving to another host

Keep the launch paths and private directories recorded with the Git commit and
dependency versions. [The deployment checkpoint](docs/LIGHTSAIL-DEPLOYMENT.md#permissions-backup-and-rollback)
has concrete backup/restore and unit-removal instructions. Back up the whole
application data directory, including SQLite companion files, query evidence
and Codex session files, with the application stopped. Preserve credentials
and proxy TLS state separately in private operator storage. Offsite storage,
retention and backup scheduling require an operator decision; this installation
does not automatically provide them.

For application or engine updates, coordinate a maintenance window, stop the
application, take a backup, update the checkout as `astra`, reinstall changed
requirements if needed, rerun appropriate checks, and restart. Do not pull code
into a running player's source tree. An engine fingerprint mismatch blocks
resumption of unfinished games; retain the old engine revision until those
games finish or you have an explicitly designed migration. Changing Codex
versions requires the protocol and paid runtime checks again. Changes to unit
files also need `systemctl daemon-reload` before restart.

For a new Linux host, rebuild the runtimes and virtual environment, restore a
coherent stopped-service data backup with `astra` ownership and private modes,
and use the same code revision and paths initially. Stop the old service before
starting the restored state on the new one. Verify privately, then change DNS
and verify HTTPS again. Do not run two schedulers over the same data directory.
Windows-to-Linux transfer of existing Codex continuation state was not tested
in the first deployment; a fresh hosted database avoids claiming that migration.

Password-reset email is optional. Configure an outbound SMTP provider using
the `ASTRA_SMTP_*` settings in the [configuration table](README.md#configuration),
including its verified sender and required DNS records, then test delivery.
A local mail server is not required. The first deployment left SMTP unset.

## Troubleshooting the transition from local to hosted

| Symptom | First checks |
| --- | --- |
| “Astra is unavailable” | Is `ASTRA_PLAYER=codex` set in the systemd environment file, and is the API key present there? A login-shell export alone does not configure the service. Check the actual model turn separately from `/api/config`. |
| Immediate interrupted turn | Inspect private service logs for the exact cause; verify audited Codex version, full bundle and native code-mode host, then run the protocol and isolated live checks during a quiet period. Preserve game state before retrying. |
| Namespace/permission error on startup | Check every bind source exists, ownership is correct, and the venv's interpreter/standard library and Codex helpers lie within the explicitly mounted runtime directories. |
| Site renders but game creation/chat is rejected | Browser scheme, hostname and port must match `ASTRA_ORIGIN`. After changing it, restart the application and use the new address. |
| HTTPS times out but HTTP responds | Check TCP 443 in both cloud and host firewalls, DNS A/AAAA answers, and the proxy listener. |
| HTTPS certificate issuance fails | Check both domain names, public routing to ports 80/443, conflicting DNS/CAA records and the Caddy log. Do not bypass the browser certificate warning. |
| Daily resource allowance reached | Check reported usage and outstanding reservations. Large input contexts count on each model request; this is separate from the compaction threshold and remaining chess time. |
| Refusal to resume after an update | Restore the game's engine revision; do not erase fingerprints or overwrite its evidence to force a resume. |

Inspect logs locally before sharing excerpts: game conversations and Codex
state are private records. The restricted tools and OS limits reduce exposure
to hostile player messages; this alpha is not a claim of proven isolation
between mutually untrusted processes sharing a Linux account.
