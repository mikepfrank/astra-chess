# September 15: monitor pagination and selectable move reasoning

Requested by Mike after a day of beta play. Scope is the isolated Arcturus
worktree and service; original Astra is unchanged.

## Behavior

- Monitor: newest activity first, ten games initially, 10/25/50/100 selector,
  Newer/Older and range/page counts. Filters precede pagination; refresh retains
  or clamps the page. Authorization loss clears private content and paging.
- Board: accessible High/Max radio switch between chat and scoresheet, stored
  with the game. Max is the default; selection persists and affects the next
  admitted move response. Changing it during work does not restart that response.
- Chat remains High. No model selection, instruction override, clock refund,
  new action scheduling or historical profile migration accompanies the control.
- Existing owner/CSRF/origin, request-id and version checks protect updates.
  Unsupported profiles hide/reject the control. Finished games reject changes;
  suspended games can save a preference without resuming.
- Effective effort is recorded with accepted AI moves/decisions. New exports
  derive played High/Max effort from recorded moves, falling back to the original
  saved level on older moves. Existing archived HTML and game identity remain intact.

## Local verification

Both intercepted Chrome suites passed without contacting live sites: monitor
pagination/filter/refresh/access-loss and the move selector's persistence,
active-turn display, pending guard, conflict recovery, keyboard, mobile layout,
and suspended/finished/unsupported states. Desktop/mobile screenshots were
visually inspected; artifacts remain under ignored `var/browser-qa`.

The real local Codex executable completed Max move, High move, High chat with
Max selected, then Max move on one disposable thread. Eight mocked provider
requests preserved the original identity/instructions and 32K output cap, and
all child processes were reaped. No paid model requests were made.

Local Python checks passed 161 tests with one Windows symlink-permission skip
across 162 tests, covering authenticated preference actions, frozen effort and
clock behavior, bridge/profile validation, service, persona and evaluation
regressions. The independent board-selector source review found no blocker.

The additional export/identity/branding checks ran 32 tests: 30 passed and two
existing Windows symlink-permission cases were skipped. No historical generated
archives were changed.

## Linux verification and activation

Exact release `3e2bb627fe509213366eef3e9f85a673a52f0b8c` passed 265 tests:
264 passed and the Windows-only process case was skipped. Linux Codex 0.154.0
completed all four actions on the same thread, with eight mocked provider
requests and no real credentials or upstream calls. The 32K response cap, 250K
compaction trigger and original identity were verified. Receipts remain in
the private staged checkout's `web-service/var`.

The Arcturus-only deployment completed in the **17:43 UTC / 12:43 CDT** window
on September 15. The final idle checks passed before stopping. All 18 stored
game documents, every database-table digest and private-file digest matched
across restart. Configuration, all service units, both notification timers,
and original Astra/Caddy process IDs were unchanged. The private backup and
receipt are under `/home/or-chess/backups/ui-reasoning-20260915T174314Z`.
The maintenance gate restored its exact Caddy configuration and health passed.

The signed-in live browser showed 15 player games (three QA games excluded),
ten rows on page one and five on the older page, then returned to page one.
Mike's current saved game displayed the High/Max control with Max selected,
unchanged 53 plies and 46:48 clock. Verification submitted no live move, chat
or preference. These counts and game state are dated observations only.

## Compact-layout follow-up

Mike requested smaller controls beside the label. Static HTML/CSS now place
“Move thinking:” and High/Max on one compact row, with one short help line.
The row wraps at narrow widths; radio labels, keyboard focus and descriptions
are retained. The intercepted selector suite passed again, and the mobile
render and independent accessibility review passed. This follow-up needs only
a verified static-file fast-forward, with no application restart or game pause.
