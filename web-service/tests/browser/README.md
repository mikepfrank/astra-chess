# Browser QA sources

These optional development checks exercise the current chat and replay UI.
They are not imported by the service or collected by `unittest`. Run commands
from the `web-service` directory. Python 3.12 and the application requirements,
Node.js 20 or newer, Playwright, and a browser are needed on the QA machine.
No model credentials are needed. Do not install browser tooling on the
production server merely to run the web service.

| Source | Scope |
| --- | --- |
| `fixture_server.py` | Creates a disposable account and finished game, using temporary storage under `var/browser-qa`. Binds only `127.0.0.1:8793`. Its player stub raises instead of invoking a model or tactical search. |
| `replay_variants.cjs` | Mutates only that fixture: creates both variants, downloads, shares, lists/unlists, relists an older snapshot, updates, deletes, checks legacy links, reloads, plays offline HTML, and checks chat/XSS and desktop/mobile layout. |
| `replay_async.cjs` | Uses the fixture login with intercepted synthetic archive responses to check delayed GETs, disabled tabs during mutations, retained downloads during refresh, and failed-refresh display. No archive mutation reaches the backend. |
| `emoji.cjs` | Loads freshly generated synthetic board data; all browser requests are intercepted. Checks caret/selection insertion, message limits, keyboard control, dismissal, post-game and suspended states, and desktop/mobile layout. No messages are sent. |
| `public_readonly.cjs` | Explicit-origin GET-only deployment check: unified UI, availability flag, public index, historical replay links/CSP, first-human-game chat navigation, and Li's draw. Creates no accounts, games, archives or links. |
| `support.cjs` | Portable dependency loading, fixture identity check, output paths and bounded waits. |

All generated access cookies, synthetic fixtures, databases, screenshots,
downloads and any redirected logs belong in ignored `web-service/var/browser-qa/`.
Do not copy real accounts or game records there to run these checks. Normal
fixture shutdown removes its database and access-cookie file; downloaded HTML
and screenshots remain for inspection. A crashed fixture can leave ignored
temporary files. Start a new fixture before retrying a failed run.

## Optional dependencies

The scripts load `require('playwright')` when Playwright is installed in Node's
normal module search path. Alternatively, set `ASTRA_PLAYWRIGHT_MODULE` to an
existing Playwright module directory. No developer-specific runtime path is
embedded in the sources.

The examples install Playwright 1.62.1 in an ignored tooling directory. The
default browser channel is an already installed **Google Chrome** (`chrome`).
To use Playwright's downloaded Chromium instead, set
`ASTRA_BROWSER_CHANNEL=chromium` and run the optional browser-install command
shown below. Browser OS libraries must already be available on that QA host.

### Windows PowerShell

Use the existing application virtual environment, or create it first:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm install --prefix var/browser-qa/tooling --no-save --package-lock=false playwright@1.62.1
$env:ASTRA_PLAYWRIGHT_MODULE = (Resolve-Path var/browser-qa/tooling/node_modules/playwright).Path
$env:ASTRA_BROWSER_CHANNEL = 'chrome'
```

Optional Chromium alternative:

```powershell
node var/browser-qa/tooling/node_modules/playwright/cli.js install chromium
$env:ASTRA_BROWSER_CHANNEL = 'chromium'
```

Start the fixture in a foreground terminal and leave it running:

```powershell
.\.venv\Scripts\python.exe tests/browser/fixture_server.py
```

In a second PowerShell terminal, from `web-service`, select the same browser
and module path and run the checks sequentially:

```powershell
$env:ASTRA_PLAYWRIGHT_MODULE = (Resolve-Path var/browser-qa/tooling/node_modules/playwright).Path
$env:ASTRA_BROWSER_CHANNEL = 'chrome'
node tests/browser/replay_variants.cjs
node tests/browser/replay_async.cjs
node tests/browser/emoji.cjs
node tests/browser/public_readonly.cjs --origin http://127.0.0.1:8793
```

Use `chromium` in that second terminal as well if you chose the alternative.
Stop the fixture with **Ctrl+C** when finished. Its startup reserves port 8793
before creating credentials; it will refuse to replace another listener.

### Linux shell

From `web-service`, with Python 3.12 and Node already available:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm install --prefix var/browser-qa/tooling --no-save --package-lock=false playwright@1.62.1
export ASTRA_PLAYWRIGHT_MODULE="$PWD/var/browser-qa/tooling/node_modules/playwright"
export ASTRA_BROWSER_CHANNEL=chromium
node "$ASTRA_PLAYWRIGHT_MODULE/cli.js" install chromium
.venv/bin/python tests/browser/fixture_server.py
```

In a second shell, from `web-service`:

```sh
export ASTRA_PLAYWRIGHT_MODULE="$PWD/var/browser-qa/tooling/node_modules/playwright"
export ASTRA_BROWSER_CHANNEL=chromium
node tests/browser/replay_variants.cjs
node tests/browser/replay_async.cjs
node tests/browser/emoji.cjs
node tests/browser/public_readonly.cjs --origin http://127.0.0.1:8793
```

For an already installed Google Chrome, use `ASTRA_BROWSER_CHANNEL=chrome`
and omit the Chromium-install command. Stop the fixture with **Ctrl+C**.

## Public deployment check

Only `public_readonly.cjs` accepts a configurable origin. Supply the intended
deployment explicitly, with no path, credentials, query or fragment:

```sh
node tests/browser/public_readonly.cjs --origin https://your-chess-host.example
```

It uses a fresh anonymous browser context, blocks browser requests other than
GET and requests to other origins, and follows only same-origin historical
links. Its explicit HTTP requests are GETs. The availability assertion checks
configuration presence; it does not prove a paid model turn succeeds. Historical
checks expect the repository's existing ten experiment pages and allow the
collection to grow.

The local mutating checks accept no origin override. Before using fixture
cookies they verify a fresh random fixture marker from the server against the
generated access file, refusing stale credentials or another listener. Run
them sequentially; they share one disposable game. The complete replay check
clears only that fixture's two archived variants at its start and finishes with
both variants and its legacy link deleted, while preserving the fixture game.

## Source consolidation

The current sources replace the session's ignored `var/qa` prototypes:

- `replay-library-preview.py` → `fixture_server.py`, with bounded listener,
  portable output paths and an explicit fixture identity.
- `replay-variants-smoke.cjs` → `replay_variants.cjs`. Coverage from
  `replay-legacy-relist-smoke.cjs` is incorporated using the current two-variant
  contract. The earlier `replay-library-smoke.cjs` targets the superseded
  one-version dialog and is not a supported test.
- `replay-variant-async-smoke.cjs` → `replay_async.cjs`.
- `emoji-smoke.cjs` → `emoji.cjs`; its synthetic board is rebuilt by the fixture
  server instead of copying a saved runtime JSON file.
- `live-unified-replay.cjs` and `replay-live-readonly.cjs` are consolidated in
  `public_readonly.cjs`; their fixed deployment URL and fixed chat count are
  removed.

Old helpers and their runtime outputs remain ignored as historical local
scratch. Existing tracked display/recovery tools such as
[`evaluation_ui_server.py`](../evaluation_ui_server.py),
[`postgame_ui_server.py`](../postgame_ui_server.py) and
[`guard_compaction_restart.py`](../guard_compaction_restart.py) are separate
tools and have not been duplicated here.
