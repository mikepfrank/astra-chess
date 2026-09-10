"""Operator preflight inside the deployed systemd filesystem/resource boundary.

Run as the service user with the service's unit properties and environment.
No model requests, credential output, or writes outside disposable probe files.
"""
import errno
import hashlib
import json
import os
from pathlib import Path
import pwd
import sqlite3
import subprocess
import sys
import tempfile


APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))
from astra_web.config import Config


def main():
    if sys.platform != "linux":
        raise SystemExit("This check requires Linux and the deployed service namespace.")
    config = Config()
    checks = {}
    checks["service_user"] = pwd.getpwuid(os.getuid()).pw_name == "astra"
    checks["api_key_present"] = bool(os.environ.get("OPENAI_API_KEY"))
    checks["python_312"] = sys.version_info[:2] == (3, 12)
    checks["password_hashing"] = len(hashlib.scrypt(
        b"preflight", salt=b"disposable-test-salt", n=32768, r=8, p=3,
        dklen=64, maxmem=64 * 1024 * 1024)) == 64
    checks["repository_readable"] = (APP_ROOT.parent / "astra_engine/rules.py").is_file()
    checks["codex_bundle"] = all((Path(config.codex_bin).parent.parent / name).is_file()
        for name in ("bin/codex", "bin/codex-code-mode-host", "codex-resources/bwrap"))
    hidden = ("/home/astra/.ssh", "/home/astra/.codex/auth.json",
              "/home/astra/.codex/config.toml", "/home/astra/.config/astra-chess/service.env",
              "/home/ec2-user/.ssh")
    checks["operator_files_hidden"] = all(not Path(path).exists() for path in hidden)
    checks["source_read_only"] = False
    try:
        with tempfile.NamedTemporaryFile(prefix=".astra-permission-probe-", dir=APP_ROOT):
            pass
    except OSError as error:
        checks["source_read_only"] = error.errno in (errno.EROFS, errno.EACCES)
    with tempfile.TemporaryDirectory(prefix="service-probe-", dir=config.data_dir) as scratch:
        database = Path(scratch) / "check.sqlite3"
        connection = sqlite3.connect(database)
        try:
            connection.execute("CREATE TABLE probe (value TEXT)")
            connection.execute("INSERT INTO probe VALUES ('ok')")
            connection.commit()
            checks["private_data_writable"] = connection.execute("SELECT value FROM probe").fetchone() == ("ok",)
        finally:
            connection.close()
    relative = next(line.split(":", 2)[2] for line in Path("/proc/self/cgroup").read_text().splitlines()
                    if line.startswith("0::"))
    cgroup = Path("/sys/fs/cgroup") / relative.lstrip("/")
    limits = {name: (cgroup / name).read_text().strip()
              for name in ("memory.max", "pids.max", "cpu.max")}
    checks["memory_limit"] = limits["memory.max"] == str(2 * 1024 ** 3)
    checks["process_limit"] = limits["pids.max"] == "64"
    quota, period = limits["cpu.max"].split()
    checks["cpu_limit"] = quota != "max" and int(quota) <= int(period)
    safe_env = {name: value for name, value in os.environ.items() if name != "OPENAI_API_KEY"}
    version = subprocess.run([config.codex_bin, "--version"], env=safe_env,
                             text=True, capture_output=True, timeout=15, check=True)
    print(json.dumps({"checks": checks, "limits": limits,
                      "python": sys.version.split()[0], "sqlite": sqlite3.sqlite_version,
                      "codex": version.stdout.strip()}, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
