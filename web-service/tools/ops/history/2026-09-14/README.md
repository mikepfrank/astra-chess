# Historical Arcturus deployment sources

These two sources preserve the one-use deployment logic previously kept only
under ignored `web-service/var/` and copied to the operator host's `/tmp/`.
**Direct execution is disabled. They are reference evidence, not general
deployment commands or an instruction to repeat completed operations.**

- `deploy_parallel_workers.py` records the final two-worker deployment, pinned
  from `3c43bf7` to `565c057`. Its shared helpers also supplied idle detection,
  full game/table/file preservation, origin-aware health, process checks and
  the bounded installed-unit namespace preflight for later deployments.
- `deploy_chat_allowance.py` is the final September 14 variant, pinned from
  `16e2bd8` to a staged candidate with exact-commit test and native-reasoning
  receipts. It was used to deploy `ce66868` at 22:24:26 UTC. Its final form is
  not the earlier 22:07:33 timeout-only deployment script.

The dependency chain is complete in Git: the chat source imports its adjacent
parallel-worker helpers; the maintenance gate and Caddy activation primitives
are the existing tracked files two directories above. The preserved sources
add that import path. The former executable blocks are retained as
`historical_entrypoint()` functions; running either file directly exits before
any service, database, proxy or Git operation. Operator-specific fixed paths,
old/new revisions and receipt expectations remain historical values.

Do not run these functions against a live host without a newly reviewed,
explicit deployment plan and freshly validated preconditions. In particular,
their isolated code rollback uses `git reset --hard` only on the expected clean
experimental checkout; it is not a mechanism to restore old player databases.
Importing the support module does not operate the host, but calling its helpers
can read private data or run privileged service operations.

Validation and outcomes are in
[parallel-workers.md](../../../../validation/2026-09-14-parallel-workers.md) and
[chat-deadline.md](../../../../validation/2026-09-14-chat-deadline.md). Private
receipts/backups stay on the host and outside Git. The offline regression runner
is now [tests/check_chat_policy.py](../../../../tests/check_chat_policy.py);
the actual Codex transport audit is
[tests/audit_chat_reasoning.py](../../../../tests/audit_chat_reasoning.py).

Other old scratch deployment wrappers and incident collectors are not current
entrypoints. Their reusable procedures are preserved in tracked operator tools,
service checks and validation notes. Raw private game copies, credentials,
budget state, transcripts, provider logs and generated runtime output remain
excluded rather than being swept into this archive.
