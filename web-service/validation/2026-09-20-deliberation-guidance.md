# Brief independent assessment before the tactical query

Mike requested a small play-guidance adjustment after the reported output-limit
incident: strategize independently, but consult the engine promptly instead of
debating quiet positions indefinitely. Inspection confirmed the failed attempts
never reached a current-position candidate/query. The first search after
compaction completed depth 4 in 14 seconds: `Nc6` +74cp, `a5` +53cp, `Nd7` +53cp,
all from Black's perspective. That supports several plausible choices, but does
not establish why the earlier generation exhausted its output allowance.

## Change

`prompts/move-deliberation-policy.md` is a short generic play instruction,
separate from the persona. On own move turns, after `chess_status`, it asks for
a brief independent comparison in quiet positions, one legal candidate and a
concrete concern, then prompt `chess_candidate` and `chess_query` calls. It
discourages proving a dominant choice before querying; completed depth, tactical
evidence and positional judgment still guide the final decision. Small heuristic
score gaps do not automatically override a sound plan. The review reserve stays.

The bridge supplies this through its existing trusted developer-instruction
path for saved Arcturus/OpenRouter bindings on every thread start/resume. This
reaches both current and future games without changing saved base prompts,
persona metadata or dynamic-tool hashes. Original Astra/other personas are
unchanged. The wording explicitly applies only on own move turns, preserving
chat-only and finished-game tool restrictions.

This is prompt guidance, not a new enforced token/time limit or a demonstrated
fix for every output cutoff. Reasoning levels, output allowance, routing,
compaction, clocks and resource budgets are unchanged. No live test turn is
sent and no historical game record is edited.

## Verification and activation

Activated code `3108148be92f6a67446721a770b669281bb46b33` on September 20 at
15:06 UTC through the idle/gated deployment helper.

- Two focused Windows bridge tests passed, covering policy inclusion on
  start/resume and exclusion from other personas; Python compilation and diff
  checks passed.
- Exact-commit Linux regression: 306 tests, 305 passed, one Windows-only skip,
  no failures or errors.
- Native Linux Codex 0.154.0 reasoning audit: four completed actions, preserving
  move Max/High selection and chat High. The full new policy was present on
  actual mocked-provider requests, including resumed games.
- Native tool visibility audit: nine wire checks passed, preserving the
  65,536-token tool-output allowance.
- Native private-notes audit: three resumed actions, eight requests, six notes,
  two public comments; conditional reminder and full deliberation-policy wire
  checks passed while saved prompts/tool hashes stayed fixed.

The gate was restored and health verified after activation. All 32 game
documents, all database table and private-file digests, configuration, service
units and notification timers were unchanged. Arcturus PID changed from
`4056774` to `4139815`; original Astra (`3778964`) and Caddy (`3778975`) did not
restart. The root-private coherent backup and activation receipt are under
`/home/or-chess/backups/ui-reasoning-20260920T150601Z`.

No paid model request, live move, retry or chat was sent for validation. This
verifies instruction delivery and state preservation, not a measured improvement
in move latency or a guarantee against further output-limit failures.
