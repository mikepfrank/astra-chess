# Lightsail dependency inventory for review

Prepared September 9, 2026 against `codex/hosted-chess` at `736ec22` and
read-only checks on the existing Amazon Linux 2023 x86-64 host, using a login
environment for `astra`. This is an installation proposal, not a deployment
record. No packages were installed and no services were started for this review.

## Proposed installation

| Component | Purpose | Observed status and proposed action |
| --- | --- | --- |
| Python 3.12 and pip | Application, tactical engine, and dependency installation | Not installed. The host's cached Amazon Linux repository offers `python3.12` 3.12.12 and `python3.12-pip` 23.2.1. Install these alongside existing Python versions to match the application's tested Python 3.12 environment. Recheck available package revisions when installing. |
| Private Python virtual environment | Keep application packages separate from OS and other users' packages | Create `web-service/.venv` in the cloned checkout, then install the exact versions in [requirements.txt](../requirements.txt). The principal packages are listed below. |
| Caddy | Public HTTPS endpoint, certificate renewal, and forwarding to the loopback application server | Neither Caddy, nginx, nor Apache is installed under those RPM names or available on `astra`'s PATH; ports 80 and 443 had no TCP listeners. Propose the official stable Linux amd64 Caddy binary, with release verification and a systemd service. The exact release will be recorded at installation. |
| Compatible Codex CLI and its bundled code-mode host | Per-game model sessions and execution of the restricted chess-tool interface | Standalone CLI 0.154.0 is already installed, including the code-mode host. The bridge currently accepts only audited version 0.153.4. Audit 0.154.0 before admitting it, or install an isolated service copy of the compatible release. No CLI replacement has been made. |

