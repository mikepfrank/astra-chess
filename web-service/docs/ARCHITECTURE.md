# Application design and boundaries

## Ownership

The browser talks only to FastAPI. It submits a move intent plus the last seen
state version and a unique request ID. The server authenticates the cookie,
checks Origin and CSRF, validates ownership and legal chess actions, and commits
one authoritative SQLite transaction. Duplicate requests do not apply or schedule
again; stale versions return conflict. The model cannot write the database or
change accepted history.

The worker supervisor schedules at most one action per game and a configurable
number globally. A per-game Codex home preserves conversation state, while the
CLI process exists only during work. A fresh snapshot accompanies every resumed
action. The server records the thread ID before starting model work, so loss of
the final RPC response does not lose the recovery handle.

Codex has only narrow chess tools. The supervisor supplies actual FEN/history,
allocates engine-query time, writes query evidence to server-chosen paths, and
submits accepted moves itself. An engine query runs in a separate Python process
with a sanitized environment and hard wall timeout. It imports the existing
engine unchanged. Caller-provided paths, arbitrary code, network destinations,
FEN overrides or tool names are not accepted.

The deliberative loop is preserved in `prompts/player.md`: independent candidate
and concern, ordinary query, prospective-board/counterplay review, focused
questions when useful, then a considered choice. A move requires recorded
candidate evidence and a non-fallback current-position search. The model still
chooses its move; it is not required to take the highest-scored candidate.

The optional board evaluation reads the latest qualifying saved search for the
last accepted Astra move. It matches the actual pre-move and post-move FEN,
chosen UCI/SAN, root side and exact completed search depth. Hypothetical
continuations, fallback moves and missing scores cannot supply this label.
Only the score, mate attribution and chosen-move metadata enter the owner-facing
snapshot; private query paths and analysis remain private. Positive scores
favor Astra for either color. The label describes its last move and persists
through a human reply, as requested; it does not reevaluate the current board.
Mate distances count from before that Astra move. Existing games use their
original evidence without another search or a database migration.

## Recovery and time

Games persist across visits. The 36-hour threshold is based on human game actions,
not polling traffic. Suspension is a state marker; a CLI has already exited
after its last action. Resume uses the same board, messages and Codex thread.
Queued work spends no thinking time. Active work has a persisted start/deadline.
Validated Codex context-compaction events persist a pause interval, display
COMPACTING, and freeze both the chess clock and the remaining turn allocation.
Completion resumes them; duplicate notifications cannot award extra time.
On a service crash, uncertain thinking time is bounded by the saved allocation,
excluding completed pauses and time after an unfinished compaction began.
Token reservations left by a crash are charged,
not refunded. A stopped action receives a visible retry state. A player retry
restores recorded clock charges for failed attempts on that same unfinished
own turn, with transactional deduplication and a durable refund record. Accepted
moves and prior completed turns are excluded. This clock adjustment does not
refund tokens or change resource limits.

An accepted Astra move stops its active clock before increment/stage credit.
Actual started/ended timestamps, charge and pre-credit balance are retained in
`clock_events`, with one settlement per attempt and its excluded pause duration.
`compaction_events` retain completed and interrupted intervals. Queue/worker
events and decision notes are also durable. Private
query evidence is separate from public commentary and shared replays.

For the model, each response begins with a small event marker and a chess_status
call. Its fresh snapshot retains the complete move notation, repeats only the
last twelve messages and omits redundant historical FEN arrays. Delivering this
as a tool result avoids retaining every board snapshot as a permanent user
message. Password-account memory is supplied through the same status tool.
The resumed Codex conversation retains earlier context, with a 400,000-token
context window (380,000 usable) and automatic compaction at 300,000 total context
tokens. Both settings are checked and reapplied on start/resume; increasing the
threshold alone would be clamped by the smaller default model window.
Engine queries still receive the full authentic
history. Search responses condense repetitive PV diagnostic geometry while
preserving warnings and tactical changes. The complete original query remains
on disk; `chess_query_details` retrieves it by a server-owned index within the
same game's query directory, without executing another search.
Each tool reply reports the action's remaining token allowance. The default
3,000,000-token action limit and 20,000,000-token daily limit include repeated input
and compaction. Retry status identifies the candidate/query requirements for
the new response attempt, so saved evidence cannot be mistaken for completed
workflow steps in that attempt.

