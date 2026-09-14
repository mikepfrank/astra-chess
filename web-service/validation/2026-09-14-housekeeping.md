# Arcturus repository checkpoint — September 14, 2026

Mike requested periodic commit/push and handoff maintenance so work can survive
compaction or interruption. This checkpoint adds no image-upload feature and
does not deploy or restart an application.

## Current operational baseline

At **22:44:55 UTC**, a read-only SSH check confirmed clean Arcturus live checkout
`ce668680f429290a07b3615774288895fa248ce1`. The original and experimental apps,
Caddy and both notification timers were active. Both loopback health requests
returned 200 with their respective canonical Host headers. An initial probe
without the required Host header was rejected with 400; the corrected probe
established health without changing server settings.

The application repairs and previous deployment notes were already pushed through
`351fabe`. Subsequent housekeeping commits preserve documentation and operator
sources locally and on `origin/codex/openrouter-chess`; they do not mean the live
checkout has advanced. The parent `main` and adjacent `codex/hosted-chess`
worktrees are outside this housekeeping scope.

## Preserved continuity and source coverage

- Root [HANDOFF.md](../../HANDOFF.md) now identifies the actual Arcturus worktree
  before the dated local-experiment handoff and points to the maintained
  [service handoff](../HANDOFF.md).
- The handoff records High chat / Max moves, the repaired 600-second chat policy,
  successful 206.8-second live retry, clock/data preservation, unresolved latency,
  both monitors/notifiers, disabled general recovery SMTP, deployment safeguards
  and the distinction between saved unfinished games and online players.
- [FUTURE-FEATURES.md](../docs/FUTURE-FEATURES.md) preserves the deferred image
  attachment proposal, documentation evidence, text-only implementation
  boundaries, request-size limits, replay/privacy considerations and the still
  untested exact provider image path. No implementation is automatically queued.
- The previously untracked DNS `.txt` import copy is preserved alongside its
  existing `.zone` counterpart. Their SHA-256 hashes matched. The DNS README
  identifies it as an applied historical artifact and points to newer mail
  activation status; it should not be reimported.
- The exact-commit chat regression runner was promoted from ignored `var/` to
  [tests/check_chat_policy.py](../tests/check_chat_policy.py), with a guarded
  entrypoint and refusal to issue an exact-commit receipt for tracked local
  modifications. Its ten-module test list matches the suite already validated
  on Windows and Linux for `ce66868`.
- The chat/parallel deployment source dependency chain is retained under the
  [dated operator archive](../tools/ops/history/2026-09-14/README.md). Direct
  execution is disabled; fixed historical revisions and host assumptions are
  documented. The gate/Caddy primitives already existed in tracked source and
  were not duplicated.
- The public-domain check, installed-notifier namespace/WAL audit and disposable
  three-message mail lifecycle check were promoted to tracked helpers. Entry
  points are guarded; mail requires explicit send flags and recipient arguments.
  Personal recipient literals were removed, and the mail checker defaults to
  Arcturus's separate configuration. The public audit has bounded requests and
  no credentials. See [operator tools](../tools/ops/README.md) for exact commands.
- The task's external visualization directory was inventoried recursively by
  filename, including hidden files; it was empty. No external task assets needed
  moving into this checkout. Private/runtime directories were not swept into Git.

Private/runtime material remains intentionally excluded: environment/API keys,
budget ledgers, live game databases, private replays, copied player/session
trees, raw provider/model logs, caches, runtime binaries, generated bundles and
full backup/incident receipts. Historical one-off wrappers whose reusable
behavior and outcomes are already captured in operator tools and validation
notes remain scratch evidence. Keeping them out of Git does not delete them.

Validation for this checkpoint is offline syntax/CLI/import and documentation
link checking, plus the read-only health snapshot above. The embedded notifier
fixture also compiles; both historical deployment entrypoints refuse execution.
No preserved mail/namespace/public audit was run against live services during
housekeeping, and no messages or paid model calls were sent. The previously recorded
151-test Windows and 150-pass/1-skip Linux results belong to the live repair,
not a new full regression run for this documentation/source-preservation commit.
