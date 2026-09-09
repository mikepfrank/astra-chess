# Codex player integration

The private Python bridge starts one Codex app-server process for an active game
action and terminates it afterwards. A game retains its dedicated `CODEX_HOME`,
thread ID and usage watermark under `ASTRA_DATA_DIR/players/<game-id>/`. Resuming
uses that same home and thread, with a fresh authoritative game snapshot. The
server owns accepted moves, clocks, identities, transcripts and tactical tools.
The process has an empty working directory, rather than the writable repository.

`CodexPlayer.run(game_id, snapshot, tool_handler, emit, thread_id=None)` is async.
The handler receives seven game tool names and two private lifecycle callbacks:
`_thread {thread_id}` is emitted immediately when an ID is received, and
`_usage {tokens}` reports cumulative usage within this action. Both the bridge's
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

The bridge sets `model_auto_compact_token_limit = 20000` with
`model_auto_compact_token_limit_scope = "total"`, checks the effective values,
and reapplies them when starting or resuming a thread. Both fields are present
in the installed `ConfigReadResponse` schema and were accepted unchanged by a
no-key strict-config/initialize/config-read check with code mode enabled. The
[configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)
defines this as the automatic compaction threshold for the full active context.
It does not reduce the model's actual context window or change Astra/Ultra.

Automatic compaction summarizes history within the existing game thread; the
next action still resumes its saved ID and receives fresh authoritative state.
The bridge does not start a separate manual compaction turn. Compaction item
events remain private, and usage notifications during the active turn count
toward the same action allowance. The threshold is neither a billed-token cap
nor a guarantee that every request contains fewer than 20,000 tokens:
instructions, new output and compaction itself also consume context or tokens.
The host's compact query replies and bounded snapshots reduce repeated input;
complete tactical evidence remains private on disk for targeted retrieval.

`currentTime/read {threadId}` is also supported, returning only the server's
integer UTC Unix timestamp. A mismatched thread or extra arguments are rejected;
the request counts against the same per-action request limit. It cannot adjust
the chess clock or authorize an operation.

## Host responsibilities and practical limits

Opponent messages and password-account memory enter a JSON data envelope at
user priority. The fixed player prompt specifies the independent-candidate,
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
cleanup. Simulated automatic-compaction item events preserve the same thread
and cumulative accounting. The tests and no-key configuration checks do not
establish that a live automatic-compaction cycle has completed; they do not call
a model or use real credentials.

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
