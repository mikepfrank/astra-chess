"""The new-game preset awards only verified own moves, for either player color."""
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from astra_engine import clock
import play_engine_game as journal


class ClassicalJournalTests(unittest.TestCase):
    def test_preset_and_increment_follow_verified_player_color(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            instant = [datetime(2026, 9, 8, 12, tzinfo=timezone.utc), 1000.0]
            def advance(seconds):
                instant[0] += timedelta(seconds=seconds)
                instant[1] += seconds
            with patch.object(journal, "ROOT", Path(directory)), \
                 patch.object(clock, "_sample", lambda: tuple(instant)), \
                 patch.object(journal, "now", lambda: instant[0].isoformat()):
                for side in ("white", "black"):
                    slug = "classical-" + side
                    def call(command, *args):
                        journal.main([command, "--game", slug, *args])
                    call("init", "--round", "11", "--side", side, "--time-control", "classical")
                    ledger = Path(directory) / "engine-games" / slug / "clock.jsonl"
                    state = clock.clock_status(ledger)
                    self.assertEqual(state["original_total_seconds"], 5400)
                    self.assertEqual(state["increment_seconds"], 30)
                    self.assertEqual(state["stage_moves"], 40)
                    self.assertEqual(state["stage_seconds"], 1800)
                    self.assertEqual(state["ordinary_seconds"], 120)
                    self.assertEqual(state["critical_seconds"], 240)
                    self.assertEqual(state["completed_own_moves"], 0)
                    advance(20)  # Setup/opponent waiting must not earn or consume own time.
                    move = "e2e4" if side == "white" else "e7e5"
                    call("turn", "--initial", move, *([] if side == "white" else ["--opponent", "e4"]))
                    self.assertEqual(clock.clock_status(ledger)["allocation_seconds"], 120)
                    advance(10)
                    call("choose", "--move", move)
                    call("submit")
                    self.assertEqual(clock.clock_status(ledger)["earned_increment_seconds"], 0)
                    advance(3)
                    call("verify")
                    state = clock.clock_status(ledger)
                    self.assertEqual(state["game_seconds_used"], 10)
                    self.assertEqual(state["earned_increment_seconds"], 30)
                    self.assertEqual(state["game_remaining_seconds"], 5420)
                    self.assertEqual(state["completed_own_moves"], 1)
                    original = ledger.read_bytes()
                    with self.assertRaises(ValueError):
                        call("verify")
                    self.assertEqual(ledger.read_bytes(), original)

    def test_classical_rejects_non_cumulative_clock(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(journal, "ROOT", Path(directory)):
            with self.assertRaisesRegex(ValueError, "requires --clock-mode game"):
                journal.main(["init", "--game", "invalid", "--round", "11",
                              "--time-control", "classical", "--clock-mode", "move"])
            self.assertFalse((Path(directory) / "engine-games/invalid").exists())


if __name__ == "__main__":
    unittest.main()
