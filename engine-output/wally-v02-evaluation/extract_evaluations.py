"""Reproduce the original game-nine chart data with the reusable exporter."""
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from export_evaluations import extract as export_game, write_export


def extract():
    return export_game("wally-engine-v02")


if __name__ == "__main__":
    write_export("wally-engine-v02", HERE / "data.json")
