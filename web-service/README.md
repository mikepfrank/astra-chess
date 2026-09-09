# Astra Chess web service

A local alpha implementation of the planned **public beta**: people play White
or Black against a per-game Codex session using Astra/Ultra and the unchanged
from-scratch tactical engine. Human turns are untimed; games can continue over
several days. The original playing checkout and its experiment records are not
modified by this application.

## Run on Windows

Use Python 3.12 and the reviewed Codex CLI version in
[CODEX-INTEGRATION.md](docs/CODEX-INTEGRATION.md). From this directory:

```powershell
python -m venv .venv
& ./.venv/Scripts/python.exe -m pip install -r requirements.txt
& ./.venv/Scripts/python.exe run.py
```

Open **http://127.0.0.1:8788**. On this development laptop, `python` is not on
PATH; the bundled Python runtime can create the virtual environment. Once the
environment exists, the last two commands work without changing PATH.

The default player mode is **disabled**. The interface explicitly reports that
the operator must configure the model connection. It never substitutes an
engine-only player or simulated game for Astra.

To enable real play, configure `OPENAI_API_KEY` in the service process's
environment using your normal secret-management mechanism, then:

```powershell
$env:ASTRA_PLAYER = 'codex'
# Only needed if codex is not on PATH:
# $env:ASTRA_CODEX_BIN = 'C:/absolute/path/to/codex.exe'
& ./.venv/Scripts/python.exe run.py
```

No API key is bundled or written into the repository. The bridge uses a fixed
OpenAI API provider; it does not inherit the desktop's login or account profile.
Keep the service key out of browser code, URLs, source files and screenshots.
The UI's availability flag establishes configuration presence, not confirmed
model access; a rejected live request leaves the game saved with a retry status.

## Linux

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python run.py
```

The application binds to loopback by default. A service unit and reverse-proxy
example are under [deploy/](deploy/). They are preparation for the later AWS
session, not evidence of an Amazon Linux deployment. Do not use Uvicorn reload
or multiple workers for this version. An OS-held data-directory lock prevents
two schedulers from owning the same games.

## Features

- Original SVG pieces, legal move targets, keyboard/touch selection, promotion,
  board flip, captured-piece trays, SAN scoresheet and PGN download.
- Per-game public commentary, resignations, draw offers/acceptance/declines and
  claims. The server enforces chess rules, including castling, en passant,
  repetition history and automatic terminal results.
- Browser-bound guest names; optional password protection and optional recovery
  email. Password accounts can enable/edit private notes supplied to Astra in
  subsequent games. Memories are opt-in, user-managed, and never available for
  guest accounts. Automatic model-authored memory extraction is not included.
- Private records by default. After a game, the owner can generate a public
  replay link, explicitly choose whether to include the exchanged commentary,
  and revoke the link. Generating another link replaces the previous link.
  Revocation stops service access; it cannot remove copies others already saved.
- One durable Codex conversation per game. Processes exit after each completed
  action; they do not idle while waiting for the human. After 36 hours without
  a human game action, the game is marked suspended. Resume restores it without
  deleting moves, messages, clock evidence or the Codex session ID.

## Configuration

All optional environment variables are listed here; `config.py` contains limits.

| Variable | Default | Purpose |
| --- | --- | --- |
| `ASTRA_DATA_DIR` | `web-service/var` | Private SQLite database, query evidence and per-game Codex homes |
| `ASTRA_ORIGIN` | `http://127.0.0.1:8788` | Exact browser origin; HTTPS enables Secure cookies |
| `ASTRA_PLAYER` | `disabled` | Set to `codex` for the real player; `test` is reserved for injected test fixtures |
| `ASTRA_CODEX_BIN` | `codex` | Reviewed Codex executable |
| `OPENAI_API_KEY` | absent | Service operator's API key |
| `ASTRA_MAX_WORKERS` | `1` | Simultaneous active Codex actions/engine searches |
| `ASTRA_MAX_DAILY_TURNS` | `500` | UTC daily admitted model-action limit, including chat and failed attempts |
| `ASTRA_MAX_TURN_TOKENS` | `30000` | Reservation and stop threshold for one model action |
| `ASTRA_MAX_DAILY_TOKENS` | `3000000` | Daily admission allowance, including outstanding reservations |
| `ASTRA_SMTP_HOST` | absent | Enables optional email recovery when sender is also configured |
| `ASTRA_SMTP_PORT` | `587` | STARTTLS; port 465 uses implicit TLS |
| `ASTRA_SMTP_FROM` | absent | Recovery sender address |
| `ASTRA_SMTP_USER`, `ASTRA_SMTP_PASSWORD` | absent | Optional SMTP authentication |

Model and reasoning are fixed at `gpt-6-astra` / `ultra`; the service rejects
silent fallback. Limits are conservative operational starting values, **not
dollar spending guarantees**. Usage notifications arrive after model work, so
one in-flight response can exceed a token threshold. Unknown/failed usage is
charged conservatively against the reservation. Record actual API charges in
the first controlled trial before selecting an operator spending policy.

The original classical allowance is retained: 90 minutes initially, +30 seconds
per accepted Astra move and +30 minutes after its 40th move. Ordinary/critical
targets are 120/240 seconds, with a 40-second review reserve. Allocations
shrink with the earned balance; the reserve shrinks to at most one third of a
shorter turn so that a tactical query remains possible. Queue time and human time are excluded; worker
startup, deliberation, queries and recovery during active work are charged.
No future credits are spent. A worker failure preserves charged time and never
silently refunds it. Exhaustion pauses play for operator review rather than
inventing a chess timeout rule for the untimed human.

## Persistence and operations

`var/astra.sqlite3` owns users, hashed passwords, hashed cookies/reset tokens,
memory notes, game state, messages, idempotency keys, event records, resource
admission and shared snapshots. `var/games/ID/queries/` keeps requests/results,
including failed-request evidence. `var/players/ID/` keeps Codex recovery state.
These are private runtime data, ignored by Git. Do not publish this directory
as static files or commit real players' records. Source control contains only
application code, tests and authored documentation.

Back up the **entire data directory**, with the service stopped or using a
coordinated SQLite backup plus matching Codex/evidence files. Copying only the
SQLite main file while WAL writes are active is insufficient. Preserve the
engine revision with the backup. A fingerprint mismatch stops a resumed game.

The service has no automatic data deletion policy yet. Its UI warns that games
and messages are logged. Operators should protect backups and establish the
later retention/privacy policy before broad promotion.

## Validation

```powershell
& ./.venv/Scripts/python.exe -m unittest discover -s tests -v
node --check static/app.js
node --check static/pieces.js
node --check static/replay.js
```

See [VALIDATION.md](docs/VALIDATION.md) for the checks actually run and remaining
live-integration gates. The fake Codex fixtures are test infrastructure only;
they are not playing-strength evidence. See [ARCHITECTURE.md](docs/ARCHITECTURE.md)
for ownership, recovery and security boundaries.
