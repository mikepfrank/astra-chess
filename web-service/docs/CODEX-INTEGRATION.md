# Codex player integration

The private Python bridge starts one Codex app-server process for an active game
action and terminates it afterwards. A game retains its dedicated `CODEX_HOME`,
thread ID and usage watermark under `ASTRA_DATA_DIR/players/<game-id>/`. Resuming
uses that same home and thread, with fresh authoritative state from `chess_status`. The
server owns accepted moves, clocks, identities, transcripts and tactical tools.
The process has an empty working directory, rather than the writable repository.

`CodexPlayer.run(game_id, snapshot, tool_handler, emit, thread_id=None)` is async.
The handler receives seven game tool names and three private lifecycle callbacks:
`_thread {thread_id}` is emitted immediately when an ID is received, and
`_usage {tokens}` reports cumulative usage within this action.
`_compaction {phase, item_id}` reports validated compaction starts/completions.
Both the bridge's
recovery file and the host database retain the ID. Conflicting stored IDs fail
closed. `close()` terminates active processes; callers must serialize a game.

The initial configuration preserves **gpt-6-astra / ultra**. A missing key,
unavailable model, different effective reasoning setting, unsupported protocol,
or security configuration mismatch stops play while preserving the game. There
is no automatic model downgrade or engine-only fallback. The operator supplies
`OPENAI_API_KEY` in the service environment; the bridge passes it only to the
Codex authentication/provider environment. It does not read the operator's
existing Codex home, copy login files, or write the key into game files. The
custom provider's endpoint is fixed to `https://api.openai.com/v1`.

## Audited protocol contract

Protocol details were checked against local **codex-cli 0.153.4** on September 9,
2026 with `codex app-server --help`, `codex features list` and
`codex app-server generate-json-schema --experimental --out <temporary-dir>`.
The bridge rejects other CLI versions until a maintainer audits them. The
generated schemas are inspection output, not another bundled dependency.
An unauthenticated local app-server startup and `initialize`/`config/read` smoke
check passed with this generated strict configuration. That check found that
the documented `tools.view_image` key is rejected by this build; the verified
`features.view_image = false` setting is used instead.

