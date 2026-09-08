# Early trial records

The saved records from the games played before the search engine was introduced
are grouped here by opponent and date. Original PGN and JSON filenames and
contents are retained; each trial's notes live alongside its records.

| Game | Record | Trial notes |
| --- | --- | --- |
| 2: Sven rematch | [PGN](sven-rematch-2026-09-05/codex-vs-sven-rematch-2026-09-05.pgn) | |
| 3: Nelson | [PGN](nelson-2026-09-05/codex-vs-nelson-2026-09-05.pgn) | |
| 4: Nelson rematch | [PGN](nelson-rematch-2026-09-05/codex-vs-nelson-rematch-2026-09-05.pgn) | [Visualization trial](nelson-rematch-2026-09-05/nelson-visualization-trial.md) |
| 5: Wendy | [PGN](wendy-2026-09-05/codex-vs-wendy-2026-09-05.pgn) | [Visualization trial](wendy-2026-09-05/wendy-visualization-trial.md) |
| 6: Wally | [PGN](wally-2026-09-05/codex-vs-wally-2026-09-05.pgn) | [Visualization trial](wally-2026-09-05/wally-visualization-trial.md) |
| 7: Wally rematch | [PGN](wally-rematch-2026-09-06/codex-vs-wally-rematch-2026-09-06.pgn) | [Visualization trial](wally-rematch-2026-09-06/wally-rematch-visualization-trial.md) |

Game numbers follow the original session. There is no saved PGN for game 1.
The [position images](../images/positions/) and [replay pages](../replays/) remain
in their shared directories. Later engine-assisted trials use
[engine-games/](../engine-games/).

For new diagram experiments, `board_scratchpad.py init` uses the ignored
`scratch/board.json`; bare `--state` filenames also go under `scratch/`. Use an
explicit directory for records that should be retained, and commit substantive
game evidence at the completion checkpoint. Reading an old journal requires its
explicit path, for example:

```text
python board_scratchpad.py show --state early-games/nelson-rematch-2026-09-05/nelson-rematch-board.json
```

Run tool commands from the repository root. Paths in each trial's Markdown notes
resolve relative to that note. The Wally rematch validation JSON's `pgn` and
`journal` filenames refer to its sibling files.
