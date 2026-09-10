"""Run an operator check with the installed system unit's restrictions.

Invoke through sudo on the deployment host. A transient unit runs as astra;
systemd reads the protected environment file, so its secrets are never copied
into this program's arguments or output. The live mode makes paid model calls.
"""
import argparse
from collections import defaultdict
import os
from pathlib import Path
import secrets
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("preflight", "protocol", "live"))
    parser.add_argument("--live", action="store_true", help="Authorize the live mode's two paid model actions")
    args = parser.parse_args()
    if args.mode == "live" and not args.live:
        parser.error("The live check requires --live.")
    if os.geteuid() != 0:
        parser.error("Run via sudo; the transient unit will execute as astra.")
    unit = Path("/etc/systemd/system/astra-chess.service")
    props = defaultdict(list)
    in_service = False
    ignored = {"Type", "ExecStart", "Restart", "RestartSec", "TimeoutStopSec"}
    for raw in unit.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            in_service = line == "[Service]"
        elif in_service:
            key, value = line.split("=", 1)
            if key not in ignored:
                props[key].append(value)
    if props.get("User") != ["astra"] or props.get("Group") != ["astra"]:
        parser.error("Installed unit must run as astra:astra.")
    app = Path("/home/astra/astra-chess/web-service")
    data = Path("/home/astra/.local/share/astra-chess")
    check_id = secrets.token_hex(5)
    command = ["systemd-run", "--quiet", "--collect", "--wait", "--pipe",
               "--service-type=exec", f"--unit=astra-chess-check-{args.mode}-{check_id}"]
    for key, values in props.items():
        command.append("--property=" + key + "=" + " ".join(values))
    command.append(str(app / ".venv/bin/python"))
    if args.mode == "preflight":
        command.append(str(app / "tools/check_linux_service.py"))
    elif args.mode == "protocol":
        command.extend([str(app / "tests/audit_codex_protocol.py"),
                        "--audit-dir", str(data / "operator-checks/protocol")])
    else:
        command.extend([str(app / "tests/live_codex_check.py"), "--live", "--turns", "2",
                        "--codex-bin", "/home/astra/.codex/packages/standalone/releases/0.154.0-x86_64-unknown-linux-musl/bin/codex",
                        "--data-dir", str(data / f"operator-checks/live-{check_id}")])
    print(f"Starting {args.mode} check with installed service properties.", flush=True)
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
