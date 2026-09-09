# Live Windows integration checkpoint

September 9, 2026. The local service at `http://127.0.0.1:8788` now uses the real
`gpt-6-astra` / `ultra` Codex player and the unchanged from-scratch chess engine.
The user's guest cookie/account was preserved when switching the preview from
disabled mode to live play. No GitHub push or Linux/AWS deployment was performed.

## Live checks that passed

- The supplied service credential authenticated at the fixed official OpenAI
  model endpoint and was saved as Windows-user DPAPI ciphertext. A separate
  launcher process successfully decrypted it. No plaintext key was written to
  an application source file, browser code, command argument or game record.
- Real Codex actions recorded independent candidates, executed actual tactical
  engine queries and submitted legal moves. Fresh and resumed conversations were
  exercised in separate private integration directories.
- `tests/live_http_check.py --live --include-commentary` passed against the actual
  running server. Its own guest played White's e4; Astra answered e5 after two
  searches, then answered a question about the engine through a resumed Codex
  process. Human resignation, anonymous replay loading with opted-in commentary,
  revocation and subsequent 404 responses passed. Its game was finished and its
  temporary replay revoked; the user's browser identity was not changed.
- The successful HTTP check recorded 65.265 seconds and 69,240 reported total
  tokens for the move action, followed by 8.859 seconds and 19,675 total tokens
  for chat. Total tokens include repeated/cached input; they are not a count of
  new reasoning tokens or a dollar estimate. Chat did not debit the chess clock.
- Browser inspection confirmed the unavailable dialog now has clear recovery
  and exit controls, preserves the guest identity, and transitions to live side
  selection after configuration. The user's White game opened successfully.

## Failures found and corrected

The pinned CLI's Astra catalog requires code-mode tool orchestration. Disabling
that feature let the model respond but hid the chess tools. The bridge now uses
the separate code-mode host with no in-process fallback, while retaining the
existing tool and environment restrictions. Thread-scoped read-only clock
requests are supported. Unknown capabilities and permission requests still fail
closed.

Windows startup now creates the process suspended, assigns a kill-on-close job,
and only then resumes it. The job bounds the app-server/runtime tree to eight
processes and 1 GiB committed memory. Tests caught and fixed the earlier race
where a runtime child could start before job assignment.

Early live actions exceeded the initial 30,000-token ceiling. A later action
also exceeded 100,000 as repeated detailed search output accumulated in context;
accepted moves and consumed time were preserved. The current 100,000-token
ceiling is accompanied by compact model-facing diagnostics, on-demand complete
query details, less duplicated snapshot history and 20,000-token automatic
context compaction. The successful HTTP check above ran with those changes.
The full engine result, warnings and game history remain durable. The engine
itself and the requested model/reasoning setting were not changed.

## Automated verification

The suite now contains **66 tests**, covered by a full 56-test run and subsequent
targeted runs of every changed area. The full run passed in 283.857 seconds;
later targeted suites passed for 19 bridge tests, 17 service tests, six engine
view tests, two model-context/evidence tests and two clock/retry tests. Nine
local setup tests include real DPAPI round trips with placeholder keys. All
unit/integration fixtures in normal unittest discovery remain free of model
API calls. JavaScript syntax and DOM references passed their checks.

The configuration-only real CLI checks verified the separate code host and
automatic-compaction settings. Simulated compaction events preserve the thread
and cumulative usage accounting. A deliberately observed live automatic-
compaction cycle, a complete long game and playing strength are not claimed by
these short integration checks.

## Continuing local tests and later deployment

Run `run.py` from the service directory to load the encrypted local setup.
Use `configure_local.py` in a normal terminal to replace the key through hidden
input. The same Windows user must launch the service; a restricted Codex sandbox
identity may be unable to decrypt that user's DPAPI file. Explicit environment
variables remain supported and take precedence.

The HTTP check is an explicit paid operation against loopback only; run it with
`--live` when needed, not as part of every unit test. Its private records and
earlier integration evidence are under ignored `var/` storage, not source control.
The normal server retains the existing single-worker and daily admission limits.
API usage notifications are not a hard dollar spending guarantee.

SMTP delivery still needs an operator-configured mail service. Linux isolation,
CPU/search-depth measurements, proxy/TLS, backups, process limits and deployment
remain the next host-specific work. No external chess engines, books, tablebases
or game-database resources were used.

## Optional historical evaluation display

The evaluation reader passed nine tests, with one additional symlink test
skipped because this Windows account lacked symlink creation privileges.
Seventeen existing HTTP/service tests also passed. Coverage includes actual
chosen-move evidence, latest qualifying query order, both colors, signed mate
distances, malformed/missing/fallback results, path confinement, ownership and
retention across a human reply. JavaScript syntax and Git whitespace checks passed.

A separate read-only browser fixture confirmed the default-off toggle,
preference persistence, signed pawn labels, mates for/against Astra, retention
after a human reply, and hidden opening/missing/checkmate states. The evaluation
panel was inspected visually. A read-only check against the active game's saved
evidence selected its rank-two Nc6 score (-0.12 pawns), excluding the later
hypothetical continuation. No new search or model call was needed for these checks.
