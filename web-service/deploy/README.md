# Home-directory Linux service

The system unit runs as `astra:astra`. Application files remain under
`/home/astra`; the small unit file belongs in
`/etc/systemd/system/astra-chess.service`. A system unit is preferred here
because PID1 can establish the filesystem namespace and enforce aggregate
resource limits without depending on a login session or a user manager's
namespace support. The unit binds only to `127.0.0.1:8788`. It installs no proxy
and makes no changes to other services.

| Host path | Visible to service | Purpose |
| --- | --- | --- |
| `/home/astra/astra-chess` | Read-only | Repository and `web-service/.venv` |
| `/home/astra/.local/share/astra-chess-runtime` | Read-only | User-installed Python, including the virtual environment's interpreter target and standard library |
| `/home/astra/.codex/packages/standalone/releases/0.154.0-x86_64-unknown-linux-musl` | Read-only | Entire pinned native Codex release |
| `/home/astra/.local/share/astra-chess` | Read/write | SQLite, per-game Codex homes, queries and other private state |
| `/home/astra/.config/astra-chess/service.env` | Hidden as a file | PID1 reads the protected environment before namespace setup |

Create the data and configuration directories before starting the unit, owned
by `astra:astra` with mode `0700`; give `service.env` mode `0600`. The bind mount
sources must exist. The unit deliberately does not use `StateDirectory=`, which
would create a system-service directory under `/var/lib`. It retains systemd's
usual journal and private temporary-directory handling outside the home tree.

Build the Python 3.12 virtual environment at
`/home/astra/astra-chess/web-service/.venv` using the runtime under
`/home/astra/.local/share/astra-chess-runtime/python`, and install the pinned
requirements before enabling the read-only service view. The runtime bind
preserves access through its versioned interpreter symlinks and to its standard
library. Dependencies remain readable in
that view; bytecode writes and user-site imports are disabled. Operator updates
to the repository and virtual environment happen outside the service namespace,
with the service stopped when its engine or runtime changes.

Copy `service.env.example` to the configuration path and supply the API key
through the protected environment. Keep the initial loopback origin until the
hostname and HTTPS proxy are configured. Environment-file values override unit
`Environment=` defaults; retain `ASTRA_MAX_WORKERS=1` for this deployment and do
not override the data/executable paths without also updating the bind mounts.
The bridge gives each game its own `HOME`, `CODEX_HOME` and temporary directory
below the private data directory. It does not use the operator's Codex login.

The executable path bypasses the operator's launcher symlink. Preserve the
entire matching release, including `bin/codex-code-mode-host`,
`codex-resources/bwrap` and `codex-path/rg`. The application bridge must accept
and validate the same CLI version before enabling player traffic. This template
targets the installed 0.154.0 bundle; updating a path does not establish CLI
compatibility. Do not add a blanket namespace restriction or
`MemoryDenyWriteExecute=true`: the bundled sandbox and V8 runtime require
compatible namespace and executable-memory behavior.

`ProtectHome=tmpfs` masks `/home`, `/root` and `/run/user`, while the explicit
binds expose only the paths above. Other homes, `/home/astra/.ssh`, the operator's
Codex authentication/configuration, and the service environment file are not
mounted into this filesystem view. `ProtectProc=invisible` also hides processes
belonging to other users where the kernel supports it. These are service
restrictions, not a claim of isolation from every other process sharing the
`astra` UID; keep operator activity under that account trusted.

Limits cover the web process and all descendants together: `CPUQuota=100%`,
`MemoryMax=2G`, `TasksMax=64`, and `LimitNOFILE=1024`. The CPU quota is one logical
CPU of aggregate time. It does not reserve a core or set a per-game allowance.

Before enabling traffic, the operator should run `systemd-analyze verify` on
the installed unit, then check the actual namespace and limits on the target
host. Confirm read access to the repository and complete Codex release, write
access only to private state and temporary storage, and absence of the hidden
home/configuration paths. Exercise native code-mode startup and an isolated
player action under the unit, including descendant cleanup and state recovery
on restart. A standalone CLI help/version check outside systemd cannot validate
these combined restrictions. Do not relax the mounts or runtime restrictions
silently if a check fails.

The directives were checked against the
[systemd 252 execution manual](https://manpages.debian.org/bookworm/systemd/systemd.exec.5.en.html#ProtectHome=):
it documents selective bind mounts with `ProtectHome=tmpfs`, system-manager
reading of `EnvironmentFile=` before mount setup, and the JIT limitation of
`MemoryDenyWriteExecute=`. This is a source-reviewed template; installing and
validating it on Amazon Linux is a separate step.
