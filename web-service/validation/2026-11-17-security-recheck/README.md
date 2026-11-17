# Post-OS preparation complete — services remain live

November 17, 2026, approximately 00:55–01:09 America/Chicago. Mike authorized
**step 1 only** while heading to bed and explicitly deferred downtime and
deployment until he returns. All staged candidates remain inactive. No app or
proxy restart/reload, admission gate, production link/config edit, paid API
request, real inference or test email occurred in this preparation stage.

Mike had already confirmed the private GPT-2/Codex lab, public GPT-2 service and
Arcturus work after the OS upgrade. Astra's site is online; its longstanding
new-game restriction remains intentional and was not lifted for testing.

## Results

| Candidate check | Result |
|---|---|
| Astra final-path Python/venv, exact deployed source | 282 tests: 279 passed, 3 expected Windows-only skips |
| Arcturus final-path Python/venv, exact deployed source | 594 tests: 591 passed, 3 expected Windows-only skips |
| Public GPT-2 candidate venv under updated OS | 206 passed, no failures/errors/skips |
| Private GPT-2 candidate venv under updated OS | 381 passed, no failures/errors/skips |
| Caddy security build | Integrity/provenance/config adaptation and isolated TLS, HTTP1/2, POST, SSE, compression, redirect and WebSocket tests passed |
| GPT-2 sandbox candidate | Exact image identity verified; no-key/no-network nested sandbox, Codex initialization and schema probes passed |

**1,457 application tests passed; six Windows-only skips, no failures.**
The GPT-2 selection retains the prior 36 public/51 lab operator-only exclusions;
these results do not recertify historical deployment scripts. All suites were
isolated from production data, credentials, external networking and model
weights. Each test job was limited to half of one CPU, at most 2 GiB RAM and
nice 10; Caddy/container jobs used 768 MiB. Prior staging evidence was preserved.

## Artifact checks and evidence

- [Chess artifact verification](chess-artifact-verification.json): three sealed
  manifests/lock files and all 18 wheels match retained SHA-256 values. The
  independently hashed Python archive still matches its reviewed digest;
  3,519 non-bytecode runtime files per installed candidate match the archive.
  Each venv's 1,036 hashed installed RECORD entries verify, package versions
  match the original manifests, and `pip check` and certificate-backed TLS
  context construction pass. Python 3.12.16, OpenSSL 3.5.9, Expat 2.10.0,
  certifi 2026.10.23 and pip 26.3 are unchanged from the staged plan.
- [Chess fixtures](chess-fixtures-postos.json) and [notes](chess-fixtures-notes.md):
  the actual final unused candidate interpreters were used as their service
  identities. New disposable source copies match 912 Astra and 1,017 Arcturus
  files from retained deployed git archives; old stage trees were not edited.
  Both transient fixture units are unloaded/inactive, PID 0. The first attempt
  stopped at a diagnostic accessibility guard before running tests; replacing
  `exists()` with an actual readability check correctly handles systemd's
  unreadable InaccessiblePaths placeholder. No candidate/source change was needed.
- [GPT-2 integrity](gpt2-artifact-integrity.json), [fixtures](gpt2-postos-fixtures.json)
  and [details](gpt2-preparation.md): all 20,634 live and 20,635 candidate
  non-bytecode entries match their original inventories and committed digests.
  Both selected deployed/copied source trees and candidate ownership verify.
  Fixtures now exercise OS Python 3.12.16/OpenSSL 3.5.8 with candidate certifi
  2026.10.23; compiled tiny-tensor and offline TLS/httpx checks pass. A fresh
  result-directory overlay preserved previous reports without changing the runner.
- [Caddy/image results](caddy-image-results.json) and [details](caddy-image-summary.md):
  Caddy binary SHA remains `e8903acf0e525a53d9ad7c8d72b10bc63b71392ff39f9b7786c15d51a0639d01`;
  Go archive/build metadata/module provenance matches. Both binaries adapt the
  current entire config identically as `astra`; all 132 installed modules remain
  available (136 in the candidate). Live TLS storage was never provisioned.
  Candidate image remains `sha256:cd4677302c525c03f02fefe65da2944ec07c6d4bb52aa0bf611a54dc504e71d1`,
  with all five sealed image-build artifact digests matching. Its Codex 0.154.0
  schema matches the baseline. Production tag/launcher/seccomp remain unchanged.
- The separate staged Codex 0.169.0 archive also retains SHA
  `3b8ed091149cc63a59046b9f094bcfa21cdb4dda15ede441ce369bcee4a71ba0`.
  This is artifact verification only; its outstanding full compatibility audit
  was not folded into this preparation stage.

[Final production check](production-unchanged.json) confirms the original PIDs
and zero restarts for Astra 4105, Arcturus 4317, public GPT-2 3982, private lab
4373 and Caddy 5194. All remain active/enabled. Every scoped HTTPS health route
returns 200, both notifier timers remain active/enabled, active chess venv
inodes/configs are unchanged, no maintenance checkpoints were created, and
Astra's new-game pause remains. No failed systemd units were reported.

## Boundary and resumption

This is an artifact and post-OS compatibility recheck of the reviewed staged
targets, not a fresh comprehensive vulnerability-database audit. Prior advisory
and container scan limitations remain. Actual production mount visibility after
switching, live TLS-storage behavior, private gateway/network operation and
bounded provider checks still belong to the gated activation stage. No claim
is made that the pending security updates are already active.

**Stop here with services available.** The [next-window checklist](next-window.md)
records fresh drain/backup requirements, activation and rollback boundaries,
the diagnostic EnvironmentFile lesson, and the separate Codex work. Do not
reuse the old completed maintenance checkpoints or start downtime automatically.
The pre-security manual snapshot and private backups remain available; include
new games/lab activity in a fresh backup before the next deployment.
