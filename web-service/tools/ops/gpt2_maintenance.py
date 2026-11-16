#!/usr/bin/env python3
"""GPT-2-only maintenance gates and lifecycle, for the reviewed Lightsail host.

This is not an automatic updater. Preparation and check do not gate traffic.
See validation/2026-11-16-security-prep/gpt2-maintenance.md. No model calls,
credentials, chat contents, or private capability URLs are printed.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time
import uuid

PUBLIC = "gpt2-public.service"
LAB = "gpt2-codex.service"
NETWORK = "gpt2-codex-network.service"
PROXY = "astra-caddy.service"
HOSTS = {PUBLIC: "gpt2-chat.com", LAB: "codex-test.gpt2-chat.com"}
PORTS = {PUBLIC: 8899, LAB: 8900}
CONFIG = Path("/home/astra/.config/astra-chess/Caddyfile")
CADDY = Path("/home/astra/.local/bin/caddy")
STATE_DIR = Path("/var/lib/gpt2-maintenance-ops")
STATE_FILE = STATE_DIR / "maintenance.json"
PROXY_LOCK = Path("/run/lock/astra-caddy-config.lock")
VENV = Path("/home/gpt-2/.venvs/gpt2-public/bin/python")
LAB_DB = Path("/home/gpt-2/.local/share/gpt2-codex/chats.sqlite3")
LAB_SOURCE = Path("/home/gpt-2/GPT-2-codex/src/gpt2_local/codex_chat.py")
LAB_SOURCE_SHA = "4566d1162eca5f6155da408a8671af03d0611d1f1bc84e19fb1dfba020beac37"
BODY = {"error": "GPT-2 is temporarily paused for host maintenance. Please retry later.", "accepted": False}
PHASES = {"prepared", "gated", "stopping", "stopped", "starting", "started", "open"}


class SafetyError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise SafetyError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def command(args, *, user=None, timeout=30):
    if user:
        require(user in {"astra", "gpt-2"}, "Unexpected execution account")
        args = ["/usr/sbin/runuser", "-u", user, "--", *map(str, args)]
    result = subprocess.run(list(map(str, args)), capture_output=True, text=True, timeout=timeout)
    # No arbitrary stdout/stderr in exceptions: config and URLs can be private.
    require(result.returncode == 0, "Operator subprocess failed; inspect privately (exit %d)" % result.returncode)
    return result.stdout


def unit(name):
    require(name in {PUBLIC, LAB, NETWORK, PROXY}, "Unexpected unit")
    raw = command(["systemctl", "show", name, "-p", "LoadState", "-p", "ActiveState",
                   "-p", "SubState", "-p", "MainPID", "-p", "ControlGroup",
                   "-p", "ExecMainStartTimestampMonotonic", "-p", "UnitFileState", "-p", "Result"])
    value = dict(line.split("=", 1) for line in raw.splitlines() if "=" in line)
    require(value.get("LoadState") == "loaded", "Required unit is not loaded: " + name)
    return value


def identity(info):
    return [info["MainPID"], info["ExecMainStartTimestampMonotonic"]]


def control(action, name):
    require(action in {"start", "stop", "enable", "disable"} and name in {PUBLIC, LAB}, "Unsupported lifecycle action")
    print(action + " " + name, flush=True)
    command(["systemctl", action, name], timeout=200)


@contextmanager
def lock(path):
    import fcntl
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == 0, "Unsafe lock file")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SafetyError("Another operator holds the maintenance lock") from None
        yield
    finally:
        os.close(fd)


def secure_directory():
    STATE_DIR.mkdir(mode=0o700, exist_ok=True)
    info = STATE_DIR.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o077,
            "Maintenance directory must be root-owned/private")


def atomic_write(path, data):
    require(not path.is_symlink(), "Refusing a symlink checkpoint")
    fd, temporary = tempfile.mkstemp(prefix=".checkpoint-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def save(state):
    atomic_write(STATE_FILE, (json.dumps(state, indent=2) + "\n").encode())


def load():
    info = STATE_FILE.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o077
            and info.st_size < 1024 * 1024, "Unsafe maintenance checkpoint")
    value = json.loads(STATE_FILE.read_text())
    require(value.get("schema") == 1 and re.fullmatch("[0-9a-f]{32}", value.get("marker", "")), "Unknown checkpoint")
    require(set(value.get("services", {})) == set(HOSTS), "Incomplete checkpoint")
    for name, item in value["services"].items():
        require(item.get("phase") in PHASES and item.get("enabled") in {"enabled", "disabled"}, "Invalid saved service state")
        require(site_block(item["original"], HOSTS[name]) == item["original"], "Invalid saved proxy block")
        normal_block(name, item["original"])
    return value


def site_span(text, host):
    require(host in HOSTS.values(), "Unsupported hostname")
    matches = list(re.finditer(r"(?m)^" + re.escape(host) + r" \{\n", text))
    require(len(matches) == 1, "Expected one standalone GPT-2 site block")
    start = matches[0].start()
    end = re.search(r"(?m)^\}[ \t]*(?:\n|$)", text[matches[0].end():])
    require(end is not None, "Unclosed GPT-2 site block")
    return start, matches[0].end() + end.end()


def site_block(text, host):
    start, end = site_span(text, host)
    return text[start:end]


def normal_block(name, block):
    require("gpt2_host_maintenance" not in block and "X-GPT2-Maintenance" not in block,
            "Unexpected existing maintenance gate")
    expected = "reverse_proxy 127.0.0.1:" + str(PORTS[name])
    require(block.count(expected) == 1 and block.count("reverse_proxy") == 1,
            "GPT-2 proxy layout differs from reviewed profile")
    if name == LAB:
        require("    @beta path " in block and "    handle @beta {\n" in block,
                "Private lab scoped route differs from reviewed profile")


def gate_fragment(marker, name):
    require(re.fullmatch("[0-9a-f]{32}", marker), "Invalid maintenance marker")
    matcher = "@gpt2_host_maintenance"
    if name == PUBLIC:
        prefix = ("    @gpt2_host_maintenance {\n        method POST\n"
                  "        path /api/message /api/regenerate\n    }\n")
    else:
        # Gate only the existing private capability route, preserving outer 404.
        prefix, matcher = "", ""
    indent = "        " if name == LAB else "    "
    match = (matcher + " ") if matcher else ""
    body = json.dumps(json.dumps(BODY, separators=(",", ":")))
    return prefix + "".join(indent + line + "\n" for line in (
        "header " + match + "Content-Type application/json",
        "header " + match + "Cache-Control no-store",
        "header " + match + "Retry-After 60",
        "header " + match + "X-GPT2-Maintenance " + marker,
        "respond " + match + body + " 503"))


def gated_block(name, original, marker):
    normal_block(name, original)
    anchor = HOSTS[name] + " {\n" if name == PUBLIC else "    handle @beta {\n"
    require(original.count(anchor) == 1, "Ambiguous insertion point")
    return original.replace(anchor, anchor + gate_fragment(marker, name), 1)


def replace_block(text, name, expected, replacement):
    start, end = site_span(text, HOSTS[name])
    require(text[start:end] == expected, "GPT-2 block changed independently; refusing overwrite")
    return text[:start] + replacement + text[end:]


def check_proxy_mount():
    info = unit(PROXY)
    require(info["ActiveState"] == "active" and int(info["MainPID"]) > 0, "Proxy is not active")
    mounted = Path("/proc") / info["MainPID"] / "root" / str(CONFIG).lstrip("/")
    local = CONFIG.lstat()
    require(stat.S_ISREG(local.st_mode) and not local.st_mode & 0o022, "Unsafe Caddyfile")
    require(local.st_ino == mounted.stat().st_ino and CONFIG.read_bytes() == mounted.read_bytes(), "Caddy file bind is stale")
    argv = (Path("/proc") / info["MainPID"] / "cmdline").read_bytes().split(b"\0")
    require(b"run" in argv and b"--resume" not in argv and b"--watch" not in argv and str(CONFIG).encode() in argv,
            "Proxy is not using expected file-based startup")
    require("admin off" in CONFIG.read_text(), "Proxy admin-off profile changed")
    version = re.match(r"v(\d+)\.(\d+)\.(\d+)", command([CADDY, "version"]))
    require(version and tuple(map(int, version.groups())) >= (2, 11, 0), "File reload requires reviewed Caddy 2.11+ behavior")
    require(digest(CADDY.read_bytes()) == digest((Path("/proc") / info["MainPID"] / "exe").read_bytes()),
            "Installed/running proxy binaries differ")
    return info, local


def validate_config(data):
    # Stage beside Caddyfile so relative imports still resolve. Only astra/root can read.
    info = CONFIG.stat()
    fd, path = tempfile.mkstemp(prefix=".gpt2-maintenance-check-", dir=CONFIG.parent)
    try:
        os.fchown(fd, info.st_uid, info.st_gid)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        adapted = json.loads(command([str(CADDY), "adapt", "--config", path, "--adapter", "caddyfile"], user="astra"))
        def dials(obj):
            if isinstance(obj, dict):
                for key, value in obj.items():
                    if key == "dial" and isinstance(value, str):
                        yield value
                    yield from dials(value)
            elif isinstance(obj, list):
                for value in obj:
                    yield from dials(value)
        ports = list(dials(adapted))
        for port in PORTS.values():
            require([v for v in ports if v.endswith(":" + str(port))] == ["127.0.0.1:" + str(port)],
                    "Unexpected alternate GPT-2 upstream")
        command([str(CADDY), "validate", "--config", path, "--adapter", "caddyfile"], user="astra")
    finally:
        Path(path).unlink(missing_ok=True)


def rewrite_config(expected, replacement, original_info):
    fd = os.open(CONFIG, os.O_RDWR | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        require((info.st_dev, info.st_ino) == (original_info.st_dev, original_info.st_ino), "Caddy inode changed")
        with os.fdopen(fd, "r+b", closefd=False) as stream:
            require(stream.read() == expected, "Caddyfile changed during validation")
            stream.seek(0)
            stream.write(replacement)
            stream.truncate()
            stream.flush()
            os.fsync(fd)
    finally:
        os.close(fd)


def reload_proxy():
    raw = command(["journalctl", "-u", PROXY, "-n", "1", "--show-cursor", "--no-pager", "-o", "cat"])
    cursors = [line.removeprefix("-- cursor: ") for line in raw.splitlines() if line.startswith("-- cursor: ")]
    require(len(cursors) == 1, "No proxy journal cursor")
    command(["systemctl", "kill", "--kill-whom=main", "--signal=SIGUSR1", PROXY])
    end = time.monotonic() + 20
    while time.monotonic() < end:
        logs = command(["journalctl", "-u", PROXY, "--after-cursor", cursors[0], "--no-pager", "-o", "cat"])
        require("failed to reload config from file" not in logs and "ignored SIGUSR1" not in logs, "Proxy rejected file reload")
        if "successfully reloaded config from file" in logs:
            return
        time.sleep(.5)
    raise SafetyError("Proxy reload confirmation timed out")


def lab_path():
    raw = Path("/etc/gpt2-codex.env").read_text()
    values = [line.split("=", 1)[1].strip().strip("\"'") for line in raw.splitlines()
              if line.startswith("GPT2_CODEX_BASE_PATH=")]
    require(len(values) == 1 and re.fullmatch(r"/[A-Za-z0-9_/-]+", values[0]), "Unexpected private route configuration")
    return values[0].rstrip("/")


def request(name, path, *, proxy=False, post=False):
    host = HOSTS[name]
    args = ["curl", "--silent", "--show-error", "--noproxy", "*", "--max-time", "10",
            "--dump-header", "-", "--write-out", "\n%{http_code}"]
    if proxy:
        args += ["--resolve", host + ":443:127.0.0.1", "https://" + host + path]
    else:
        args += ["--header", "Host: " + host, "http://127.0.0.1:" + str(PORTS[name]) + path]
    if post:
        # Empty object can never start generation; gate check must still reject at proxy.
        args += ["--header", "Content-Type: application/json", "--header", "Origin: https://" + host, "--data-binary", "{}"]
    raw, status = command(args, timeout=12).replace("\r\n", "\n").rsplit("\n", 1)
    headers, body = raw.split("\n\n", 1)
    return int(status), headers.lower(), body


def health(name):
    path = "/api/health" if name == PUBLIC else lab_path() + "/health"
    status, _, body = request(name, path)
    require(status == 200, "GPT-2 backend health failed")
    data = json.loads(body)
    require(data.get("status") == "ready" if name == PUBLIC else data == {"ok": True, "application": "gpt2-codex"},
            "Unexpected GPT-2 backend health response")
    return data


def verify_gate(state, name):
    paths = ("/api/message", "/api/regenerate") if name == PUBLIC else (lab_path() + "/health",)
    for path in paths:
        status, headers, body = request(name, path, proxy=True, post=(name == PUBLIC))
        require(status == 503 and "x-gpt2-maintenance: " + state["marker"] in headers
                and json.loads(body).get("accepted") is False, "Maintenance response not confirmed")
    if name == PUBLIC and unit(PUBLIC)["ActiveState"] == "active":
        require(request(PUBLIC, "/api/health", proxy=True)[0] == 200, "Public result/health access must remain available during drain")


def change_proxy(state, name, gated):
    # Caller holds shared proxy lock. Never restore an entire historical config.
    old_info, file_info = check_proxy_mount()
    before = CONFIG.read_bytes()
    original = state["services"][name]["original"]
    gate = gated_block(name, original, state["marker"])
    current = site_block(before.decode(), HOSTS[name])
    require(current in (original, gate), "GPT-2 block differs from maintenance checkpoint")
    desired = gate if gated else original
    candidate = replace_block(before.decode(), name, current, desired).encode()
    validate_config(candidate)
    if candidate != before:
        rewrite_config(before, candidate, file_info)
    # Reconfirm even after interruption between writing and reloading.
    reload_proxy()
    new_info, _ = check_proxy_mount()
    require(identity(new_info) == identity(old_info), "Proxy unexpectedly restarted during reload")
    if gated:
        verify_gate(state, name)
    else:
        path = "/api/health" if name == PUBLIC else lab_path() + "/health"
        require(request(name, path, proxy=True)[0] == 200, "Restored HTTPS health failed")


def cgroup_pids(info):
    root = Path("/sys/fs/cgroup")
    group = (root / info["ControlGroup"].lstrip("/")).resolve()
    require(root in group.parents, "Invalid service cgroup")
    found = set()
    for p in group.rglob("cgroup.procs"):
        try:
            found.update(int(x) for x in p.read_text().split())
        except FileNotFoundError:
            continue
    return found


def lab_activity():
    require(digest(LAB_SOURCE.read_bytes()) == LAB_SOURCE_SHA, "Lab source changed; re-review presence/scheduler semantics")
    code = ("import sqlite3,json,collections; "
            "c=sqlite3.connect(" + repr("file:" + str(LAB_DB) + "?mode=ro") + ",uri=True); "
            "rows=[json.loads(r[0]) for r in c.execute('select record from sessions')]; "
            "print(json.dumps({'sessions':len(rows),'statuses':dict(collections.Counter(r.get('status','unknown') for r in rows)),"
            "'pending_human':sum(bool(r.get('pending_human')) for r in rows)}))")
    data = json.loads(command([VENV, "-I", "-B", "-c", code], user="gpt-2"))
    ids = command(["docker", "ps", "-q", "--filter", "label=io.gpt2-codex=sandbox"]).splitlines()
    info = unit(LAB)
    require(info["ActiveState"] == "active" and int(info["MainPID"]) > 0, "Private lab is not active")
    data["containers"] = len(ids)
    pids = cgroup_pids(info)
    require(int(info["MainPID"]) in pids, "Lab main process absent from cgroup")
    data["children"] = len(pids - {int(info["MainPID"])})
    data["idle"] = not (set(data["statuses"]) - {"idle", "error"}) and not ids and data["children"] == 0
    return data


def settled(name):
    raw = command(["ss", "-H", "-t", "-a", "-n", "sport = :" + str(PORTS[name])])
    return not any(line.split()[0] not in {"LISTEN", "TIME-WAIT"} for line in raw.splitlines())


def retain_public(observe, connections_settled, *, timeout=1200, clock=time.monotonic, sleep=time.sleep, emit=print):
    """Pure/injectable retention policy. Never infer success from timeout."""
    deadline, since = clock() + timeout, None
    while True:
        data = observe()
        queue = data.get("queue")
        require(isinstance(queue, dict) and type(queue.get("waiting")) is int and queue["waiting"] >= 0
                and type(queue.get("running")) is bool, "Invalid queue observation")
        ttl = data.get("limits", {}).get("result_ttl_seconds")
        require(type(ttl) is int and 0 < ttl <= 86400, "Invalid result retention limit")
        ttl = max(600, ttl)
        idle = queue == {"waiting": 0, "running": False}
        if not idle:
            since = None
        elif since is None and connections_settled():
            if observe().get("queue") == {"waiting": 0, "running": False}:
                since = clock()
                emit("Public queue drained; preserving result access for %d seconds." % ttl)
        if since is not None and clock() - since >= ttl:
            require(observe().get("queue") == {"waiting": 0, "running": False}, "Queue changed at retention boundary")
            return ttl
        require(clock() < deadline, "Public drain/retention timed out; service remains running behind its gate")
        sleep(min(5, deadline - clock()))


def quiet_lab(state, *, timeout=120, clock=time.monotonic, sleep=time.sleep):
    deadline, since = clock() + timeout, None
    expected = state["services"][LAB]["identity"]
    while True:
        require(identity(unit(LAB)) == expected, "Lab restarted during idle check")
        data = lab_activity()
        # Wait longer than the reviewed 45s browser-presence TTL, with tabs already closed.
        idle = data["idle"] and settled(LAB)
        since = clock() if idle and since is None else since if idle else None
        if since is not None and clock() - since >= 60:
            return
        require(clock() < deadline, "Private lab is not quiet; no gate/stop performed")
        sleep(min(5, deadline - clock()))


def prepare():
    require(not STATE_FILE.exists(), "Existing checkpoint; use status/resume instead")
    check_proxy_mount()
    text = CONFIG.read_text()
    state = {"schema": 1, "marker": uuid.uuid4().hex, "created_at_unix": time.time(), "services": {},
             "network_enabled": unit(NETWORK)["UnitFileState"], "network_active": unit(NETWORK)["ActiveState"]}
    for name, host in HOSTS.items():
        info = unit(name)
        require(info["ActiveState"] == "active" and info["UnitFileState"] in {"enabled", "disabled"}, "Unsupported GPT-2 startup state")
        original = site_block(text, host)
        normal_block(name, original)
        state["services"][name] = {"phase": "prepared", "enabled": info["UnitFileState"], "identity": identity(info), "original": original}
        text = replace_block(text, name, original, gated_block(name, original, state["marker"]))
        health(name)
    validate_config(text.encode())
    atomic_write(STATE_DIR / ("Caddyfile-" + state["marker"] + ".backup"), CONFIG.read_bytes())
    save(state)
    print("Prepared private checkpoint and validated gates; public traffic unchanged.")


def gate(state, name, owner_idle):
    item = state["services"][name]
    require(item["phase"] in {"prepared", "gated"}, "Service is not in a gateable phase")
    require(identity(unit(name)) == item["identity"], "GPT-2 process changed since preparation")
    if name == LAB:
        require(owner_idle, "Private lab requires owner-confirmed tabs closed/paused after work finished")
        quiet_lab(state)
    with lock(PROXY_LOCK):
        if name == LAB:
            require(lab_activity()["idle"] and settled(LAB), "Private work appeared before gating")
        change_proxy(state, name, True)
    item["phase"] = "gated"
    save(state)
    print("Maintenance gate active: " + name)


def stop(state, name, timeout):
    item = state["services"][name]
    require(item["phase"] in {"gated", "stopping", "stopped"}, "Gate traffic before stopping")
    if unit(name)["ActiveState"] == "inactive":
        require(item["phase"] in {"stopping", "stopped"}, "Service stopped unexpectedly")
    else:
        require(identity(unit(name)) == item["identity"], "GPT-2 process changed during maintenance")
        if name == PUBLIC:
            verify_gate(state, name)
            retain_public(lambda: health(PUBLIC), lambda: settled(PUBLIC), timeout=timeout)
        else:
            require(lab_activity()["idle"] and settled(LAB), "Private lab is busy; refusing stop")
        with lock(PROXY_LOCK):
            require(site_block(CONFIG.read_text(), HOSTS[name]) == gated_block(name, item["original"], state["marker"]), "Gate configuration changed")
            verify_gate(state, name)
            require(identity(unit(name)) == item["identity"], "Process changed at final stop check")
            if name == PUBLIC:
                require(health(name).get("queue") == {"waiting": 0, "running": False} and settled(name), "Public work/connections appeared before stop")
            else:
                require(lab_activity()["idle"] and settled(name), "Private work appeared before stop")
            item["phase"] = "stopping"
            save(state)
            control("disable", name)
            control("stop", name)
    control("disable", name)
    info = unit(name)
    require(info["ActiveState"] == "inactive" and info["MainPID"] == "0" and info["UnitFileState"] == "disabled"
            and info["Result"] == "success", "GPT-2 did not stop cleanly")
    item["phase"] = "stopped"
    save(state)
    print("Stopped and disabled; checkpoint retained: " + name)


def start(state, name):
    item = state["services"][name]
    require(item["phase"] in {"stopped", "starting", "started"}, "Service is not in a startable phase")
    if name == LAB:
        require(state["services"][PUBLIC]["phase"] == "started", "Start/validate public GPT-2 before private lab")
        require(unit(NETWORK)["ActiveState"] == "active", "Validate/re-establish private Docker isolation before lab startup")
    with lock(PROXY_LOCK):
        require(site_block(CONFIG.read_text(), HOSTS[name]) == gated_block(name, item["original"], state["marker"]), "Gate must remain installed during startup")
        item["phase"] = "starting"
        save(state)
        control("start", name)
    deadline = time.monotonic() + 180
    while True:
        try:
            health(name)
            break
        except (SafetyError, ValueError):
            require(time.monotonic() < deadline, "GPT-2 startup readiness timed out; gate retained")
            time.sleep(2)
    item["phase"] = "started"
    save(state)
    print("Started behind maintenance gate; perform regression tests: " + name)


def reopen(state, validated):
    require(validated, "Explicit completed-regression acknowledgement required")
    for name, item in state["services"].items():
        require(item["phase"] in {"prepared", "gated", "started", "open"}, "Start apps and finish validation before reopening")
        health(name)
    for name, item in state["services"].items():
        with lock(PROXY_LOCK):
            change_proxy(state, name, False)
        control("enable" if item["enabled"] == "enabled" else "disable", name)
        item["phase"] = "open"
        save(state)
    archive = STATE_DIR / ("completed-" + state["marker"] + ".json")
    atomic_write(archive, (json.dumps(state, indent=2) + "\n").encode())
    STATE_FILE.unlink()
    directory = os.open(STATE_DIR, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    print("GPT-2 routes and saved boot settings restored; completed checkpoint archived.")


def check():
    check_proxy_mount()
    for name in HOSTS:
        normal_block(name, site_block(CONFIG.read_text(), HOSTS[name]))
        health(name)
    print(json.dumps({"public_queue": health(PUBLIC)["queue"], "lab_activity": lab_activity()}, sort_keys=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "prepare", "status", "gate-public", "gate-lab", "stop-public", "stop-lab", "start-public", "start-lab", "reopen"))
    parser.add_argument("--owner-idle", action="store_true", help="Operator confirmed private lab tabs closed/paused only after their work finished")
    parser.add_argument("--validated", action="store_true", help="Operator completed required regression/isolation checks")
    parser.add_argument("--timeout", type=int, default=1200)
    args = parser.parse_args()
    require(sys.platform == "linux" and os.geteuid() == 0, "Run only as root on the reviewed Linux host")
    require(600 <= args.timeout <= 7200, "Drain timeout must be between 600 and 7200 seconds")
    if args.action == "check":
        check()
        return
    secure_directory()
    with lock(STATE_DIR / "operation.lock"):
        if args.action == "prepare":
            with lock(PROXY_LOCK):
                prepare()
            return
        state = load()
        if args.action == "status":
            print(json.dumps({"marker": state["marker"], "services": {n: {"phase": v["phase"], "unit": unit(n)} for n, v in state["services"].items()}}, sort_keys=True))
        elif args.action.startswith("gate-"):
            gate(state, PUBLIC if args.action.endswith("public") else LAB, args.owner_idle)
        elif args.action.startswith("stop-"):
            stop(state, PUBLIC if args.action.endswith("public") else LAB, args.timeout)
        elif args.action.startswith("start-"):
            start(state, PUBLIC if args.action.endswith("public") else LAB)
        else:
            reopen(state, args.validated)


if __name__ == "__main__":
    try:
        main()
    except (SafetyError, OSError, ValueError, subprocess.SubprocessError) as error:
        print("Maintenance halted: " + (str(error) if isinstance(error, SafetyError) else type(error).__name__) + ". Checkpoint retained; do not bypass it.", file=sys.stderr)
        raise SystemExit(1)
