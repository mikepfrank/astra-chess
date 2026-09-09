# Codex player integration

The private Python bridge starts one Codex app-server process for an active game
action and terminates it afterwards. A game retains its dedicated `CODEX_HOME`,
thread ID and usage watermark under `ASTRA_DATA_DIR/players/<game-id>/`. Resuming
uses that same home and thread, with a fresh authoritative game snapshot. The
server owns accepted moves, clocks, identities, transcripts and tactical tools.
The process has an empty working directory, rather than the writable repository.

`CodexPlayer.run(game_id, snapshot, tool_handler, emit, thread_id=None)` is async.
The handler receives six public tool names and two private lifecycle callbacks:
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
- `turn/start.effort` includes `ultra`; the effective thread response is checked
  before a model turn starts. Explicit model rerouting events abort the action.
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
KILL. Windows starts child processes hidden and reaps the app-server process.
No child-executing model tools are enabled, but full Windows descendant-process
isolation has not been established. Production Linux deployment should enforce
service-user filesystem permissions, process/memory/CPU limits and outbound
network policy independently of Codex. A dedicated game home is useful
separation, not an OS sandbox between mutually untrusted processes.

## Verification status

`python -m unittest discover -s tests -p test_codex_bridge.py` uses real local
Python subprocesses acting as fake app-servers. It checks start/resume, durable
IDs, usage accounting, public/private event separation, forbidden tool and
approval denial, configuration/version rejection, cancellation and timeout
cleanup. The tests do not call a model or use real credentials.

The real model/API path remains **unverified** until an operator configures a
service key and runs a controlled game. CLI schema support does not establish
that this account can use this exact model/effort through API billing. The
production Lightsail environment, hard OS limits, model tool inventory and a
complete live game require an integration gate before announcing the service.
