# Codex candidate staging — November 15, 2026

Status: **candidate staged; not approved for production promotion by tests yet**.
Both chess services still use Codex 0.154.0. No live source, allowlist, unit,
configuration, game home, credential, or service process was changed. No model
or email calls were made.

## Candidate and integrity

- Official release: [Codex 0.169.0](https://github.com/openai/codex/releases/tag/rust-v0.169.0),
  also listed in the [official changelog](https://learn.chatgpt.com/docs/changelog).
- Complete Linux musl standalone archive:
  `codex-package-x86_64-unknown-linux-musl.tar.gz`.
- SHA256:
  `3b8ed091149cc63a59046b9f094bcfa21cdb4dda15ede441ce369bcee4a71ba0`.
- The downloaded archive matches both the GitHub release asset digest and the
  release's `codex-package_SHA256SUMS` entry. The Sigstore bundle was retained
  but its signature was not separately verified.
- Remote staging root:
  `/home/ec2-user/chess-security-stage-20261115/codex`.
- Candidate executable: `bundle/bin/codex` beneath that root; it reports
  `codex-cli 0.169.0`. The complete bundle, not just that executable, is retained.
- No symlink or active executable path was switched.

The remote staging directory also contains the archive/checksums, isolated
source copies, 479 generated experimental protocol-schema files, `probe.py`,
and the raw no-turn probe reports. The compact, credential-free evidence is
[codex-assessment.json](codex-assessment.json).

## Completed checks

The no-turn probe ran against separate copies of the exact deployed source:

| Service | Source revision | Candidate result |
|---|---|---|
| Astra | `60bc178f3b442a2c333ed35dc304a99e17106b00` | Strict config, initialize, config/read and thread/start passed |
| Arcturus | `a98784cdafacbe5e6616cc55b0e94a34e8056bf2` | Strict config, initialize, config/read and thread/start passed |

Each probe used an isolated generated Codex home and a pruned environment with
no real API credentials. It ran inside `unshare --net`, preventing external
network access. Its RPC wrapper allowed only initialize, initialized,
config/read and thread/start; **turn/start was prohibited**. The application
version gate was not changed or bypassed in production: this separate probe
invoked the candidate directly for an explicit pre-admission audit.

The existing effective-config checker passed for each configuration. Returned
thread settings matched the expected model/provider, reasoning effort,
`approvalPolicy=never`, `approvalsReviewer=user`, empty runtime roots,
no active permission profile, no instruction-source additions, and a read-only
sandbox with network access disabled. Astra remained `gpt-6-astra` / Ultra;
Arcturus remained `z-ai/glm-5.3-flash:nitro` / Max. No new model was selected.

Selected generated schemas retain the parameters used by the bridge, including
thread start/resume, turn start, dynamic-tool call/results and token-usage
notifications. This is an interface inspection, not proof of full event-stream
or model compatibility.

## Promotion matrix

| Area | Status | Required before promotion |
|---|---|---|
| Bundle integrity / executable startup | Passed checksum and version checks | Retain full bundle and record installed ownership/modes |
| Strict config / no-turn thread boundary | Passed for both deployed profiles | Repeat inside actual service namespaces with candidate paths visible |
| Production version gate | Correctly remains unchanged | Review supporting evidence before admitting 0.169.0; adjust version-pinned service-check helpers |
| Host/tool isolation | No-turn boundaries passed only | Audit actual advertised tools and disabled built-ins, tool result execution, and sandbox behavior |
| Model request wire / reasoning | Not exercised | Run mocked provider wire tests for Astra and OpenRouter, including High chat, High/Max moves, 32K output and long tool outputs |
| Usage / clock / budget semantics | Not exercised | Run mocked usage, interruption and compaction accounting tests |
| Thread continuation | No real game thread opened | Test saved thread continuation, private notes, compaction and parallel workers using disposable isolated state |
| Real provider operation | Not exercised | After model-free/native checks pass, run the approved small paid smoke tests in disposable private state |

Two startup log messages deserve review during the full audit. Codex calls the
old `features.multi_agent` setting deprecated and describes `agents.enabled`
as the newer control; the intended absence of subagent tools must be checked
on the actual model wire. It also reports no system bubblewrap on PATH and
falls back to its bundled bubblewrap. Neither message prevented these probes,
but tool execution and native sandbox validation have not been established.

There is **no demonstrated candidate incompatibility** from these limited
checks. There is also **not enough evidence to expand the production
allowlist**. Keep the Codex migration separate from urgent OS, certificate-trust,
private Python and Caddy patches so those fixes need not wait for this audit.
