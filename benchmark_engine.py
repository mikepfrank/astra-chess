"""Reproducible, unprofiled comparison against our own committed baseline.

No third-party engine or position database is used. Fixtures are this trial's
recorded positions and small rule-derived positions. Run without live gameplay.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent
BASELINE = "37f3767e4a9c9634fd6901a2918ee36a1997a316"


def cases():
    game = json.loads((ROOT / "engine-games/wally-2026-09-07/game.json").read_text())
    fixtures = []
    for name, index in [("before_Ra1", 38), ("before_Rfd1", 40), ("after_c4", 42), ("final_attack", 80)]:
        fixtures.append({"name": name, "fen": game["fens"][index], "history_fens": game["fens"][:index]})
    fixtures.extend([
        {"name": "initial", "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", "history_fens": []},
        {"name": "rook_endgame", "fen": "8/6k1/7p/8/3R4/6P1/5PK1/r7 w - - 0 1", "history_fens": []},
    ])
    return fixtures


def worker(args):
    sys.path.insert(0, args.engine)
    from astra_engine.rules import Position
    from astra_engine.search import analyze

    fixture = json.loads(args.case)
    root = Position.from_fen(fixture["fen"])
    options = json.loads(args.options)
    started = time.perf_counter()
    result = analyze(root, max_depth=args.depth, time_limit=args.seconds, multipv=3,
                     history=[Position.from_fen(f).repetition_key() for f in fixture["history_fens"]], **options)
    elapsed = time.perf_counter() - started
    for line in result["candidates"]:
        board = root
        assert line["fens"][0] == board.fen()
        for i, uci in enumerate(line["uci"]):
            move = board.parse_uci(uci)
            assert board.san(move) == line["san"][i]
            board = board.play(move)
            assert board.fen() == line["fens"][i+1]
    print(json.dumps({"case": fixture["name"], "requested_depth": args.depth, "seconds": args.seconds,
                      "completed_depth": result["completed_depth"], "nodes": result["nodes"],
                      "wall_seconds": elapsed, "search_seconds": result["elapsed_seconds"],
                      "overrun_seconds": max(0, elapsed - args.seconds),
                      "options": options, "diagnostics": result.get("diagnostics"),
                      "candidates": [{k: c.get(k) for k in ("root_move", "score_cp", "uci", "ending", "claim_by_intended_move")}
                                     for c in result["candidates"]]}))


def run(args):
    output = {"baseline_commit": BASELINE, "python": sys.version, "fixed_depth": [], "fixed_time": [], "experimental": []}
    digest = hashlib.sha256()
    for name in ("rules.py", "search.py", "diagnostics.py"):
        digest.update(name.encode("ascii") + b"\0" + (ROOT / "astra_engine" / name).read_bytes())
    output["current_source_sha256"] = digest.hexdigest()

    def measure(engine, fixture, depth, seconds, options=None):
        command = [sys.executable, "-S", str(Path(__file__).resolve()), "--worker", "--engine", str(engine),
                   "--case", json.dumps(fixture), "--depth", str(depth), "--seconds", str(seconds),
                   "--options", json.dumps(options or {})]
        child = subprocess.run(command, capture_output=True, text=True, timeout=seconds+15, cwd=engine)
        if child.returncode:
            raise RuntimeError(child.stderr)
        return json.loads(child.stdout)

    def save():
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")

    with tempfile.TemporaryDirectory(prefix="astra-own-baseline-") as temporary:
        reference = Path(temporary)
        package = reference / "astra_engine"
        package.mkdir()
        for name in ("__init__.py", "rules.py", "search.py"):
            old = subprocess.run(["git", "show", f"{BASELINE}:astra_engine/{name}"], cwd=ROOT, capture_output=True, check=True)
            (package / name).write_bytes(old.stdout)
        if not args.time_only and not args.options_only:
            for fixture in cases():
                measurements = []
                for repeat in range(args.repeats):
                    pair = {}
                    # Alternate order to reduce consistent warmup/order bias.
                    for label in (["baseline", "current"] if repeat % 2 == 0 else ["current", "baseline"]):
                        pair[label] = measure(reference if label == "baseline" else ROOT, fixture, 3, 60)
                    pair["same_candidates"] = pair["baseline"]["candidates"] == pair["current"]["candidates"]
                    pair["same_nodes"] = pair["baseline"]["nodes"] == pair["current"]["nodes"]
                    if not pair["same_candidates"] or pair["baseline"]["completed_depth"] != 3 or pair["current"]["completed_depth"] != 3:
                        raise AssertionError(f"Fixed-depth equivalence failed: {fixture['name']} {pair}")
                    measurements.append(pair)
                row = {"case": fixture["name"], "measurements": measurements,
                       "median_speedup": statistics.median(m["baseline"]["wall_seconds"] for m in measurements) /
                                         statistics.median(m["current"]["wall_seconds"] for m in measurements)}
                output["fixed_depth"].append(row)
                save()
                print(f"{fixture['name']}: identical candidates; {row['median_speedup']:.2f}x speed", flush=True)
        if args.experimental or args.options_only:
            variants = {"mobility": {"evaluation": {"mobility": True}},
                        "restricted_piece": {"evaluation": {"restricted_piece": True}},
                        "king_exposure": {"evaluation": {"king_exposure": True}},
                        "all_evaluation": {"evaluation": {"mobility": True, "restricted_piece": True, "king_exposure": True}},
                        "extension": {"threat_extensions": 1},
                        "extension_2": {"threat_extensions": 2}}
            for fixture in cases():
                for name, options in {"default": {}, **variants}.items():
                    result = measure(ROOT, fixture, 12, 3, options)
                    result["variant"] = name
                    output["experimental"].append(result)
                    save()
                print(f"{fixture['name']}: experimental equal-time comparisons saved", flush=True)
        if args.fixed_time or args.time_only:
            # Includes a known tactical failure, a different attack, and an endgame.
            for fixture in [cases()[0], cases()[3], cases()[5]]:
                for seconds in (3, 15, 45):
                    pair = {"case": fixture["name"], "seconds": seconds}
                    for label, engine in (("baseline", reference), ("current", ROOT)):
                        pair[label] = measure(engine, fixture, 12, seconds)
                    output["fixed_time"].append(pair)
                    save()
                    print(f"{fixture['name']} {seconds}s: depths {pair['baseline']['completed_depth']} -> {pair['current']['completed_depth']}", flush=True)
    save()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "engine-benchmarks/v02.json")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--fixed-time", action="store_true")
    parser.add_argument("--time-only", action="store_true")
    parser.add_argument("--experimental", action="store_true")
    parser.add_argument("--options-only", action="store_true")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--engine", help=argparse.SUPPRESS)
    parser.add_argument("--case", help=argparse.SUPPRESS)
    parser.add_argument("--depth", type=int, default=3, help=argparse.SUPPRESS)
    parser.add_argument("--seconds", type=float, default=60, help=argparse.SUPPRESS)
    parser.add_argument("--options", default="{}", help=argparse.SUPPRESS)
    args = parser.parse_args()
    worker(args) if args.worker else run(args)
