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

Export regression, exact-commit Linux checks and activation results will be
recorded here once complete. Until that activation record is added, the last
verified live code remains `ce668680f429290a07b3615774288895fa248ce1`.
