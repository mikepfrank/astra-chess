"""Replays and prospective diagrams stay in their designated output folders."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import board_scratchpad as scratchpad
import build_replay as replay
import serve_replay as server


class AssetPathTests(unittest.TestCase):
    def test_relocated_assets_leave_no_top_level_html_or_png(self):
        self.assertEqual(list(replay.ROOT.glob("*.html")), [])
        self.assertEqual(list(replay.ROOT.glob("*.png")), [])
        self.assertTrue((replay.ROOT / "templates/replay.template.html").is_file())
        self.assertTrue((replay.REPLAY_DIR / "index.html").is_file())
        self.assertTrue(server.PAGE.is_file())

    def test_build_creates_output_directory_and_honors_explicit_paths(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            archive = Path(directory) / "replays"
            explicit = Path(directory) / "custom/nested.html"
            pgn = replay.ROOT / "engine-games/wally-v02-black/game.pgn"
            with patch.object(replay, "REPLAY_DIR", archive):
                replay.build(pgn, Path("trial.html"))
                replay.build(pgn, explicit)
            self.assertTrue((archive / "trial.html").is_file())
            self.assertEqual((archive / "trial.html").read_bytes(), explicit.read_bytes())
            self.assertIn("Astra (Ultra) vs. Wally", explicit.read_text(encoding="utf-8"))
            self.assertFalse((replay.ROOT / "trial.html").exists())

    def test_server_resolves_old_bare_page_names_and_explicit_locations(self):
        self.assertEqual(server.replay_page_path("index.html"), replay.REPLAY_DIR / "index.html")
        self.assertEqual(server.replay_page_path("replays/index.html"), Path("replays/index.html"))
        self.assertEqual(server.replay_page_path(server.PAGE), server.PAGE)

    def test_preview_default_and_named_png_use_image_folder_without_changing_state(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            state = Path(directory) / "board.json"
            state.write_text(json.dumps({"board": scratchpad.START, "journal": [], "last_edits": []}))
            original = state.read_bytes()
            images = Path(directory) / "images/positions"
            commands = [([], images / "board-preview.png"),
                        (["--png", "candidate.png"], images / "candidate.png"),
                        (["--png", str(Path(directory) / "custom.png")], Path(directory) / "custom.png")]
            for flags, expected in commands:
                with self.subTest(flags=flags), patch.object(scratchpad, "POSITION_IMAGES", images), \
                     patch.object(scratchpad, "render") as render, \
                     patch("sys.argv", ["board_scratchpad.py", "preview", "e2e4", "--state", str(state), *flags]):
                    scratchpad.main()
                    self.assertEqual(render.call_args.args[1], expected.resolve())
                    self.assertEqual(render.call_args.args[0]["board"]["e4"], "P")
                    self.assertEqual(state.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
