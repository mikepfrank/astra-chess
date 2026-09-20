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

Prepared; the two focused Windows bridge tests passed, covering policy inclusion
on start/resume and exclusion from other personas. Native audits compile and
the diff check is clean. Exact-commit Linux/native checks and idle/gated activation
are pending. Native
reasoning and private-note receipts now additionally require the full new policy
on the actual provider wire, covering Max/High moves and resumed conversations.
