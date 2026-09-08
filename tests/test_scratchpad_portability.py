"""ASCII board inspection remains usable without the optional PNG dependency."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ScratchpadPortabilityTests(unittest.TestCase):
    def test_ascii_without_site_packages_and_actionable_png_error(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "board.json"
            command = [sys.executable, "-S", str(ROOT / "board_scratchpad.py")]
            initial = subprocess.run(command + ["init", "--state", str(state)],
                                     capture_output=True, text=True)
            self.assertEqual(initial.returncode, 0, initial.stderr)
            self.assertIn("8  r n b q k b n r", initial.stdout)
            self.assertEqual(len(json.loads(state.read_text())["board"]), 32)
            shown = subprocess.run(command + ["show", "--state", str(state)],
                                   capture_output=True, text=True)
            self.assertEqual(shown.returncode, 0, shown.stderr)
            self.assertIn("Uppercase = White", shown.stdout)
            png = Path(directory) / "board.png"
            missing = subprocess.run(command + ["show", "--state", str(state), "--png", str(png)],
                                     capture_output=True, text=True)
            self.assertEqual(missing.returncode, 2)
            self.assertIn("PNG rendering requires Pillow", missing.stderr)
            self.assertNotIn("Traceback", missing.stderr)
            self.assertFalse(png.exists())


if __name__ == "__main__":
    unittest.main()
