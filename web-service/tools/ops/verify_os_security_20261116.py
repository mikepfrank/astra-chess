#!/usr/bin/env python3
"""Read-only OS checkpoint for the pinned November 2026 Lightsail maintenance.

Run as root after the OS reboot. Never starts applications, opens admission,
loads application constructors, or prints credentials/private capability URLs.
This checks configuration/state, not integrated sandbox network behavior.
"""
import datetime
import hashlib
import json
from pathlib import Path
import runpy
import stat
import subprocess
import tarfile


def command(args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise RuntimeError("Read-only check failed: " + args[0])
    return result.stdout.strip()


def main():
    result = {"checked_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    result["kernel"] = command(["uname", "-r"])
    assert result["kernel"] == "6.1.190-237.442.amzn2023.x86_64"
    result["release"] = Path("/etc/system-release").read_text().strip()
    assert "2023.12.20261112" in result["release"]
    result["boot_id"] = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    result["failed_units"] = command(["systemctl", "--failed", "--no-legend", "--no-pager"])
    assert not result["failed_units"]

    stopped = ["astra-chess.service", "or-chess.service", "gpt2-public.service",
               "gpt2-codex.service", "astra-game-notify.timer", "or-chess-game-notify.timer"]
    active = ["astra-caddy.service", "docker.service", "containerd.service",
              "gpt2-codex-network.service", "sshd.service", "amazon-ssm-agent.service"]
    result["units"] = {}
    for unit in stopped + active:
        fields = dict(line.split("=", 1) for line in command([
            "systemctl", "show", unit, "-p", "ActiveState", "-p", "SubState",
            "-p", "UnitFileState", "-p", "MainPID", "-p", "Result"]).splitlines())
        result["units"][unit] = fields
        assert fields["ActiveState"] == ("inactive" if unit in stopped else "active"), unit
        if unit in stopped:
            assert fields["UnitFileState"] == "disabled", unit
            assert fields.get("MainPID", "0") == "0", unit
    for unit in ["astra-game-notify.service", "or-chess-game-notify.service", "gpt2-preview.service"]:
        assert command(["systemctl", "show", unit, "--value", "-p", "ActiveState"]) == "inactive"

    stage = Path("/home/ec2-user/chess-security-stage-20261115/os")
    manifest = json.loads((stage / "rpm-manifest.json").read_text())
    assert len(manifest["files"]) == len({item["name"] for item in manifest["files"]}) == 274
    # DNF clears download-only RPMs after a successful transaction. The retained,
    # pre-install checksum manifest supplies exact name/version/release/arch.
    expected = {item["name"] for item in manifest["files"]}
    installed = set(command(["rpm", "-qa", "--qf",
                             "%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}.rpm\n"]).splitlines())
    missing = sorted(expected - installed)
    result["reviewed_rpms"] = {"count": len(expected), "missing": missing,
                               "comparison": "name/version/release/architecture"}
    assert not missing
    result["selected_packages"] = command(["rpm", "-q", "system-release", "kernel",
        "amazon-ssm-agent", "openssl", "openssh-server", "python3.12", "systemd",
        "glibc", "curl-minimal", "docker", "containerd", "runc"]).splitlines()

    gpt = runpy.run_path("/home/ec2-user/chess-security-stage-20261116/ops/gpt2_maintenance-v2.py",
                        run_name="os_gate_verification")
    state = gpt["load"]()
    result["gates"] = {}
    for unit in gpt["HOSTS"]:
        assert state["services"][unit]["phase"] == "stopped"
        gpt["verify_gate"](state, unit)
        result["gates"][unit] = "verified maintenance 503"
    for host, checkpoint in [("astraplayschess.com", "astra-chess-ops"),
                             ("arcturuschess.com", "arcturus-chess-ops"),
                             ("arcturus.astraplayschess.com", "arcturus-chess-ops")]:
        state = json.loads(Path("/var/lib", checkpoint, "maintenance.json").read_text())
        assert state["phase"] == "stopped"
        response = command(["curl", "--silent", "--show-error", "--noproxy", "*",
            "--max-time", "10", "--resolve", host + ":443:127.0.0.1",
            "--dump-header", "-", "--write-out", "\n%{http_code}", "https://" + host + "/"])
        assert response.endswith("503") and state["marker"] in response
        result["gates"][host] = "verified maintenance 503"

    network = json.loads(command(["docker", "network", "inspect", "gpt2-codex-isolated"]))[0]
    result["docker_network"] = {key: network[key] for key in ["Driver", "Internal", "EnableIPv6", "Options", "IPAM"]}
    assert network["Driver"] == "bridge" and network["Internal"] is True
    assert network["EnableIPv6"] is False
    assert network["Options"]["com.docker.network.bridge.enable_icc"] == "false"
    assert network["IPAM"]["Config"] == [{"Subnet": "172.30.97.0/24", "Gateway": "172.30.97.1"}]
    chain = command(["iptables", "-S", "GPT2-CODEX-INPUT"]).splitlines()
    assert chain == ["-N GPT2-CODEX-INPUT", "-A GPT2-CODEX-INPUT -p tcp -m tcp --dport 8902 -j ACCEPT",
                     "-A GPT2-CODEX-INPUT -j DROP"]
    inputs = command(["iptables", "-S", "INPUT"]).splitlines()
    assert inputs[1] == "-A INPUT -s 172.30.97.0/24 -j GPT2-CODEX-INPUT"
    result["firewall"] = {"scoped_chain": chain, "input_hook_first": True}
    assert not command(["docker", "ps", "-q", "--filter", "label=io.gpt2-codex=sandbox"])
    result["production_image"] = command(["docker", "image", "inspect", "--format", "{{.Id}}", "gpt2-codex-runtime:0.154.0"])
    assert result["production_image"] == "sha256:9d9274de90e73ba2e215935f0dfbd09eb5c2fe248ba7a6b3052e45969de496fb"

    files = ["/usr/local/libexec/gpt2-codex-sandbox", "/usr/local/libexec/gpt2-codex-network",
             "/usr/local/libexec/gpt2-codex-cleanup", "/usr/local/libexec/gpt2-codex-seccomp.json",
             "/etc/sudoers.d/gpt2-codex", "/home/astra/.config/astra-chess/Caddyfile",
             "/home/astra/.config/astra-chess/new-games.caddy",
             "/home/astra/.local/share/astra-chess/new-games-paused",
             "/var/lib/astra-chess-ops/maintenance.json",
             "/var/lib/arcturus-chess-ops/maintenance.json",
             "/var/lib/gpt2-maintenance-ops/maintenance.json"]
    backup = Path("/var/backups/chess-security/20261116T232418Z")
    assert json.loads((backup / "manifest.json").read_text())["complete"] is True
    result["preserved_files"] = []
    with tarfile.open(backup / "applications.tar", "r:") as archive:
        for name in files:
            path = Path(name)
            info = path.lstat()
            member = archive.getmember(name.lstrip("/"))
            assert stat.S_ISREG(info.st_mode) and member.isfile()
            assert info.st_uid == member.uid and info.st_gid == member.gid
            assert stat.S_IMODE(info.st_mode) == stat.S_IMODE(member.mode)
            current = hashlib.sha256(path.read_bytes()).hexdigest()
            assert current == hashlib.sha256(archive.extractfile(member).read()).hexdigest(), name
            result["preserved_files"].append({"path": name, "sha256": current, "matches_backup": True})
    command(["visudo", "-cf", "/etc/sudoers.d/gpt2-codex"])
    result["complete"] = True
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
