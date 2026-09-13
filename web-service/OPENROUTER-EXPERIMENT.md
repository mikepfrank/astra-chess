# Alternate-model chess experiment

Orientation checkpoint: September 13, 2026. This branch explores whether other
LLMs can operate the hosted chess toolkit, initially through Codex CLI and
OpenRouter on Windows, before a possible separate Lightsail deployment.
No alternate-model implementation or paid model test has been performed yet.

## Checkout and scope

- Branch: `codex/openrouter-chess`, based on hosted commit
  `306db42ba31e256a9425f51ff93e587982202427`.
- Local worktree: `C:/Users/MikeFrank/Documents/ChatGPT/Chess/openrouter-worktree`.
- The original `Chess` checkout remains on `main`; `Chess/hosted-worktree`
  remains on `codex/hosted-chess`.
- Work here with disposable data, isolated per-game model homes and credentials,
  and a distinct local port/origin. This orientation launches no server.
- Later Lightsail experiments are intended for a new Linux account and separate
  configuration, data, service name and port. Mike will create that account.
  A separate account still shares host CPU and memory; capacity needs checking
  before simultaneous experimental and production workers run.
- Production service, player records, operator credentials and the original
  engine/game journals are outside this experiment's working data.

Read [the hosted handoff](HANDOFF.md), [architecture](docs/ARCHITECTURE.md),
[Codex integration](docs/CODEX-INTEGRATION.md), [configuration and launch
reference](README.md), and [player instructions](prompts/player.md) for the
baseline. The root [handoff](../HANDOFF.md) preserves the original experiment's
intent; its pre-service status is historical.

## Findings from source review

The supervisor already accepts an injected player implementing async
`run(game_id, snapshot, tool_handler, emit, thread_id=None)` and `close()`.
See [supervisor.py](astra_web/supervisor.py) and
[codex_bridge.py](astra_web/codex_bridge.py). Authoritative moves, clocks,
candidate/query requirements, tactical evidence and resource enforcement stay
with the supervisor. The existing `player_factory` is a testing seam, not a
complete production provider registry.

The current bridge deliberately pins the OpenAI endpoint and credential name,
Astra/Ultra configuration, code mode, 400,000-token context and 250,000-token
compaction trigger. Availability checks and local credential setup also assume
OpenAI. An alternate provider therefore needs an explicit configuration profile
and corresponding effective-configuration checks, not just another key.

The seven chess tools have ordinary JSON schemas. Astra's requirement for Codex
code mode is separate from the chess-tool contract. Whether another model can
use those tools through this app-server integration remains unverified. Preserve
capability denial, process cleanup, early continuation persistence, truthful
usage accounting, public/private output separation and state reconciliation.

New games currently record model, reasoning and engine fingerprint. They do not
bind a complete provider/driver/prompt configuration or guard against all
configuration changes on resume. Before real experimental games, persist that
identity and reject incompatible resumes. Record requested and observed model
identity and provider routing where available; do not silently substitute models.
Adapt the opponent's displayed identity and runtime-specific prompt wording
while retaining its chess method.

## Provider feasibility and local prerequisite

OpenRouter's [Codex CLI guide](https://openrouter.ai/docs/cookbook/coding-agents/codex-cli)
documents a custom provider using its API endpoint and `OPENROUTER_API_KEY`.
The [official Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)
documents custom provider base URLs, environment credentials and Responses
transport. These sources were opened on September 13, 2026. They establish a
documented configuration path, not compatibility of a selected non-OpenAI model
with this service's tools, reasoning, continuation or compaction lifecycle.

The local `codex --version` currently resolves to `0.154.0-alpha.6.2`.
The baseline bridge accepts only `0.153.4` and `0.154.0`, including rejection of
version suffixes. Select an already audited executable if available, or audit a
separately selected build before changing the accepted versions. Do not update
the desktop installation or another checkout's runtime for this experiment.

## Proposed first implementation and validation

1. Retain Codex app-server as the first transport to investigate. Define an
   isolated provider/model profile with supported reasoning, context and tool
   settings. Keep the engine and initial wall-time policy fixed.
2. Extend configuration/contract tests with synthetic responses and disposable
   data. Cover allowed tools, unknown requests, model mismatches, usage,
   cancellation, duplicate acceptance, continuation/restart and output privacy.
   Treat context maintenance as compaction only when validated by the adapter.
3. Run a no-key protocol/configuration audit. This can validate local boundaries
   but cannot establish model access, real tool use or durable resume.
4. With model selection, secure key setup and a spending ceiling established,
   perform two real local actions separated by a deterministic legal test reply.
   Adapt the existing [live check](tests/live_codex_check.py); retain all private
   evidence. This is an operational smoke test, not a strength measurement.
5. Compare a small fixed set of positions with authentic legal histories, then
   paired games if successful. Record initial candidate, final choice, targeted
   questions, completed search depth, failures, wall time, token categories and
   available billed cost. Use the same engine revision, hardware and search/time
   limits. Engine scores are diagnostic evidence, not independent strength labels.

A direct OpenRouter tool-calling player could use the existing supervisor seam
if Codex compatibility prevents progress, provided Mike accepts that as a
separate experimental condition. Equal wall-time trials are the proposed initial
comparison; equal-cost trials can answer a different question later.

## Decisions requested from Mike

- Is retaining Codex a strict requirement or the preferred first approach, with
  a separate driver acceptable if needed?
- Which one or two models should lead the experiment, or should Astra select a
  shortlist after reviewing current capabilities and prices?
- What total OpenRouter spending ceiling applies to the initial local trials?

No secret is needed for this source review. Set up the key through private local
configuration when paid testing is ready; do not put it in this document or Git.

## Verification at this checkpoint

Reviewed the maintained handoffs, prompt, architecture, integration reference,
configuration, driver/supervisor interfaces and existing test contracts. Created
the isolated worktree and checked the default CLI version. Changes at this
checkpoint are documentation only; application tests were not rerun. No provider
model calls, local/live games, production access or deployment occurred.
