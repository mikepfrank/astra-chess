"""Backup admission guards without running services, Docker, tar, or SQLite."""
import importlib.util
import json
from pathlib import Path
import stat
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("backup_host_security", Path(__file__).parents[1] / "tools/ops/backup_host_security.py")
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


class BackupGuardTests(unittest.TestCase):
    def setUp(self):
        self.units = {name: {"ActiveState": "inactive", "MainPID": "0", "UnitFileState": "disabled"}
                      for name in (*m.APPS, *m.TIMERS, *m.JOBS)}
        self.checkpoints = {path: {"phase": "stopped"} for path in m.CHECKPOINTS[:2]}
        self.checkpoints[m.CHECKPOINTS[2]] = {"services": {name: {"phase": "stopped"} for name in m.APPS[2:]}}
        self.sandboxes, self.tag, self.missing, self.unsafe = "", m.IMAGE, None, False

    def run_command(self, args, **kwargs):
        if args[0] == "systemctl":
            return "\n".join(k + "=" + v for k, v in self.units[args[2]].items())
        if args[:2] == ["docker", "ps"]:
            return self.sandboxes
        if args[:3] == ["docker", "image", "inspect"]:
            return self.tag
        raise AssertionError("Unexpected command")

    def fake_path(self, path):
        return SimpleNamespace(
            lstat=lambda: SimpleNamespace(st_mode=stat.S_IFREG | (0o644 if self.unsafe else 0o600), st_uid=0),
            read_text=lambda: json.dumps(self.checkpoints[path]),
            exists=lambda: path != self.missing)

    def check(self):
        with patch.object(m, "run", side_effect=self.run_command), patch.object(m, "Path", side_effect=self.fake_path):
            return m.preflight()

    def test_all_four_stopped_and_disabled_are_accepted(self):
        self.assertEqual(set(self.check()), set((*m.APPS, *m.TIMERS, *m.JOBS)))

    def test_any_running_app_is_refused(self):
        self.units[m.APPS[3]]["ActiveState"] = "active"
        with self.assertRaises(RuntimeError):
            self.check()

    def test_disabled_but_lingering_main_process_is_refused(self):
        self.units[m.APPS[0]]["MainPID"] = "999"
        with self.assertRaises(RuntimeError):
            self.check()

    def test_boot_enabled_app_is_refused(self):
        self.units[m.APPS[2]]["UnitFileState"] = "enabled"
        with self.assertRaises(RuntimeError):
            self.check()

    def test_running_notifier_is_refused(self):
        self.units[m.JOBS[0]]["ActiveState"] = "activating"
        with self.assertRaises(RuntimeError):
            self.check()

    def test_unfinished_chess_drain_is_refused(self):
        self.checkpoints[m.CHECKPOINTS[0]]["phase"] = "draining"
        with self.assertRaises(RuntimeError):
            self.check()

    def test_unfinished_lab_drain_is_refused(self):
        self.checkpoints[m.CHECKPOINTS[2]]["services"][m.APPS[3]]["phase"] = "gated"
        with self.assertRaises(RuntimeError):
            self.check()

    def test_loose_checkpoint_permissions_are_refused(self):
        self.unsafe = True
        with self.assertRaises(RuntimeError):
            self.check()

    def test_running_sandbox_is_refused(self):
        self.sandboxes = "container123\n"
        with self.assertRaises(RuntimeError):
            self.check()

    def test_moved_rollback_image_tag_is_refused(self):
        self.tag = "sha256:not-original"
        with self.assertRaises(RuntimeError):
            self.check()

    def test_missing_backup_source_is_refused(self):
        self.missing = "/home/gpt-2/GPT-2-tools"
        with self.assertRaises(RuntimeError):
            self.check()


if __name__ == "__main__":
    unittest.main()
