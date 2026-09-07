import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from astra_chess import attach_diagnostics, prepare
from astra_engine.rules import Position, START_FEN
from astra_engine.search import analyze, probe


class OptionalInterfaceTests(unittest.TestCase):
    def test_strict_optional_fields_and_larger_limits(self):
        prepare({"depth": 32, "seconds": 180, "diagnostics": True,
                 "evaluation": {"mobility": True}, "threat_extensions": 2})
        for extra in [{"diagnostics": 1}, {"evaluation": {"mobillity": True}},
                      {"evaluation": {"mobility": 1}}, {"threat_extensions": True},
                      {"threat_extensions": 3}, {"proof_only": True},
                      {"mode": "probe", "goal": {"type": "check"}, "evaluation": {}},
                      {"mode": "probe", "goal": {"type": "check"}, "proof_only": "yes"}]:
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                prepare(extra)

    def test_diagnostic_coverage_and_deadline(self):
        answer = analyze(Position.from_fen(START_FEN), max_depth=1, time_limit=1)
        attach_diagnostics(answer, time.monotonic() + 1)
        self.assertTrue(answer["diagnostic_coverage"]["complete"])
        self.assertEqual(answer["position_diagnostics"]["fen"], START_FEN)
        for line in answer["candidates"]:
            self.assertEqual(len(line["fens"]), len(line["position_diagnostics"]))
            for fen, inspection in zip(line["fens"], line["position_diagnostics"]):
                self.assertEqual(inspection["fen"], fen)
                self.assertEqual(inspection["side"], "white")
        attach_diagnostics(answer, time.monotonic() - 1)
        self.assertFalse(answer["diagnostic_coverage"]["complete"])
        self.assertIsNone(answer["position_diagnostics"])
        self.assertGreater(answer["diagnostic_coverage"]["positions_skipped"], 0)

    def test_probe_diagnostics_do_not_require_analysis_turn_field(self):
        root = Position.from_fen("7k/5K2/6Q1/8/8/8/8/8 w - - 0 1")
        answer = probe(root, {"type": "checkmate"}, max_depth=1, time_limit=1, proof_only=True)
        attach_diagnostics(answer, time.monotonic() + 1)
        self.assertEqual(answer["position_diagnostics"]["side"], "white")
        self.assertTrue(answer["diagnostic_coverage"]["complete"])

    def test_game_clock_cli_charges_full_query_and_logs_invalid_attempt(self):
        from astra_engine.clock import create_game_clock, observe_turn, clock_status
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            clock = folder / "clock.jsonl"
            request, output, html = (folder / name for name in ("query.json", "result.json", "report.html"))
            create_game_clock(clock)
            observe_turn(clock, 0)
            request.write_text(json.dumps({"depth": 1, "seconds": 0.5, "diagnostics": True,
                                          "evaluation": {"mobility": True}}))
            command = [sys.executable, "-S", str(ROOT / "astra_chess.py"), "query", "--request", str(request),
                       "--output", str(output), "--html", str(html), "--game-clock", str(clock)]
            child = subprocess.run(command, capture_output=True, text=True, cwd=ROOT, timeout=10)
            self.assertEqual(child.returncode, 0, child.stderr)
            answer = json.loads(output.read_text())
            self.assertEqual(answer["engine"]["version"], "0.2")
            self.assertTrue(answer["diagnostic_coverage"]["complete"])
            self.assertTrue(html.exists())
            events = [json.loads(line) for line in clock.read_text().splitlines()]
            completed = [e for e in events if e["kind"] == "query_completed"][-1]
            self.assertGreaterEqual(completed["data"]["elapsed_seconds"], answer["elapsed_seconds"])
            self.assertEqual(clock_status(clock)["calls"], 1)
            original_ledger = clock.read_bytes()
            for option in ("--output", "--html"):
                unsafe = command.copy()
                unsafe[unsafe.index(option)+1] = str(clock)
                child = subprocess.run(unsafe, capture_output=True, text=True, cwd=ROOT, timeout=10)
                self.assertEqual(child.returncode, 2, child.stderr)
                self.assertIn("clock path", child.stderr)
                self.assertEqual(clock.read_bytes(), original_ledger)
            request.write_text('{"depht": 3}')
            child = subprocess.run(command, capture_output=True, text=True, cwd=ROOT, timeout=10)
            self.assertEqual(child.returncode, 2, child.stderr)
            self.assertIn("Unknown query fields", child.stderr)
            events = [json.loads(line) for line in clock.read_text().splitlines()]
            self.assertEqual(events[-1]["kind"], "query_rejected")
            self.assertEqual(clock_status(clock)["active_ply"], 0)
            self.assertFalse(clock.with_name(clock.name + ".lock").exists())


if __name__ == "__main__":
    unittest.main()
