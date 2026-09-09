# Local alpha validation

Checkpoint: September 9, 2026. Development and checks ran natively on Windows
with Python 3.12.14, Node.js 24.16.0 and the installed codex-cli 0.153.4.
All authored application files are under `web-service/` on branch
`codex/hosted-chess`, in a separate worktree. The original engine, experimental
records, replay templates and skills were not modified.

## Reproduced checks

The final application suite passed **44 tests in 44.815 seconds**:

```powershell
& ./.venv/Scripts/python.exe -m unittest discover -s tests -v
```

- 14 bridge tests use local subprocess fixtures to exercise start/resume,
  durable conversation IDs, usage accounting, private/public event separation,
  tool/configuration rejection and process cleanup.
- 10 identity tests cover cookie persistence, name ownership, salted password
  hashes, opt-in protected-account memory, single-use recovery, concurrent
  recovery requests, expiry and TLS requirements.
- 17 service tests cover ownership, Origin/CSRF/body limits, authoritative moves,
  special chess rules, duplicate/stale requests, draw handling, private/revocable
  sharing, clock evidence, budget admission, suspension, recovery and cleanup.
- Two regression tests cover shrinking the review reserve on a low clock and
  retrying a failed chat response during the human's turn.
- One adapter test runs the unchanged local tactical engine in a real subprocess,
  including an explicit hypothetical move and history/evidence checks. This is
  an integration check, not a depth or playing-strength benchmark.

The existing repository's full engine suite was not rerun: its source is
unchanged. The new adapter test verifies this application's actual invocation.
Starlette emitted a non-failing deprecation warning about its TestClient's
httpx compatibility; the runtime dependencies are pinned in `requirements.txt`.

`node --check` passed for all three browser scripts. Literal DOM references
were also checked against the authored HTML.

An unauthenticated real CLI `initialize` and `config/read` smoke check passed
with the bridge's strict configuration. The CLI schema and effective config
were inspected locally. No model turn was started by that check.

## Browser review

The embedded browser was used to inspect the real disabled-player preview and
a separate disposable fixture server. The fixture visibly identified its
scripted opponent; it did not call Astra or any external chess resource.

Verified interactions included guest creation, White game creation, legal
square selection, accepting e4 and a scripted reply, SAN history, clock credit,
chat, an agreed draw, optional commentary sharing and replay navigation.
Manufactured HTML in chat was displayed as literal text. Revoking a replay
was verified to make its HTTP endpoint return 404. An already-loaded page or
saved copy can of course retain content it previously received.

A 390 by 844 browser viewport had no horizontal document overflow; this was
an emulated viewport check, not physical-phone testing. The normal preview
remains available on loopback port 8788 with real play disabled.

## Remaining integration gates

1. Configure a service API key outside source control and run a controlled
   Astra/Ultra game, including resumption after a service restart. Neither
   `OPENAI_API_KEY` nor `CODEX_API_KEY` was present in the development process;
   no paid model calls were made. Account access to this exact model/effort,
   model-visible tool inventory, conversation recovery and actual costs still
   require a live check.
2. Measure engine depth, move latency and memory on the selected Linux host
   before choosing concurrency. No Lightsail capacity claim has been made.
3. Validate the dedicated account, read-only code, process/CPU/memory limits,
   egress restrictions, TLS proxy, proxy-aware rate limiting, backups and
   restart behavior on Amazon Linux. The deployment files are examples, not
   an installed or audited production configuration. Windows descendant-process
   isolation is not established by the local bridge tests.
4. Configure SMTP and verify real email delivery before offering recovery email
   publicly. Current tests use an injected transport, with no email sent.
5. Review the first live game's transcript, clock ledger and API usage, then
   set operational limits for the initial friends-only alpha. Token accounting
   is conservative admission control, not a guaranteed dollar ceiling.

No remote push, public deployment, SSH operation or AWS change was performed.
The next step is live integration with credentials, followed by host validation;
the current checkpoint is a local alpha, not a completed public launch.
