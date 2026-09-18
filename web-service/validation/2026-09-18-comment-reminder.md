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
- Exact-commit Linux/native checks: pending.
- Live activation: pending; earlier backend `bf5b746` remains installed until
  the idle/gated deployment receipt below confirms otherwise.

No live game move, chat, retry or real provider request is used for QA.
