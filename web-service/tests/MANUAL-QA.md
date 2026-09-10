# Manual development checks

These helpers were used while developing the first hosted human game. Their
source is tracked here; generated data, local credentials and caches remain
under ignored runtime directories. Run commands from `web-service`.

## Evaluation and worker-status display

```powershell
./.venv/Scripts/python.exe tests/evaluation_ui_server.py
```

Serves synthetic, read-only display fixtures on `http://127.0.0.1:8790/`.
Select a fixture using `?game=NAME`: `initial`, `missing`, `human-reply`,
`mate`, `losing-mate`, `mate-proof`, `checkmate`, or a worker status such as
`thinking-white`, `calculating-black`, or `compacting-white`. The suffix gives
Astra's color. These fixtures do not start a model or access a live database.
Their scores and clocks are UI test values, not chess-analysis evidence.

## Post-game conversation

```powershell
./.venv/Scripts/python.exe tests/postgame_ui_server.py
```

Serves the application on `http://localhost:8791/` using temporary data and a
fixed test responder. Create a guest game, resign, then send a message to check
the completed-game chat controls and response. The temporary database is removed
on normal exit. No model or engine is called.

## Coordinated development restart

```powershell
./.venv/Scripts/python.exe tests/guard_compaction_restart.py
# After a separately coordinated restart:
./.venv/Scripts/python.exe tests/guard_compaction_restart.py --verify
```

The helper reads the local `var/astra.sqlite3` database in read-only mode. If no
response is queued or active, the first command saves a digest of selected game
state fields to `var/qa/restart-checkpoint.json`; `--verify` compares them after
the restart. It prints counts and comparison results, not conversations or
credentials. Exit code 2 means work is active; code 3 means the digest changed.

This is a development check, not a server lock: a player can submit a new action
immediately after it returns. Coordinate exclusive access before restarting.
The helper does not stop or restart any process. It checks the recorded board,
moves, messages, game status, conversation ID and selected clock fields; it is
not a full database backup or a comparison of every stored field.
