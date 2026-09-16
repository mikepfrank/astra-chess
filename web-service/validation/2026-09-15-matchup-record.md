# September 15: account-scoped head-to-head record

The operator requested a visible cumulative score against the AI and the same
record in the AI's context after noticing that post-game conversation did not
recognize a previous matchup. Implementation and local validation are complete;
exact-commit Linux validation and live activation are still pending below.

## Scope and identity

The score derives from existing completed games for the same immutable human
account ID, saved AI persona name and canonical model. Reasoning level, model
profile version and persona text revisions do not reset this record. Separate
accounts with the same display name are never merged. Different AI personas or
underlying models have separate records. Guest accounts receive only their own
cookie-account totals; adding a password preserves their existing account ID.

Count a win as one point, a draw as half a point and a loss as zero. Only finished
games with recognized results count, irrespective of color. Active and suspended
games are excluded. A completed current game is included once. Aggregation reads
the games table rather than event counts, so retries and repeated chat do not
duplicate results. No schema migration or game-record backfill is necessary.

The board displays compact head-to-head points near its title. The owned game
API and the AI's fresh status use the same aggregate. Model context identifies
these as server-recorded totals, not access to earlier game moves or chats.
Existing saved prompts/profiles/thread identities and password/opt-in memory
rules remain intact. The record is not added to public replay snapshots.

## Historical initialization

A read-only scan found 20 games at the start of implementation. The operator's
account had two completed Arcturus losses, one as each color, plus a new active
game. The completed games have profile versions 2 and 4 but the same persona
and canonical model, so the starting matchup score is human 0, Arcturus 2.
These are dated observations; deployed totals are recalculated from current
saved records rather than frozen from this scan.

## Local validation

- Eleven matchup backend tests passed: results and colors, historical/profile
  identity, owner isolation, legacy identity, retries, current-snapshot
  consistency, fresh totals from other games, owned API authorization, public
  replay exclusion, and initial/status/accepted-action model context delivery.
- The intercepted matchup browser check and existing move-thinking browser
  check passed without any real account or model requests. Desktop and mobile
  screenshots show one compact score line beneath the board heading. The check
  also covers account/game switching, missing data, logout, orientation and
  completed-game updates.
- Independent source review found no correctness or privacy blocker. Each
  aggregate reads the account's saved game documents; consider a lighter
  projection only if account histories become large enough to justify it.

## Activation

Pending exact-commit Linux receipts and an idle, gated Arcturus deployment.
