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

Exact-revision Linux checks and activation results will be recorded below.
