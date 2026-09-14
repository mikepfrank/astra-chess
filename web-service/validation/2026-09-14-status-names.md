# Arcturus status-name audit — September 14, 2026

Mike reported an earlier “Astra is thinking” banner and requested an audit of
hard-coded player names in the live-game interface. Both the current local and
deployed thinking-banner implementation already selected the configured game
name. An older open page is a possible explanation for that sighting, not a
confirmed diagnosis. The live JavaScript response has `Cache-Control: no-cache`;
a normal refresh loads the current script.

The audit found remaining generic-player references in server-generated worker
notices, action-validation errors, resource-admission messages, the operator
monitor, initial HTML placeholders and downloaded filenames. Commit `3c43bf7`
corrects them:

- Per-game server notices use the saved persona name.
- The browser adapts old host-status messages at display time, leaving the
  saved record and all conversation text untouched.
- Initial HTML and the operator monitor use neutral labels where no game
  identity is available; the board's loaded identity uses its game/config data.
- Downloads use `chess-game.pgn` and `chess-replay-…html`.
- Historical harness attribution, genuine Astra game fallbacks and technical
  storage/API identifiers remain intact.

Validation: 50 existing Windows tests passed across service integration, daily
resource limits, compaction clocks and replay branding. The staged Linux
service suite passed all 17 tests. Its initial invocation failed before test
execution because the working directory was not on Python's import path; the
corrected invocation used the staging web-service directory.

Fully intercepted browser checks passed for queued, thinking, calculating,
compacting, error, disabled and post-game thinking states. Legacy error text
displayed Arcturus, while a fixture's historical chat text still named Astra.
The bold red error style, board flip and mobile layout remained correct.
The existing monitor checks passed access, escaping, stale-response, visibility,
desktop/mobile and sign-in behavior. A fixture race was corrected by waiting
for interception before cancelling its simulated hidden-tab request.

Deployment used a separate server staging checkout, idle checks, a stopped
experimental service, coherent private backup and namespace preflight. At
20:07 UTC, all eight game documents, all database table contents and private
file digests matched before and after. Only Arcturus restarted; original Astra
and Caddy PIDs were unchanged. The private backup receipt is in the operator's
`status-names-20260914T200734Z` backup directory. Public UI responses matched
deployed source bytes, all three health endpoints returned HTTP 200, and public
configuration still selected Arcturus with Max reasoning. No model call or
game action was performed for this update.
