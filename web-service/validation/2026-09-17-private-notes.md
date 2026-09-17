# Explicit public comments and optional internal-note export

## Behavior and scope

For saved Arcturus/OpenRouter GLM games, only `chess_comment` publishes new
sidebar messages. Completed ordinary assistant messages in the normal,
commentary and final-answer phases are persisted separately as `assistant_notes`.
They remain in the native per-game Codex conversation for subsequent model
context, subject to normal compaction. Hidden reasoning, partial deltas, tool
traces and compaction summaries never become exportable notes.

The trusted policy in `prompts/public-comment-policy.md` is supplied through
developer instructions on both thread start and resume. It explicitly overrides
the older saved prompt's public-assistant-text statement, requires the tool for
human replies, and explains the owner's post-game export option. Saved prompt,
persona, model, thread and tool-schema hashes are unchanged. In particular, do
not casually edit dynamic-tool descriptions: they participate in the saved
schema hash. Other saved personas and the original Astra retain their behavior.

The private callback is not a model-callable tool. Each saved note records its
item ID, phase, text, committed ply, timestamp and last public message ID. IDs
suppress duplicate delivery; anchors preserve interleaving even when wall-clock
timestamps tie or go backwards. Notes do not consume the public message quota
or its size allowance. Existing response token/RPC limits still apply. Ordinary
message persistence does not alter clocks, turns or public message versions.

Export chat now opens a compact options dialog. "Include AI's internal notes?"
starts unchecked on every opening. Notes can be requested only after a game
finishes; the server enforces this and ownership. Opt-in adds
`?include_notes=true` to the existing RTF endpoint. Notes are labeled "AI internal
note - not sent to sidebar" and use muted italic indented formatting. Public
comments and moves keep their normal styling. All content is escaped as literal
RTF text. Default exports, public replays and normal board snapshots exclude the
private stream. The note stream is not fetched into the browser page.

This is prospective: historical sidebar messages and existing replay artifacts
are preserved as seen by their players. No historical transcript reclassification
or private rollout import occurs. Saved games acquire notes on subsequent model
actions without a migration. No actual player chat, move, retry or paid provider
call is required for validation.

## Validation before deployment

- Focused bridge/supervisor reasoning tests cover private phases and long text,
  duplicate delivery, forged tool rejection, original Astra behavior, public
  quota separation, clock preservation and snapshot/replay exclusion. One new
  replay test initially used a future fixture clock with a real export timestamp;
  matching the export timestamp to that fixture fixed the test setup.
- Eighteen RTF/API tests pass, including opt-in ordering, authentication,
  finished-only access, Unicode/RTF escaping and unchanged default exports.
- Browser export, matchup and thinking-control regressions pass. Desktop/mobile
  options dialogs were visually checked; native-picker activation, fallback,
  cancellation and stale account/game handling remain covered.
- Native Windows CLI `0.154.0-alpha.6.2` audit passes two actions/six mocked
  requests across a process restart: four private notes (including text longer
  than the public allowance), two explicit public comments, retained note history
  and the trusted developer policy on every transmitted request. The audit
  reports structure/hashes, never real user text or credentials.

The opt-in synthetic RTF was also opened in a separate hidden Word instance,
exported to PDF and rendered with Poppler. The one-page preview shows muted
italic notes with 24pt indentation, and the following public chat correctly
returns to normal dark text and 12pt indentation. Unicode, literal braces and
backslashes render correctly. Default RTF bytes are unchanged with versus
without stored notes. All task-created Word processes were closed. Synthetic
previews are ignored under `var/browser-qa/internal-note-preview.*`.

## Exact Linux validation and activation

Candidate `bf5b746ddc7ff3546611eb39febfe0d13209dab4` passed 299 Linux tests:
298 passed, one Windows-only skip, zero failures or errors. The exact clean
staged checkout also passed native CLI `0.154.0` audits:

- Four actions/eight requests preserve selectable move effort and fixed High chat.
- Three long-output cases/nine wire checks preserve tool and human text on resume.
- Two actions/six requests preserve private ordinary notes across process restart,
  publish exactly two explicit comments, and carry the current developer policy
  in every actual provider request. Hidden reasoning never enters the note stream.

All upstreams were mocked; no real keys or paid API calls were used.

The fresh idle checks and gated activation completed at **2026-09-17 16:32:04
UTC / 11:32:04 CDT**. Prior checkout was `9d7bd95`. Backup/receipt:
`/home/or-chess/backups/ui-reasoning-20260917T163204Z`.
All **28** saved game documents, every database-table digest and private-file
digest, private configuration, service units and notification timers remained
unchanged. Arcturus PID changed `3943873` to `4015431`; original Astra PID
`3778964` and Caddy PID `3778975` were preserved. Health and namespace checks
passed and the maintenance gate was restored.

A temporary signed-in live tab confirmed the completed-game Export chat dialog:
the notes option was enabled and unchecked, with Cancel and Download controls.
It was closed without downloading or scheduling work; the original user tab
was preserved without a reload. No game state or user setting was changed for
browser verification. Existing tabs need a refresh for the new static UI.

## Owner-requested single-game retrospective test

After the prospective rollout, Mike explicitly requested converting just his
recent finished 81-ply game as a test case. This is a scoped exception to the
historical preservation policy above, not an automatic migration of other games.

The read-only inventory found 321 public messages: 46 human, 53 explicit
`chess_comment` messages, and 222 ordinary assistant messages. The native rollout
also has unpublished items, so simple position matching is insufficient. The
repair planner requires a unique ordered subsequence alignment of every stored
AI message against ordinary assistant items and success-confirmed comment calls.
Ambiguous or missing evidence aborts. Neither writing style nor hidden reasoning
is classification evidence. Text, ply, timestamps and complete interleaving must
survive the conversion exactly; existing note anchors are rebased as needed.

The operation is prepared in `tools/ops/reclassify_81ply_game.py`: read-only by
default, exact inspected state/source hashes required to apply, service-identity
SQLite access, coherent private backup, short idle maintenance gate, and one
transaction changing only this game's messages/notes/version plus an audit event.
Native history, previously generated replays, other games and services remain
outside its write scope. Application results are recorded below when complete.
