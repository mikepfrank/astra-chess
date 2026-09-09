# Li replay: historical engine scores

`data.json` contains all 70 verified Astra moves from game 11, extracted only
from saved in-game searches. No new chess analysis was run for this archive.
Each row retains the actual move/FEN alignment, source path and hash, achieved
depth, and White score perspective. The hypothetical move-43 follow-up is not
substituted for the actual Rh7 score.

Rebuild from the repository root:

```text
python export_evaluations.py --game li-v02-classical --output engine-output/li-v02-evaluation/data.json
python build_replay.py --pgn engine-games/li-v02-classical/game.pgn --output replays/li-replay.html --subtitle "Engine v0.2 trial / Classical clock" --evaluations engine-output/li-v02-evaluation/data.json
```

The replay contains 140 positions and ends with 70.Kxe6, a draw by insufficient
material. The final result panel prioritizes the actual draw and preserves the
recorded +0.00 as historical evidence. Opponent frames have no new evaluation.

Validation: all 168 Python tests passed, including new draw-ending validation
and existing scored-replay checks. All four offline replay browser suites passed
with the existing Edge installation. The Li suite checked moves, score provenance,
both castlings, capture/rewind, terminal bare kings, both Draw labels, board flip,
keyboard/slider navigation, playback, PGN download, the collection link, and
390/320-pixel layouts. The pawn SVG regression suite covered all nine archives.
Desktop and mobile screenshots are in `images/replays/li-*.png` and were visually
inspected. The page was also opened and its ending checked in the embedded sidebar.
The canonical/installed archive skill copies match and passed the skill validator.

Upload `replays/li-replay.html` as the root `index.html` of a new Netlify project.
The collection entry proposes **astra-vs-li.netlify.app**; it does not assert
that this new project is deployed. Upload `replays/index.html` separately to
the existing master collection project. Existing deployment links are preserved.
