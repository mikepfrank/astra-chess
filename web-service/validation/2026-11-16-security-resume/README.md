# Services resumed after the OS upgrade

Completed November 16, 2026 evening (November 17 UTC). Mike explicitly requested
resuming the services and addressing any upgrade-related problems as they arise.
This supersedes the earlier sequence that kept all applications stopped until
private runtime/Caddy/image activation. **All four applications are now live.**

The OS upgrade remains installed. The staged private chess Python/certifi,
shared GPT-2 certifi, Caddy and Docker image candidates were **not promoted**.
Those security updates, and the separate Codex compatibility work, remain
pending. Any later activation must obtain a fresh quiet/drain checkpoint;
do not follow old instructions that assume applications remain stopped.

## Restoration and checks

- Public GPT-2 was started behind its POST gate and reached model readiness.
  The private lab was then started behind its full gate, preserving existing
  session data and pending inputs. No real lab session was used for testing.
- Both chess applications started behind maintenance gates. Direct health,
  board, public-game list and monitor-shell routes returned HTTP 200.
- Arcturus's installed preflight passed every check: account/configuration,
  credential presence without disclosure, private budget, password hashing,
  Codex executable, read-only source/runtime, hidden operator files and resource
  restrictions. Python 3.12.14 and Codex 0.154.0 remain unchanged, as intended.
- Astra's equivalent preflight passed with its monitor EnvironmentFile included.
  The first diagnostic launcher incorrectly joined two EnvironmentFile paths
  into one property and failed before executing the preflight. A disposable
  `/run/systemd/system/` unit with separate EnvironmentFile directives corrected
  that invocation and was removed afterward. This was a diagnostic-launcher
  problem, not an application startup failure. No production unit was edited.
- [Public GPT-2 smoke check](gpt2-public-smoke.json): one synthetic generation,
  16-token cap, accepted 202; streamed progress and completion; final/repeated
  result retrieval and export/import round trip passed. Queue returned idle.
  The model revision, CPU/FP32 settings and context limit are unchanged. This
  was a loopback check behind the gate and did not access browser-owned chats.
- [Private sandbox check](gpt2-baseline-sandbox-probe.json): the original
  production image passed no-key/no-network checks for UID, dropped capabilities,
  no-new-privileges, seccomp, read-only root, nested Bubblewrap, Codex sandbox,
  schema generation and app-server initialization. No provider model turn ran.
- Both GPT-2 live mount namespaces can run their original venv with OS Python
  3.12.16/OpenSSL 3.5.8 and construct a TLS context. Their certifi remains
  2026.07.22 until the separate pending update.

The reviewed `astra-up.sh` and `arcturus-up.sh` helpers restored the chess routes
and prior app/timer enablement. Each intentionally restarted shared Caddy.
The GPT-2 helper's `reopen --validated` then restored its two routes via graceful
Caddy reload and restored original boot settings. All three active maintenance
checkpoints were archived by their respective helpers; none remains active.
Astra's independent new-game pause was preserved.

[Final status](final-service-status.json), checked at 01:07 UTC, confirms:

- All four application services, Caddy and both notification timers active and
  enabled; no failed units or application journal entries at error priority
  since resumption began. Each app has zero automatic restarts.
- Astra, Arcturus and its old alias return HTTP 200 at health, board, public
  games and monitor-shell routes. Both GPT-2 HTTPS health routes return 200
  without maintenance headers; the private capability path is not recorded.
- Both notification jobs have already run successfully since timer restoration.
  Delivery state was preserved; no manual test email was sent.
- Independent checks from the Windows laptop also return HTTP 200 for all
  three chess health URLs and `https://gpt2-chat.com/api/health`.

These are startup, runtime, sandbox and focused public GPT-2 smoke checks.
No paid chess move/chat or private lab provider request was made; authenticated
monitor behavior and a full game were not retested. Existing game/session state,
model settings and ledgers were not manually edited. Retain the manual host
snapshot and private backup while remaining maintenance is outstanding.
