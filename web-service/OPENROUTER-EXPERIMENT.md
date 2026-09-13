# OpenRouter chess experiment

Checkpoint: September 13, 2026. Mike selected Codex CLI as the first driver,
`z-ai/glm-5.3-flash` as the first model, throughput-oriented routing and a $50
initial local experiment budget. This branch implements that configuration with
the existing from-scratch chess engine and hosted supervisor.

The [shared playing contract and versioned personas](prompts/README.md) are
stored separately. New GLM games select Mike's supplied Arcturus draft;
existing experimental games keep their exact recorded prompt and identity. The
gateway checks the complete pinned instructions on every provider request.
The [isolated Linux deployment guide](docs/OPENROUTER-DEPLOYMENT.md) describes
the new `or-chess` account and `arcturus.astraplayschess.com` test hostname.

## Scope and isolation

- Branch: `codex/openrouter-chess`, based on hosted commit
  `306db42ba31e256a9425f51ff93e587982202427`.
- Worktree: `C:/Users/MikeFrank/Documents/ChatGPT/Chess/openrouter-worktree`.
- Keep development, disposable games and credentials here. The original `main`
  checkout, `codex/hosted-chess` checkout and production records remain separate.
- The local launcher binds to `127.0.0.1:8790`; its default data directory is
  `web-service/var/openrouter-local`. It overrides inherited data-directory and
  origin settings and accepts only a dedicated data directory below this
  worktree's `web-service/var`.
- The Lightsail trial uses a separate `or-chess` Linux account, service,
  configuration, data directory and loopback port 8792. Shared host capacity
  is bounded separately with a half-CPU quota, lower scheduling priority and
  2 GiB memory ceiling for the experiment.

Read the [hosted handoff](HANDOFF.md), [architecture](docs/ARCHITECTURE.md) and
[player instructions](prompts/player.md) for the preserved chess workflow.
The original service and its game records are outside this deployment's scope.

## Driver and playing contract

