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
accepted moves and consumed time were preserved. The initial 100,000-token
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
evidence selected its recorded chosen-candidate score, excluding a later
hypothetical continuation. No new search or model call was needed for these checks.

## Retry interruptions and clock restoration

Further local play exposed a compaction loop under the 20,000-token threshold.
A resumed request already used roughly 16,500 tokens. One failed retry performed
three compactions, each consuming about 13,000–20,000 total tokens; generated
output for that retry was only about 3,100 tokens. The cumulative usage accounting
was accurate. Repeating full board snapshots in user messages also made them
persist through compaction, causing unnecessary growth across game turns.

At the operator's request for generous local testing limits, the revised bridge
initially used a 100,000-token total-context compaction threshold, a bounded 1,000,000-token
action allowance and a 20,000,000-token daily limit.
New responses carry small event markers and retrieve fresh state, account-gated
memory and attempt requirements through chess_status. Existing thread history
is preserved. Tool responses report remaining tokens, and the player instructions
explain fresh candidate/query requirements when retrying. API output limits and
Astra/Ultra are unchanged.

All 22 bridge/config tests passed, and the actual pinned CLI accepted the revised
strict configuration in a no-key check. Seventeen service regression tests also
passed after the clock changes. These checks did not call a model; a successful
live retry under the revised policy remains to be observed.

At the user's request, Retry now restores corroborated clock charges from failed
attempts on the current unfinished Astra turn, once, within the action's SQLite
transaction. Accepted moves and prior completed turns remain charged, and API
usage is never refunded. Explicit operator clock settings establish a new
baseline so older failed intervals cannot be refunded on top of that setting.

Ten targeted clock/refund tests and two existing clock-allocation/retry tests
passed. A read-only copy of the live records also confirmed that an explicitly
set clock baseline would survive the next retry without another historical
refund. Clock recovery, attempt flags, fresh board/messages and gated memory
were exercised through the actual supervisor handler with local test players.

The service was restarted with no active or queued responses. The existing
browser game retained its identity, board and explicitly requested clock
baseline. The live evaluation toggle showed the score selected from saved
evidence and was returned to its default off state. Retry remained available;
the user was told the revised service was ready for the next live attempt.

## Larger context experiment

The operator subsequently requested compaction at 300,000 tokens. The default
272,000-token Astra context would clamp that threshold, so this change also
sets model_context_window to 400,000. The exact pinned CLI's bundled catalog
advertises a maximum context of 872,000; its model resolution accepts 400,000,
providing 380,000 usable tokens and a 360,000 compaction ceiling. A 300,000
threshold fits below both. The action allowance increases to 3,000,000 cumulative
tokens so several model calls with 250,000–300,000 input tokens can finish a
response. The 20,000,000-token daily allowance and Astra/Ultra are unchanged.

All 22 bridge tests passed with the context override and compaction checks;
the affected default-budget test passed again after the action allowance change.
The pinned CLI accepted the larger window and threshold in a no-key strict
configuration check. The service restarted while no response was active or
queued, and its HTTP availability check passed.

These are configuration and compatibility checks. Handling a live context over
300,000 tokens and any improvement in playing quality remain to be observed
during longer games.

## Compaction status and clock pauses

The pinned CLI's context-compaction item notifications now drive a private host
callback. The board displays COMPACTING for Astra in either orientation, and a
paused own-turn clock displays PAUSED. Human-turn conversation compaction does
not claim an own-clock pause. The normal status returns after completion.

The supervisor persists compaction intervals and excludes them from both the
chess clock and its ordinary/critical turn allocation. Interrupted pauses close
with explicit evidence on settlement or recovery. Failed-attempt refunds use
only charged thinking time, preventing a second credit for excluded compaction.
Token accounting and the separate emergency process timeout remain active.

All 27 bridge tests passed, including simulated start/end notifications,
duplicates, ordering, private summary handling, cancellation and failed
compactions. The 17 service, 10 retry-refund and two allocation/retry regression
tests also passed. JavaScript syntax passed. A separate read-only browser
fixture confirmed the new status, frozen clock and pause caption, restoration
of THINKING, both colors and a flipped board. The optional evaluation remained
visible through compaction. The fixture used no live records or model calls.

Ten additional deterministic clock tests passed in 2.614 seconds. They cover
multiple completed pauses followed by an interrupted pause, a frozen monitor
beyond the original turn deadline, critical and reduced-time allocations,
cancellation, duplicate notifications, human-turn conversation and post-move
compaction. Recovery and Retry credit only actual charged thinking time.

The service was restarted after a read-only guard confirmed no active or queued
responses. A before/after digest verified preservation of game identity, sides,
board, moves, messages, result, Codex thread, move credits and used clock time.
The restarted HTTP service reported Astra/Ultra available. A page reload loads
the new UI; the server continues active play independently of browser reloads.

These checks simulate compaction notifications; an observed live compaction
using the new display and accounting remains to be confirmed during play.

## Tactical calculation status

The host marks each tactical-query wait as CALCULATING, then restores THINKING
when the result returns. Calculation uses the existing chess clock and turn
allocation without pause. Query failure/cancellation clears the transient
status; recovery also recognizes an interrupted calculation during conversation.

Six new deterministic status/clock tests passed, alongside all 17 service,
10 compaction-clock and two allocation/retry tests. JavaScript syntax and a
separate browser fixture confirmed CALCULATING for both colors and board
orientations, with the clock unpaused and the compact evaluation still visible.
These checks used no model calls or live game actions.

The service restarted while no response was active or queued. The player
continued chatting and playing immediately afterward; a digest reconstructed
from the pre-restart records verified that those earlier moves, messages,
conversation identity and clock balance were preserved.

## Immediate retries blocked by daily admission

The first longer game reached 17,128,936 recorded tokens. Reserving the next
3,000,000-token action exceeded the 20,000,000 daily allowance, so admission
failed before a player process or clock interval started. A generic supervisor
error had misleadingly called this an interrupted turn on every Retry.

Daily admission now raises a dedicated exception with a fixed safe public
explanation and `daily_resource_limit` code. It also suppresses queued automatic
reruns of that denial. Other exceptions retain their sanitized generic message.
No denied reservation debits time or changes the usage ledger.

The operator's generous local-testing policy is now persisted as
`max_daily_tokens: 100000000` in the ignored Windows launcher settings. Explicit
environment values still take precedence, and the shared configuration default
remains 20,000,000. Reconfiguring credentials preserves the local allowance.

Five admission tests, 14 local-setup tests and 17 existing service tests passed.
A temporary SQLite backup of the real ledger also admitted the next 3,000,000
reservation under the effective local setting; the private test copy was
removed afterward. These checks started no model turn or live game action.
The idle service restarted successfully with the local override, and its HTTP
availability check passed. A before/after digest confirmed that the saved games,
conversation IDs, move credits and clock balances were unchanged.
