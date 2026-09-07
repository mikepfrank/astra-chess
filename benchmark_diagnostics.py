"""Reproduce optional-feature overhead without running a chess search.

Run after other benchmark/search processes finish:
    python benchmark_diagnostics.py --output engine-benchmarks/diagnostics-micro.json
"""

import argparse
import hashlib
import json
from pathlib import Path
import statistics
import timeit

from astra_engine.diagnostics import diagnose, extra_evaluate, threat_frontier
from astra_engine.rules import Position, START_FEN
from astra_engine.search import evaluate


ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="engine-benchmarks/diagnostics-micro.json")
    parser.add_argument("--iterations", type=int, default=300)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if args.iterations < 1 or args.repeats < 1:
        parser.error("iterations and repeats must be positive")
    game = json.loads((ROOT / "engine-games/wally-2026-09-07/game.json").read_text())
    positions = [("start", Position.from_fen(START_FEN))]
    positions += [(f"game8_ply_{ply}", Position.from_fen(game["fens"][ply]))
                  for ply in (20, 38, 40, 42, 60, 78, 80)]
    functions = {
        "base_eval": evaluate,
        "mobility": lambda p: extra_evaluate(p, {"mobility": True}),
        "restricted_piece": lambda p: extra_evaluate(p, {"restricted_piece": True}),
        "king_exposure": lambda p: extra_evaluate(p, {"king_exposure": True}),
        "all_optional": lambda p: extra_evaluate(p, {"mobility": True, "restricted_piece": True,
                                                     "king_exposure": True}),
        "threat_frontier": threat_frontier,
        "diagnose": diagnose,
    }
    result = {"description": "Unprofiled function timings; optional values are added cost, not complete evaluation time.",
              "iterations": args.iterations, "repeats": args.repeats,
              "source_sha256": {name: hashlib.sha256((ROOT / "astra_engine" / name).read_bytes()).hexdigest()
                                for name in ("rules.py", "search.py", "diagnostics.py")},
              "positions": {name: pos.fen() for name, pos in positions}, "measurements": {}}
    for name, function in functions.items():
        samples = {}
        for label, pos in positions:
            samples[label] = [seconds / args.iterations * 1e6 for seconds in
                              timeit.repeat(lambda: function(pos), number=args.iterations, repeat=args.repeats)]
        medians = [statistics.median(values) for values in samples.values()]
        result["measurements"][name] = {"samples_microseconds": samples,
                                          "median_position_microseconds": statistics.median(medians),
                                          "max_position_median_microseconds": max(medians)}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({name: {key: value for key, value in data.items() if key != "samples_microseconds"}
                      for name, data in result["measurements"].items()}, indent=2))
    print(f"Saved {output}")


if __name__ == "__main__":
    main()
