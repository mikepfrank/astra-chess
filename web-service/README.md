# Astra Chess web service

A **public beta** chess service: people play White
or Black against a per-game Codex session using Astra/Ultra and the unchanged
from-scratch tactical engine. Human turns are untimed; games can continue over
several days. The original playing checkout and its experiment records are not
modified by this application.

**Hosting your own instance? Start with the [deployment walkthrough](DEPLOYMENT.md).**
It covers the tested path from local Windows development to Linux, including
runtime installation, credentials, private preview, DNS, HTTPS and operations.

The durable player workflow lives in [prompts/player.md](prompts/player.md).
Its finishing guidance is to seek a short, verified finish early when
overwhelmingly ahead, collect material only when it helps secure that finish,
and agree on instructional detours with the opponent.

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

Before setup, the default player mode is **disabled**. The interface explains
availability inside the side-selector dialog and lets the player return to the
board or saved games. It never substitutes an engine-only player or simulated
game for Astra.

For local Windows testing, configure the key once through a hidden terminal
prompt, then launch normally:

```powershell
& ./.venv/Scripts/python.exe configure_local.py --codex-bin 'C:/path/to/codex.exe'
& ./.venv/Scripts/python.exe run.py
```

The setup helper validates access to the exact Astra model before saving. It
stores a Windows DPAPI encrypted credential in `var/secrets/openai-key.dpapi`
and nonsecret launcher settings in `var/local-config.json`, both ignored by Git.
The same Windows user can restart the service without re-entering the key.
Explicit environment settings take precedence. This local encrypted file is
not a portable Linux credential; use the environment on the deployment host.
An optional positive integer `max_daily_tokens` in `var/local-config.json`
sets this laptop's daily allowance across restarts. It maps to
`ASTRA_MAX_DAILY_TOKENS`; an explicit environment value still takes precedence.
The current local testing allowance is 100,000,000 tokens per day. The shared
configuration default remains 20,000,000 for a separately configured deployment.

