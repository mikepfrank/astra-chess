# Conditional sidebar publication reminder

Mike reported that a resumed older game continued answering in ordinary private
notes despite the developer publication policy. He requested an additional
reminder when an action records notes without a sidebar comment.

## Behavior and boundaries

The supervisor stores `comment_reminder_pending` transactionally with an actual
new private note when that host response action has not published a comment.
Only successful nonblank public delivery clears it. Duplicate notes, failed
comments, tool-only actions, failures and cancellation do not clear the marker.
A trailing final note after successful public delivery in the same action does
not rearm it. Existing games without a marker bootstrap from saved note presence;
this intentionally errs toward one reminder for older conversations.

The bridge mirrors successful host callback results within the action. The
gateway appends one fixed developer message as the final input item on each
subsequent chess request while pending. It says that only `chess_comment()` is
displayed in sidebar chat, and to use that tool when intending to reply. It is
not an instruction to invent a comment or launch another model action.

The saved OpenRouter GLM/Arcturus binding scopes the change. Original Astra,
hidden reasoning, saved base prompt/tool hashes, move thinking choices, clock
mechanics and public export policy are unchanged. Native history does not
accumulate reminder copies; compaction receives none and does not clear the
marker. Outgoing size checks include the reminder. Private telemetry adds a
boolean, never input contents.

## Verification

- Real Windows Codex 0.154.0-alpha.6.2, mocked provider: passed three actions and
  eight requests across two process restarts, six notes and two public comments.
  Every conditional reminder is the final developer input item. Pending status
  survives a notes-only action, clears on delivery, and stays clear after the
  closing note. Long ordinary notes and the old saved prompt survive unchanged.
- Windows gateway/bridge suite: 75 passed. Supervisor chat-policy suite plus
  the two focused bridge reminder tests: 17 passed. These cover failed/blank
  comments, durable retry/resume, duplicate notes, legacy bootstrap, original
  Astra, compaction exclusion and the outgoing request byte ceiling.
- Linux regression at exact clean commit
  `31f3270c50daeb1d647571eb6e187b860f94ce99`: 306 tests, zero failures/errors,
  one Windows-only skip (305 passed).
- Native Linux Codex 0.154.0 at that commit: reasoning audit passed four actions
  and eight requests; long-tool-output audit passed three cases and nine wire
  checks; private-note audit passed three actions/eight requests with conditional
  reminder suffixes verified throughout. All used mocked providers.

## Live activation

Activated `31f3270` September 18, 2026 at 15:21 UTC / 10:21 CDT through
`deploy_arcturus_ui.py`, from the clean installed `c9755e4` checkout. Runtime
previously used backend `bf5b746`; later old commits were tools/documentation.
The service was idle before admission gating and before shutdown. Health and
gate restoration passed, with no active turn interrupted.

- Private backup/receipt:
  `/home/or-chess/backups/ui-reasoning-20260918T152133Z`.
- All 29 game documents, all database table digests, all private file digests,
  configuration, units and notification timers were unchanged across restart.
- Arcturus PID changed from `4015431` to `4056774`.
  Original Astra `3778964` and Caddy `3778975` stayed running.
- Two workers, Max move default/High chat, 32K output, 250K compaction and 200M
  daily tokens were preserved. No further restart or gameplay pause is pending.
- Exact-commit receipts are under the isolated stage
  `/home/or-chess/ui-staging/31f3270/web-service/var/`.

No live game move, chat, retry or real provider request is used for QA.