## Identity, memory and sharing

Guest identity comes from an HttpOnly, SameSite=Strict cookie; typing an existing
guest name does not grant its identity. Names are normalized and unique without
case distinctions. Passwords use salted scrypt; cookie and one-hour single-use
reset tokens are hashed at rest. Reset revokes all sessions. Reset links carry
their token in a URL fragment and are not logged as HTTP query strings.

Password-protected accounts alone can opt in to user-edited memory notes.
The model receives these as untrusted conversational context, without email,
password, cookie or reset data. No memory is made public in a replay. The user
can edit or disable it; disabling does not rewrite already-recorded historical
Codex conversations that had previously received that memory.

Private game endpoints require the exact owner. Sharing is an explicit
end-of-game action that creates a separate snapshot containing only the board
record and, if selected, public messages. Private candidate notes, tools, model
reasoning, credentials, email, account IDs and memories are excluded. Message
content is rendered as text, never as HTML. Sharing a new snapshot revokes the
old URL. A generated public page depends on this service and is not yet a
downloadable standalone HTML bundle like the original experiment archives.

## Prompt-injection and operating limits

User text is never inserted into privileged instructions. The system prompt
identifies opponent messages/names/memories as untrusted. The restriction is also
enforced outside the conversation: built-in shell, filesystem-changing tools,
browser/search, plugins, host skills and subagents are disabled; environment
access is empty; approval requests are denied; the effective configuration is
checked before a turn. Unknown capabilities fail closed. See the bridge reference
for the exact audited version and protocol assumptions.

The HTTP layer enforces exact Origin, CSRF, host checks, small request bodies,
bounded text, rate limits, security headers and no-store private responses.
The supervisor enforces game admission, queued/active workers, tool calls,
search deadlines, cumulative thinking allowance and daily token reservations.
The model cannot change these settings by agreeing to an opponent's request.

These controls reduce exposure; they are **not a claim of proven multi-tenant
isolation on Amazon Linux**. The deployed `astra` account, read-only runtime
mounts, hidden operator files, process/memory/CPU limits and public TLS proxy
have passed the checks recorded in
[LIGHTSAIL-DEPLOYMENT.md](LIGHTSAIL-DEPLOYMENT.md), including two real model turns
inside the application service's exact sandbox. The application remains bound
to loopback behind Caddy; public HTTPS is reachable after the Lightsail firewall
change. These checks do not establish an outbound destination allowlist or
complete tenant isolation. Full Linux games, live Linux compaction, heavy load,
offsite backups and startup after reboot remain unverified or unconfigured.
The earlier [capacity assessment](../benchmarks/README.md) used read-only SSH
inspection and bounded engine benchmarks loaded entirely in memory.

## Deliberate initial limits

- One server process and SQLite; up to 16 queued/active games, one active worker
  by default, three unfinished games per user, 1000 messages per game.
- No automatic engine-only move when the model fails, and no model downgrade.
- Memories are user-managed notes, not autonomous profile extraction.
- No email address changes/password settings page after initial protection;
  password reset supports recovery when an email was supplied and SMTP configured.
- Conservative insufficient-material recognition follows the authored engine;
  exotic dead-position proofs are outside its existing rules coverage.
- No takebacks, opening books, external engine/evaluation bars, tablebases,
  ratings, leaderboards, spectator lobby or cross-game strategy database.
- Failed/cancelled paid requests may use tokens before usage is reported. Local
  reservations are conservative accounting, not an exact dollar circuit breaker.
- The deployed launcher trusts forwarded client addresses and scheme only from
  Caddy at `127.0.0.1`. IP rate limits therefore use the forwarded client address;
  visitors sharing a public address still share those limits. Heavy-load and
  comprehensive host-isolation testing remain deployment work.