The live Lightsail host also uses a 100,000,000-token daily allowance as of
September 10, 2026. See the [dated host overrides](docs/LIGHTSAIL-DEPLOYMENT.md#operator-policy-changes)
for its applied settings and verification record.

Alternatively, configure `OPENAI_API_KEY` in the service process's
environment using your normal secret-management mechanism, then:

```powershell
$env:ASTRA_PLAYER = 'codex'
# Only needed if codex is not on PATH:
# $env:ASTRA_CODEX_BIN = 'C:/absolute/path/to/codex.exe'
& ./.venv/Scripts/python.exe run.py
```

No plaintext API key is bundled or tracked in the repository. The bridge uses a fixed
OpenAI API provider; it does not inherit the desktop's login or account profile.
Keep the service key out of browser code, URLs, source files and screenshots.
The UI's availability flag establishes configuration presence. Setup verifies
model access at that time; later authentication or service failures still leave
the game saved with a retry status.

## Linux

Follow the [deployment walkthrough](DEPLOYMENT.md) for the complete installation
sequence. The short commands below only launch an application environment.

The [Lightsail deployment checkpoint](docs/LIGHTSAIL-DEPLOYMENT.md) records
the installed private runtime, sandbox checks, pending validation and operator
commands. The [dependency inventory](docs/LIGHTSAIL-DEPENDENCIES.md) preserves
the earlier pre-installation review.

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python run.py
```

The application binds to loopback by default. A service unit and reverse-proxy
example are under [deploy/](deploy/); see the deployment checkpoint for what has
actually been installed and validated on Amazon Linux. Do not use Uvicorn
reload or multiple workers for this version. An OS-held data-directory lock
prevents two schedulers from owning the same games.

## Features

- Original SVG pieces, legal move targets, keyboard/touch selection, promotion,
  board flip, captured-piece trays, SAN scoresheet and PGN download.
- Optional **Show Astra's evaluation** toggle above the board, remembered in
  this browser. The label above the board shows saved tactical evidence for
  Astra's last chosen move, in pawns with positive values favoring Astra, or a
  mate count. A qualifying forced mate proof takes precedence over an ordinary
  numeric score and is labeled **mate proof**. Its displayed depth is the
  completed adversarial proof depth, not the length of a representative line;
  cooperative witnesses and unknown results do not qualify as forced proofs.
  The display stays through the human reply until Astra moves again. All mate
  counts start after Astra's chosen move; mates against Astra are identified.
  No label appears before Astra has moved, at checkmate, or when the latest
  move has no qualifying recorded score. This display runs no new analysis.
- Per-game public commentary, resignations, draw offers/acceptance/declines and
  claims. The server enforces chess rules, including castling, en passant,
  repetition history and automatic terminal results.
- Conversation stays available after the game ends, in the same per-game
  Codex session. Astra can discuss the moves and inspect saved search evidence;
  the final board, result and chess clock stay fixed. Interrupted replies can
  be retried. Each post-game response has the ordinary response time allocation
  and existing token/resource limits, without using any chess-clock time.
- An **Emoji** button below the chat box opens a small keyboard-accessible
  palette. Choosing an emoji inserts it at the cursor (or replaces selected
  text), respects the message length limit and leaves sending up to the player.
- Browser-bound guest names; optional password protection and optional recovery
  email. Password accounts can enable/edit private notes supplied to Astra in
  subsequent games. Memories are opt-in, user-managed, and never available for
  guest accounts. Automatic model-authored memory extraction is not included.
- Private records by default. **Save/share replay** on any finished game
  constructs a standalone interactive HTML archive with chat included only when
  selected. Download it, share it, or do both. Sharing creates an unlisted link
  unless **Also publish to public game list** is checked. Remove a listing
  while retaining the link, or disable the link entirely; the private download
  remains available. Earlier share links keep working and can be managed in
  the same dialog. Revocation cannot remove copies others already saved.
- Replay chat follows the selected move; the final frame includes post-game
  discussion captured at generation time. Later messages stay private unless
  included in a newly generated version. Rebuilding a private replay does not
  silently replace a shared version. The [replay workflow](docs/REPLAY-WORKFLOW.md)
  covers the preserved template, recorded evaluations and privacy choices.
- **Public games** at `/games/` links to the earlier ten experiment replays at
  `/experiments/`, all hosted on this domain. Earlier Netlify copies remain
  available at their original addresses.
- One durable Codex conversation per game. Processes exit after each completed
  action; they do not idle while waiting for the human. After 36 hours without
  a human game action, an unfinished game is marked suspended. Resume restores it without
  deleting moves, messages, clock evidence or the Codex session ID.
- During automatic context compaction, the board shows **COMPACTING** and
  freezes Astra's chess clock. The remaining turn allocation resumes when
  compaction finishes; interrupted compactions retain auditable clock evidence.
- While the tactical engine runs a query, Astra's status reads **CALCULATING**,
  then returns to **THINKING** for review and deliberation. Calculation counts
  toward the same chess clock and turn allocation as deliberation.

## Offline game replays

The [replay collection](replays/README.md) contains standalone HTML archives with
animated moves, historical evaluations and a conversation sidebar synchronized
to the selected position. The HTML works offline and can be shared as one file.
Building it uses the existing repository replay builder and the rules-and-notation
dependency included in `requirements.txt`; it runs no chess search or model request.

From this directory:

```powershell
& ./.venv/Scripts/python.exe -m pip install -r requirements-replay.txt
& ./.venv/Scripts/python.exe export_replay.py --game GAME_ID --data-dir var --record replays/game.json --output replays/game.html --pgn replays/game.pgn
```

The exporter reads a consistent, read-only snapshot of a finished game. It
validates each recorded move, final result and message position. The saved JSON
contains display metadata, moves, public chat and historical evaluations with
source hashes; credentials, account details, private decisions and Codex
transcripts are excluded. Messages retain their recorded order and text,
including the post-game discussion captured at export time.

Rebuild from that JSON without accessing the service database or query files:

```powershell
& ./.venv/Scripts/python.exe export_replay.py --from-record replays/game.json --output replays/game.html
```

Add `--omit-commentary` to exclude chat from both the HTML and JSON. Use
`--record-only` to save the validated JSON without building HTML. CLI exporting
does not publish a page or change the service's optional public replay links.

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
| `ASTRA_MAX_TURN_TOKENS` | `3000000` | Reservation and stop threshold for one model action, including input/context tokens |
| `ASTRA_MAX_DAILY_TOKENS` | `20000000` | Daily admission allowance, including outstanding reservations |
| `ASTRA_SMTP_HOST` | absent | Enables optional email recovery when sender is also configured |
| `ASTRA_SMTP_PORT` | `587` | STARTTLS; port 465 uses implicit TLS |
| `ASTRA_SMTP_FROM` | absent | Recovery sender address |
| `ASTRA_SMTP_USER`, `ASTRA_SMTP_PASSWORD` | absent | Optional SMTP authentication |

The player uses a 400,000-token context window (380,000 usable) and requests
automatic compaction at 250,000 total-context tokens. Both values are enforced
when starting or resuming a game. The threshold leaves a nominal 22,000-token
margin below Astra's 272,000-input-token pricing boundary, checked on
September 10, 2026. It is a soft trigger: request growth and compaction can still
cross that boundary. See [Astra pricing](https://developers.openai.com/api/docs/models/gpt-6-astra)
and the [compaction policy](docs/CODEX-INTEGRATION.md).

These context settings are separate from cumulative action and daily token
allowances. The 3,000,000 action allowance leaves room for several model calls
with this larger context, since each call counts repeated input as well as
generated output. Dated validation and the live host's policy overrides are in
the [deployment checkpoint](docs/LIGHTSAIL-DEPLOYMENT.md#operator-policy-changes).

Model and reasoning are fixed at `gpt-6-astra` / `ultra`; the service rejects
silent fallback. The operator chose generous local-testing limits, **not
dollar spending guarantees**. Usage notifications arrive after model work, so
one in-flight response can exceed a token threshold. Unknown/failed usage is
charged conservatively against the reservation. Record actual API charges in
the first controlled trial before selecting an operator spending policy.
Admission requires room for the full per-response reservation, so a new response
can be denied before the daily counter reaches its ceiling. Such denials do not
start a model process or debit the chess clock; the UI identifies the daily
resource allowance instead of reporting an interrupted turn.

The original classical allowance is retained: 90 minutes initially, +30 seconds
per accepted Astra move and +30 minutes after its 40th move. Ordinary/critical
targets are 120/240 seconds, with a 40-second review reserve. Allocations
shrink with the earned balance; the reserve shrinks to at most one third of a
shorter turn so that a tactical query remains possible. Queue time and human time are excluded; worker
startup, deliberation and queries during active work are charged. Codex-reported
context compaction is excluded from the chess clock and the ordinary/critical
turn allocation. The independent process timeout and API token accounting
remain in force, including during compaction.
No future credits are spent. Retrying a harness-interrupted own turn restores
the recorded thinking time of its failed attempts, once, with an audit record.
Accepted moves, completed turns and actual API usage keep their accounting.
Exhaustion pauses play for operator review rather than
inventing a chess timeout rule for the untimed human.

## Persistence and operations

`var/astra.sqlite3` owns users, hashed passwords, hashed cookies/reset tokens,
memory notes, game state, messages, idempotency keys, event records, resource
admission and shared snapshots. `var/games/ID/queries/` keeps requests/results,
including failed-request evidence. `var/players/ID/` keeps Codex recovery state.
These are private runtime data, ignored by Git. Do not publish this directory
as static files or commit real players' records without their authorization.
Source control contains application code, tests, authored documentation and
explicitly requested archives in `replays/`.

On this Windows laptop, optional `var/secrets/` also contains the DPAPI encrypted
operator key. It is separate from per-game Codex homes and query subprocesses.

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

[Manual QA helpers](tests/MANUAL-QA.md) preserve the isolated evaluation/status
and post-game chat fixtures, plus the coordinated development restart check.

An explicit paid integration check is available separately from the test suite:

```powershell
& ./.venv/Scripts/python.exe tests/live_codex_check.py --live --codex-bin 'C:/path/to/codex.exe' --data-dir var/operator-check --turns 2
```

It uses the production supervisor, real tactical queries and a deterministic
test-opponent reply, with separate private records. It checks a fresh action and
Codex conversation resumption; it is not a playing-strength benchmark.