The explicit `openrouter-glm` profile selects
`z-ai/glm-5.3-flash:nitro` through OpenRouter's Responses endpoint. OpenRouter
documents `:nitro` as equivalent to `provider.sort: "throughput"`: eligible
providers are tried in throughput order. It is a routing preference for the
selected model, not a guaranteed speed or a model substitution. See
[provider routing](https://openrouter.ai/docs/guides/routing/provider-selection).

| Setting | Deployed profile v3 configuration |
| --- | --- |
| Driver | Codex app-server, direct function tools |
| Model | `z-ai/glm-5.3-flash:nitro` |
| Reasoning setting | `high` |
| Context window / compaction trigger | 1,310,720 / 250,000 total-context tokens |
| Output ceiling | 8,192 tokens per provider request |
| Gateway byte limits | 8 MiB per request; 2 MiB per upstream SSE event |
| Active workers | One |
| Cumulative token ceiling per action | At most 2,000,000, including repeated input and compaction; smaller operator overrides remain effective |
| Daily token allowance | Selected Arcturus deployment override: 200,000,000; shared application default: 20,000,000 |
| Chess clock | 90 minutes, +30 seconds per own move, +30 minutes after move 40 |
| Ordinary / critical turn targets | 120 / 240 seconds, reduced by earned balance |

The supervisor retains authoritative moves, clocks, legal-action checks,
independent candidate registration, mandatory current-position search and private
query evidence. The model still reviews counterplay and chooses its move. There
is no automatic engine-only move or model downgrade when an action fails.

New games and saved Codex recovery state bind the model profile, prompt hash and
tool-schema hash. Profile v3 admits exactly the authorized v2 runtime upgrade
from 128,000/80,000 to 1,310,720/250,000 context/compaction settings. All other
saved identity fields must match, including the model, persona, prompt and tool
schema. Original game and recovery provenance stays intact; the bridge records
the new runtime context policy separately. Reverse, partial and unknown-version
changes remain incompatible. Unbound legacy games still require their original
Astra configuration. The engine source fingerprint remains separately checked.

This context-compaction update was deployed as `43a494e` on September 13 at
21:32 UTC. Its [repair validation](experiments/arcturus-compaction-repair-2026-09-13.json)
is separate from the earlier paid smoke tests below. At 250,000 tokens, repeated
context in the mandatory status, candidate,
query and choose rounds can exceed the former 1,000,000-token action limit.
The 2,000,000 ceiling leaves room for those rounds and compaction. A focused
no-model regression completes compaction and a full move at 1,549,152 tokens;
an explicit smaller limit still interrupts correctly. Daily admission reserves
the configured action ceiling and settles actual complete usage; missing or
incomplete usage remains conservatively charged. The $50 session budget and
$5 stop threshold are unchanged.

Mike subsequently selected a 200,000,000-token daily allowance for the live
Arcturus deployment, through its private `ASTRA_MAX_DAILY_TOKENS=200000000`
environment setting. The setting was activated and verified in the running
process and installed service namespace at 22:02 UTC on September 13. See the
[allowance update record](experiments/arcturus-daily-allowance-2026-09-13.json).
The shared 20,000,000-token code default and the original Astra
deployment are unchanged. This raises the Arcturus UTC-day admission allowance
without resetting recorded usage, increasing the 2,000,000-token action ceiling,
or changing the separate $50 lifetime spending guard and $5 stop threshold.

## Observed CLI boundary and local gateway

The exact local build `0.154.0-alpha.6.2` passed the isolated, no-key startup
configuration audit. A separate loopback wire capture observed two additional
built-in advertisements despite the restricted configuration:
`request_user_input` and the `skills` namespace. Startup configuration alone
therefore did not establish the intended model-visible tool list.

The experimental profile admits that exact build with an authenticated local
gateway. The gateway removes those observed declarations, validates the seven
canonical chess schemas, caps output, and forwards only to the fixed OpenRouter
Responses endpoint. Codex receives a temporary local credential; the OpenRouter
key stays in the service. Unknown tool shapes are rejected. The forwarded chess tools
are `chess_status`, `chess_candidate`, `chess_query`, `chess_query_details`,
`chess_critical`, `chess_choose` and `chess_comment`.

For automatic compaction, the gateway also accepts the audited exact `tools: []`
request with no forced tool choice. It preserves the same complete pinned
persona instructions, model, routing, budget check and output ceiling. Summary
responses may contain assistant text and reasoning, but tool-call output is
rejected. Missing tool declarations and partial chess-tool sets remain invalid.
Compaction grants no additional host capability. Its lifecycle pauses the chess
clock and turn allocation; tokens and the independent process timeout still
apply.

The gateway permits at most 8 MiB for each incoming and forwarded serialized
request, while retaining a separate 2 MiB cap for each upstream SSE event.
These are byte limits, independent of the model's token window. This permits
larger repeated-context requests without relaxing the output-event bound.

Every provider request receives a fresh budget check. The gateway disallows
concurrent requests and does not retry HTTP requests or follow redirects. The
bridge also rejects unexpected capabilities and model rerouting. The alpha build
is admitted only for this experimental profile; the original Astra profile's
audited-version policy remains separate.

Implementation: [profiles](astra_web/player_profiles.py),
[bridge](astra_web/codex_bridge.py), [gateway](astra_web/openrouter_gateway.py).
The [startup audit](tests/audit_model_profile.py) and
[wire audit](tests/audit_model_wire.py) use isolated homes and local evidence.
Neither audit establishes real model tool use or playing strength.

## Credentials and the $50 session budget

The existing OpenRouter key can be used without changing its provider settings.
The private budget ledger pins that credential and records the first model-action
preflight's cumulative OpenRouter and BYOK usage. All subsequent increases in
both counters count against the experiment's $50 lifetime allowance, including
other activity using the same key. New games, application restarts and provider
daily resets do not reset this baseline. Credential swaps, decreasing counters,
missing telemetry and nonfinite values stop new work.

Remaining allowance is the smaller of `$50 - combined usage increases` and the
provider's remaining key allowance, when one is reported. New actions and
provider requests stop at $5 or less remaining. This is **local usage-delta
admission control, not a provider-enforced hard spending cap**: usage reporting
delay and work already in flight can exceed an allowance. The one-worker limit,
output ceiling and $5 reserve provide additional bounds for the small first trial.
OpenRouter documents the [usage fields](https://openrouter.ai/docs/api_reference/limits)
and [request-time cap limitations](https://openrouter.zendesk.com/hc/en-us/articles/51680687417499-Can-I-create-one-API-key-per-user-with-its-own-spending-limit-Management-API-keys).

The [setup helper](configure_openrouter.py) accepts a hidden terminal prompt,
validates key telemetry without an inference call, and uses Windows user-scoped
DPAPI storage under private `var/` paths. It reads no OpenAI setup or credential.
Explicit `OPENROUTER_API_KEY` environment configuration is also supported. Setup
does not establish a new budget baseline; the first action preflight does.
Run setup and the service as the same Windows user. Keep keys out of commands,
screenshots, source control and public replay records.

## Local setup and checks

From this worktree's `web-service` directory, create its own virtual environment
with Python 3.12; do not install packages into another checkout's environment:

```powershell
# Use the bundled Python's absolute path if python is unavailable on PATH.
python -m venv .venv
& ./.venv/Scripts/python.exe -m pip install -r requirements.txt
$chessCodex = 'C:/path/to/reviewed/codex.exe'
& ./.venv/Scripts/python.exe configure_openrouter.py --codex-bin $chessCodex
& ./.venv/Scripts/python.exe run_openrouter.py
```

Open `http://127.0.0.1:8790`. Close that local server before the isolated paid
smoke test so only one experiment uses the allowance at a time:

```powershell
& ./.venv/Scripts/python.exe -m unittest discover -s tests -v
& ./.venv/Scripts/python.exe tests/live_codex_check.py --live --profile openrouter-glm --codex-bin $chessCodex --data-dir var/openrouter-smoke --turns 2
```

The paid check uses the real supervisor and engine for two model actions,
separated by a deterministic legal test-opponent reply. It tests initial play
and continuation in one saved conversation. Its private records remain in the
selected data directory; the spending baseline is shared across this worktree.
Successful smoke tests establish operation and resumption, not Elo or strength.
Later comparisons should hold engine revision, hardware and wall-time policy
fixed, using genuine legal histories and recorded candidate/search decisions.

## Initial pre-persona validation checkpoint

The complete regression suite passed **300 tests with 2 skipped** on September
13, 2026, on this Windows host.
The real Codex executable also completed the gateway wire audit against a local
mock Responses provider, with the seven canonical chess tools forwarded.

The paid two-action test used the real supervisor and from-scratch engine. GLM
played `1.e4`, resumed its saved conversation after the deterministic test reply
`1...a6`, and played `2.d4`. Both moves were accepted, with one completed engine
query and one public comment per model turn. Charged own-turn times were 20.93
and 23.14 seconds. This is an operational check, not a strength measurement.

All ten provider requests completed successfully with the selected GLM model.
OpenRouter generation metadata identified BaseTen, Crusoe and Together as the
providers and reported 132 native reasoning tokens. Total reported inference
cost was **$0.00629936**; the refreshed local budget had **$49.99370064** remaining.
The [sanitized experiment record](experiments/glm-5.3-flash-smoke-2026-09-13.json)
contains per-request cost, timing and provider metadata without credentials,
private response IDs or model reasoning text.

Linux deployment was untested at that initial checkpoint. The September 13
Arcturus checks below superseded that limitation. Neither initial smoke test
exercised long-game context compaction or established playing strength. The
gateway at that checkpoint accepted the audited chess-action request shape;
the subsequently deployed text-only compaction support is described above.

## Arcturus Linux validation, September 13

The persona split passed the 303-test Windows regression run (2 skips), 11
additional persona tests and 6 deployment-helper tests. A later gateway fix
passed all 16 gateway tests on both Windows and Linux. Linux also passed 64
focused profile, persona, setup and service-helper tests. These were separate
runs, rather than one combined test invocation.

Under the installed experimental unit's actual filesystem and resource
restrictions, Python 3.12.14 and Codex 0.154.0 passed the namespace preflight and
the mock-provider wire audit. The full composed Arcturus instructions arrived
unchanged, with only the seven canonical chess tools forwarded.

The paid two-action Linux check then played `1.d4 a6 2.Bf4`, resuming the saved
conversation between turns. It recorded two candidates, two engine queries and
two accepted decisions. All ten provider requests completed and verified the
same full prompt. OpenRouter selected Together for those requests; their total
reported inference cost was **$0.00600888**. The test used half of one logical
CPU and a 2 GiB memory ceiling. It establishes basic operation and continuation,
not a playing-strength comparison.

An initial attempt exposed a metadata mismatch: the response model was correct,
but the selected endpoint used `z-ai/glm-5.3-flash-20260826`. The
[public catalog](https://openrouter.ai/api/v1/models) identifies that exact dated
slug as the configured model's `canonical_slug`. The gateway now permits this
verified identifier only in endpoint metadata; response-model and requested
model checks remain strict. Unknown future identifiers still stop work for
review. The failed attempt cost $0.00085475 and a small routing diagnostic cost
$0.00076505; both remain part of the unchanged shared experiment allowance.

See the [sanitized Linux smoke record](experiments/arcturus-linux-smoke-2026-09-13.json),
[deployment validation record](experiments/arcturus-validation-2026-09-13.json),
and [deployment guide](docs/OPENROUTER-DEPLOYMENT.md) for current activation status.