The [official app-server documentation](https://learn.chatgpt.com/docs/app-server)
describes initialization, thread start/resume, streamed events and experimental
dynamic tools. The bridge follows this sequence over private stdio; it exposes
no app-server listener to browsers. Tools persist with the thread and return
results through `item/tool/call`. Only completed public assistant messages go
to the player; reasoning events and raw tool output remain private.

The installed schema adds details essential to this implementation:

- Dynamic specs use `type: "function"` and `inputSchema`; results use
  `contentItems: [{type: "inputText", text: ...}]` and `success`.
- `thread/start.sandbox` is `"read-only"`; the response sandbox is
  `{type: "readOnly", networkAccess: false}`.
- `environments: []` on thread/turn start disables environment access. This is
  the boundary that removes environment-backed shell, patch and file tools.
  The resume schema has no dynamicTools field; stored definitions are reused.
- `turn/start.effort` accepts a nonempty string at the protocol-schema level.
  This does not establish that a particular model or API account supports
  `ultra`. The effective thread response is checked before a model turn starts;
  explicit model rerouting events abort the action.
- Usage notifications carry a cumulative `tokenUsage.total.totalTokens`. The
  persisted watermark avoids counting earlier turns again after resumption.

The [official configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)
documents provider environment keys, ephemeral credential storage, disabled web
search, feature flags and the read-only sandbox. The bridge disables shell,
exec, browser, computer use, plugins/apps, hooks, memories, delegation and other
unneeded capabilities. Additional approval requests are denied and terminate
the action; unknown host requests and tool names also fail closed.
The effective configuration is read back before thread creation, and enabled
ambient MCP servers or capabilities that failed to disable are rejected.

The locally cached Astra model catalog specifies `tool_mode: code_mode_only`.
The first authenticated Astra/Ultra trial completed a response but reported no
available tools with code mode disabled. The bridge therefore enables
`features.code_mode` and the separate local `features.code_mode_host`, requiring
`disable_in_process_fallback = true`. This supplies JavaScript orchestration for
the registered chess tools; it does not enable shell, file, browser, network,
plugin or delegation tools. Environment access remains empty. The existing
tool-name allowlist, request limits and external turn deadline still apply.
The [app-server reference](https://learn.chatgpt.com/docs/app-server) describes
its local code-mode host; the installed build accepts these feature settings in
a no-key strict-config/initialize/config-read check.

The bridge sets `model_context_window = 400000` and
`model_auto_compact_token_limit = 300000` with
`model_auto_compact_token_limit_scope = "total"`, checks the effective values,
and reapplies them when starting or resuming a thread. These fields are present
in the installed `ConfigReadResponse` schema and were accepted unchanged by a
no-key strict-config/initialize/config-read check with code mode enabled. The
[configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)
defines the compaction threshold for the full active context. The larger context
setting preserves Astra/Ultra.

Automatic compaction summarizes history within the existing game thread; the
next action still resumes its saved ID and reads fresh authoritative state.
The bridge does not start a separate manual compaction turn. Compaction item
events drive the host's `COMPACTING` indicator and chess-clock pause; their
contents remain private. Usage notifications during the active turn count
toward the same token allowance. The threshold is neither a billed-token cap
nor a guarantee that every request contains fewer than 300,000 tokens:
instructions, new output and compaction itself also consume context or tokens.
The host's compact query replies and bounded snapshots reduce repeated input;
complete tactical evidence remains private on disk for targeted retrieval.

The pinned `ItemStartedNotification` and `ItemCompletedNotification` schemas
identify compaction as `item.type = "contextCompaction"`, with a stable item ID
and explicit thread/turn IDs. The bridge converts only those validated events
to `_compaction {phase: "started" | "completed", item_id}`. Duplicate events do
not repeat callbacks. An unmatched completion and a later repeated start are
ignored, without retrospective clock credit. Wrong-thread/turn events, invalid
identifiers and overlapping intervals fail closed. A pre-turn compaction
received after submitting `turn/start` binds that requested turn even if the
normal start notification or RPC response has not arrived yet; its tokens are
charged to the action.

`completed` is emitted only for an actual matching CLI completion event. The
[versioned compaction implementation](https://github.com/openai/codex/blob/rust-v0.153.4/codex-rs/core/src/compact.rs#L234-L375)
can exit on error before emitting completion. On interruption, cancellation or
process exit, the bridge leaves an unmatched start for the supervisor to settle
as an interrupted pause; crash recovery also closes persisted open pauses.
The host uses its own timing for clock accounting. Public assistant items and
chess-tool requests are blocked while compaction is active, so summary text
does not leak and paused clock time cannot cover ordinary chess-tool work.
The CLI's hooks remain disabled; these callbacks add no model-callable tool or
arbitrary command capability. Independent token and emergency wall limits still
apply during compaction.

Live trials exposed repeated compaction at a 20,000-token threshold: a resumed
request already used about 16,500 tokens, and a diagnostic reply immediately
crossed the threshold again. The generous 300,000-token threshold leaves much
more room for game history before summarizing. It requires enlarging the
catalog's default 272,000-token raw window. The exact 0.153.4
[bundled Astra catalog](https://github.com/openai/codex/blob/rust-v0.153.4/codex-rs/models-manager/models.json)
permits a maximum raw window of 872,000 tokens. Its
[override implementation](https://github.com/openai/codex/blob/rust-v0.153.4/codex-rs/models-manager/src/model_info.rs#L21-L33)
clamps the requested window to that maximum, so 400,000 resolves unchanged.
The [model calculations](https://github.com/openai/codex/blob/rust-v0.153.4/codex-rs/protocol/src/openai_models.rs#L458-L480)
then yield 380,000 usable tokens (95%) and a 360,000 automatic-compaction ceiling
(90% of the raw window). The requested 300,000 threshold fits below both.
This conclusion combines the versioned implementation and catalog with local
strict-config verification; an actual model turn using more than the previous
default context has not been exercised by that no-key check.

The default per-action allowance is 3,000,000 cumulative tokens across model/tool
rounds and compaction; the daily allowance is 20,000,000. The service retains
the existing 500-action daily limit, single-worker default and game clock/query
limits. These settings do not change the API's maximum response-output setting
or Astra/Ultra. Retaining more context reduces summarization frequency but sends
more input on each model call; playing quality and long-game cost still require
live observation.

Because compaction preserves user messages, each new turn now receives only a
bounded event marker with game ID and numeric version/ply. It instructs Astra to
call `chess_status` first. Board state, transcript excerpts and account memory
arrive as tool results, which can be summarized during compaction. Existing
history is retained. Each chess-tool reply includes host-owned `resource_budget`
fields `max_action_tokens` and `remaining_action_tokens`; the latter is null
until this action has reported usage. An in-flight response can still consume
tokens before the next usage event arrives.

`currentTime/read {threadId}` is also supported, returning only the server's
integer UTC Unix timestamp. A mismatched thread or extra arguments are rejected;
the request counts against the same per-action request limit. It cannot adjust
the chess clock or authorize an operation.

## Host responsibilities and practical limits

Opponent messages and password-account memory enter a JSON tool-result envelope
as untrusted data. The fixed player prompt specifies the independent-candidate,
tactical-query, prospective-review and considered-choice workflow. The host
validates each structured request, supplies authentic history, budgets engine
queries, and accepts only legal actions for the current game/version. Prompt
instructions complement those mechanical controls; they do not replace them.

Token limits interrupt on reported usage. An in-flight response can consume
tokens before its next usage event; this is not a hard billing cap. Interrupted
requests may also have unreported provider usage. Use provider spending controls
and the host's wall-clock/concurrency limits in addition to these counters.
This implementation does not estimate dollar costs. The bridge has its own
300-second emergency timeout; the host applies the shorter ordinary/critical
clock allocation and can cancel the coroutine at any time.

On Unix, each process has a separate process group, terminated with TERM then
KILL. Windows creates processes hidden and suspended, assigns them to a
kill-on-close job, then resumes their primary thread. This prevents runtime
children escaping through an early-launch race. Code-host prewarming is disabled.
The job permits
at most eight processes and 1 GiB of committed memory for the app-server/runtime
tree; closing it terminates descendants even if app-server exited first. A local
fake-runtime descendant test verifies timeout cleanup. These limits bound
runtime resource use, not every possible runtime or OS vulnerability.
Production Linux deployment should enforce
service-user filesystem permissions, process/memory/CPU limits and outbound
network policy independently of Codex. A dedicated game home is useful
separation, not an OS sandbox between mutually untrusted processes.

## Verification status

`python -m unittest discover -s tests -p test_codex_bridge.py` uses real local
Python subprocesses acting as fake app-servers. It checks start/resume, durable
IDs, usage accounting, public/private event separation, forbidden tool and
approval denial, configuration/version rejection, cancellation and timeout
cleanup. Simulated automatic-compaction tests cover pre-turn ordering,
duplicates, unmatched completions, invalid thread/turn IDs, summary privacy,
mid-compaction failures and cancellation while preserving token accounting.
The tests and no-key configuration checks do not
establish that the revised 400,000-context/300,000-compaction policy completes a
live turn; they do not
call a model or use real credentials. The earlier 20,000-token policy did compact
live, exposing the repeated-work problem described above.

Real Astra/Ultra actions have now submitted legal moves using the local tactical
engine. The completed HTTP integration check played e4/e5, resumed the same
Codex conversation for chat, then verified resignation, optional commentary
sharing and revocation. It used a separate guest account and left the user's
browser identity intact. See [LIVE-VALIDATION.md](LIVE-VALIDATION.md) for the
earlier failures, measured usage and the checks actually completed.

The production Lightsail environment and its hard OS limits remain unverified.
A full live game and a deliberately observed live automatic-compaction cycle
are not claimed by these short checks. Fake-process tests do not establish live
playing strength or complete runtime sandbox isolation.
