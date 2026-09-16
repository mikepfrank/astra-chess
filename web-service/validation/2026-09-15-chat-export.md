# September 15: private rich-text chat export

The operator requested an Export chat button at the screen bottom that saves a
human-readable, formatted transcript with game moves and conversation correctly
interleaved. Implementation and validation are in progress; this note does not
yet establish live activation.

## Contract

- Export one account-owned current game as an RTF attachment, available during
  play, after suspension and after completion. Include the entire saved public
  conversation, including post-game messages, and accepted moves.
- Use the message's committed ply marker for placement: opening comments,
  first move, comments after that move, and so on. Preserve saved message order
  at each ply. Wall-clock timestamps are displayed, not used to reorder valid
  records. Legacy records without a valid ply use a deterministic time fallback.
- Format the title, participants/colors, game result/status, move notation,
  speaker labels, UTC timestamps and message paragraphs. Message wording remains
  literal, including any Markdown punctuation. Escape all RTF metacharacters;
  Unicode text and supplementary characters use signed UTF-16 RTF escapes.
- The owned GET endpoint has the same account boundary as PGN download. It reads
  a coherent saved snapshot without modifying games, clocks, workers, shares or
  public replay listings. Export no private prompts, tool evidence, model
  reasoning, credentials or internal identifiers.
- The footer control opens the browser's save picker directly on supported
  browsers. Otherwise it uses the ordinary browser download flow, like PGN.
  User cancellation is quiet; failed requests and identity/game changes must
  not save a stale or invalid response.

The picker requires a direct user gesture and is not available in every browser;
see [the browser API reference](https://developer.mozilla.org/en-US/docs/Web/API/Window/showSaveFilePicker).

## Local validation

- All twelve renderer/API tests passed, including both human colors, historical
  persona labels, timestamp ties/backwards clocks, legacy fallback, complete
  long Unicode comments, literal RTF escaping, private-field exclusion,
  authorization and repeated-download state preservation.
- The intercepted browser export test passed: keyboard operation, compact
  desktop/mobile footer, active/finished/suspended games, picker before fetch,
  cancellation, unavailable/blocked picker fallback, bad MIME/server errors,
  disk-write failure, game-switch cancellation and identity/logout protections.
  Existing matchup and move-thinking browser regressions also passed.
- Independent source review found no blocker in ordering, escaping, ownership
  or UI cancellation. A synthetic two-page RTF opened in a separate hidden
  Microsoft Word instance; all twelve message bodies round-tripped exactly,
  including Unicode, emoji, tabs, line breaks and literal RTF/Markdown syntax.
  Word-exported PDF pages were visually checked for readable formatting and
  pagination. The temporary Word instance was closed. Synthetic previews stay
  in ignored `var/browser-qa/`, never a real account export.

## Activation

Pending exact-commit Linux checks and the idle/gated deployment with existing
game-preservation checks. The last pre-release inventory found an active AI
response; activation must wait for the worker and reservations to clear.