[AWS documents side-by-side Python versions](https://docs.aws.amazon.com/linux/al2023/ug/python.html).
Keep the system `/usr/bin/python3` on Python 3.9. The existing Python 3.11.14
has working pip, venv, ensurepip, SQLite, and SSL and passed the earlier engine
benchmark; the complete web service has not been validated on that interpreter.
Python 3.12 is the proposed baseline to avoid introducing that extra difference.

[Caddy supports installation from official binaries](https://caddyserver.com/docs/install)
and [automates HTTPS issuance and renewal](https://caddyserver.com/docs/automatic-https).
Its built-in certificate management covers this deployment without a separate
certificate-renewal application. This proposal does not assume that an arbitrary
Fedora/RHEL third-party RPM repository is compatible with Amazon Linux.

## Python package set

The complete pinned installation set is in [requirements.txt](../requirements.txt).
Major components are:

| Package | Pinned version | Role |
| --- | --- | --- |
| FastAPI | 0.141.1 | Web routes and API framework |
| Uvicorn | 0.52.4 | Application HTTP server, bound to loopback behind Caddy |
| Starlette | 1.6.0 | Underlying web framework |
| Pydantic / pydantic_core | 2.13.5 / 2.46.5 | Request and configuration validation |
| AnyIO | 4.15.1 | Asynchronous support used by the framework |
| HTTPX | 0.28.1 | HTTP testing and setup/verification helpers; also imported by the launcher on Linux, so required in the application environment |

The remaining pinned packages support these components: annotated-doc,
annotated-types, certifi, click, h11, httpcore, idna, typing-inspection, and
typing_extensions. Install the full pinned file in the virtual environment.
The pins were tested locally on Windows/Python 3.12; installation and the
application tests still need to pass on Linux. The Python tests use the built-in
`unittest` runner. Prefer available binary wheels;
no compiler, Rust toolchain, or Python development headers are in the initial
installation proposal. Reassess if a required wheel is unavailable.

## Existing facilities to reuse

| Facility | Verified on the host | Installation implication |
| --- | --- | --- |
| Git and SSH | Git 2.50.1, OpenSSH clients 8.7p1; GitHub authenticates as `mikepfrank` and exposes `codex/hosted-chess` at `736ec22` | Ready to clone under `/home/astra`, using the existing key. |
| SQLite | SQLite 3.40.0, including working Python 3.11 bindings | Embedded database; no separate database server. Check Python 3.12 bindings after installation. |
| systemd | Version 252.23 | Available for startup, restart, journals, and service resource limits. Add a service unit after review. |
| TLS support | OpenSSL 3.2.2 and CA certificates installed | Reuse OS TLS support; verify it through the selected Python environment. |
| Download/archive utilities | `curl-minimal` 8.11.1 provides `/usr/bin/curl`; tar and gzip installed | Existing tools can retrieve and unpack verified release artifacts. |
| Codex bundle | `/home/astra/.local/bin/codex` resolves into `~/.codex/packages/standalone/releases/0.154.0-x86_64-unknown-linux-musl/` | Bundle contains `bin/codex`, `bin/codex-code-mode-host`, `codex-path/rg`, and `codex-resources/bwrap`. File presence and CLI help were checked; the complete Linux player/sandbox workflow has not been exercised. |
| OpenAI API credential | `OPENAI_API_KEY` was nonempty and exported in the login environment | Supply it explicitly to the eventual service environment. A systemd service does not automatically source the account's login profile. No credential value was recorded and no model request was made for this inventory. |

The installed standalone Codex CLI runs without Node or npm; neither is on
`astra`'s PATH. Keep the complete Codex release bundle available rather than
copying only its main executable. The separate code-mode host is required by
this application's audited configuration.

## Optional or deferred

| Component | When it is needed |
| --- | --- |
| `chess==1.11.2` from [requirements-replay.txt](../requirements-replay.txt) | Building downloadable standalone HTML archives with the existing replay builder. It supplies rules and notation only, never the playing engine. The live game and the service's public replay pages do not require this archive-building dependency. |
| Node.js and browser test tooling | Optional server-side JavaScript syntax/browser QA. The frontend is static HTML/CSS/JavaScript with no Node build pipeline; browser checks can remain on the laptop. |
| Pillow | Optional original-project PNG rendering. Not needed for the live board or the standard-library tactical engine. |
| Outbound SMTP provider | Password-reset email. The application already implements SMTP with STARTTLS or implicit TLS. Configure a verified sender, provider credentials if required, and the provider's DNS records; perform a delivery test. A local mail server is not required. |
| Backup destination and scheduling | Durable protection of the private database, game evidence, and Codex continuation state. Existing system tools can schedule a coordinated backup; storage destination and retention still need selection. |

The initial application uses SQLite, standard-library password hashing/SMTP,
static SVG pieces, and the in-repository chess engine. It has no runtime
requirement for PostgreSQL/MySQL, Redis, a separate task-queue service, Docker,
an external chess engine, or a GPU.

## Layout and deployment configuration still to prepare

A clone at `/home/astra/astra-chess` on branch `codex/hosted-chess` is a suitable
working checkout, as authorized by Mike. The existing
[systemd template](../deploy/astra-chess.service) instead names user
`astra-chess`, code under `/srv`, and Codex under `/opt`, and sets
`ProtectHome=true`. It must be adapted before it can use the `astra` account and
home-directory installations. Preserve restricted source/runtime access and
private writable game storage while making the required paths accessible;
keep SSH keys and the operator's Codex login out of player environments.

Before public access, configuration also needs the chosen hostname, matching
`ASTRA_ORIGIN`, DNS pointing to the host, and inbound HTTP/HTTPS access. Caddy
will forward to a single application worker on `127.0.0.1:8788`; this version
must not run multiple Uvicorn workers against the same game directory. Retain
the proposed single concurrent Astra action initially. CPU/memory/process
limits, restart recovery, Codex compatibility, and an actual API-backed turn
remain deployment checks, not established results from this inventory.

Mike requested review of this inventory before installation. The next step is
his review of Python 3.12, the pinned Python environment, Caddy, and the Codex
compatibility work; optional email and archive dependencies can be staged later.
