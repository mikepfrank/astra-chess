# Saving and publishing game replays

Every finished game, including games completed before this feature was added,
has a **Save/share replay** button. Signing into a protected account in another browser
restores access through **Your games**. Guest access follows the existing browser
session; knowing a player's name or game URL does not grant ownership.

## Player controls

1. Open a finished game and choose **Save/share replay**.
2. Choose **Moves only** or **With chat**. These are two separately saved versions
   of the same game, each with its own download and optional shared link. The
   dialog starts with Moves only. With chat includes the entire public
   conversation captured at generation time, including post-game discussion;
   it never includes private model reasoning or tools.
3. Choose **Generate replay**. The dialog shows construction progress and
   reports when the standalone HTML is ready.
4. **Download HTML** saves a file that works offline. **Share** creates a link
   to the same standalone replay. Leave **Also publish to public game list**
   unchecked for an unlisted link, or check it to add the replay to `/games/`.
   Downloading and sharing are independent: use either or both, in any order.
5. Copy the link or open the shared replay from this same dialog. An unlisted
   replay is accessible to anyone with its link, but absent from the public list.
6. **Remove from public list** makes a listed replay unlisted while keeping its
   link usable. **Disable shared link** removes both access through that link
   and any listing. Both act only on the selected version and retain its private
   download and the original game.
7. **Delete this version** removes the selected version's saved download, shared
   link and listing after confirmation. It preserves the other version, original
   game and conversation. To remove both versions, select and delete each one.
   Previously downloaded copies remain outside the service's control.

Generating one version never replaces the other. For example, keep With chat
private for your own download and share Moves only with friends or publicly.
Both remain saved across reloads and sign-ins until explicitly updated or deleted.

Updating a version captures newer discussion and changes that version's private
archive only. Sharing the updated snapshot is another explicit action; the dialog
distinguishes it from an older shared copy of the same version. Sharing an update
replaces only that version's old link. Changing its listing choice preserves
the link. Each version's checkbox reflects its own existing listing; new shares
default to unlisted.

The public list contains at most one entry per game. If both versions are
explicitly listed, With chat takes precedence. Removing or unlisting it reveals
Moves only if that version is still listed. A private or unlisted chat version
never overrides a listed Moves only version. Both explicitly shared URLs remain
usable even when only one appears in the list.

Links created with the earlier separate **Share link** button keep working and
are never silently added to the public list. Owners can open, copy or disable
an **Earlier share link** inside the unified dialog. Generating or sharing a
standalone replay does not revoke an earlier link automatically.

## Preserved first-human-game workflow

The original September 9 human replay and its sanitized source remain in
[`replays/`](../replays/README.md). The same machinery builds new user archives:

| Resource | Purpose |
| --- | --- |
| [`astra_web/replay_archive.py`](../astra_web/replay_archive.py) | Validate saved moves, SAN, FENs, result, message chronology and historical evaluations; build standalone HTML. |
| [`templates/replay.template.html`](../templates/replay.template.html) | Animated chessboard, controls, PGN download, evaluations and move-synchronized conversation. |
| [`build_replay.py`](../../build_replay.py) | Shared original experiment renderer and rules/notation checks. |
| [`export_replay.py`](../export_replay.py) | Offline command-line export and rebuild from sanitized records. |
| [`astra_web/replay_library.py`](../astra_web/replay_library.py) | Owner-only construction/download, listed or unlisted shared snapshots and public list. |
| [`prompts/player.md`](../prompts/player.md) | Guidance included in deployed Astra sessions so they can explain replay controls. |

Forward navigation reveals chat committed through the selected board position;
backward navigation retracts later messages. The final position includes the
captured post-game conversation. Scores come from the original saved searches
for Astra's chosen moves; unavailable evidence stays missing. The builder never
runs new chess analysis, invokes Codex, consumes the model's game allowance or
modifies the board or chess clock.

The repository and template remain readable to the host service in its systemd
filesystem view. Player instances learn the procedure through their instructions;
the feature does not give the model a filesystem, publishing or shell tool.

## Hosting and persistence

`/games/` is the public user-game index. Its entries are derived from explicitly
published snapshots, and the service maintains a generated
`public-replays/index.html` under `ASTRA_DATA_DIR`. This file is an output, not
an operator-edited source of truth. Back up the private SQLite database together
with `replay-archives/` and `public-replays/` under `ASTRA_DATA_DIR`: SQLite owns
archive/publication metadata, and the HTML snapshots reside in these directories.
Never expose the entire data directory via the reverse proxy or a static-files mount.

The `replay_versions` and `replay_variant_shares` tables store private downloads
and shared snapshots, keyed by game and chat-inclusion choice. On upgrade, the
old `replay_archives`, `replay_publications` and `replay_unlisted` rows migrate
once, preserving saved IDs, shared tokens, HTML contents and listing choices.
If an old shared snapshot has a different chat choice from the old private
download, both become saved versions. Migrated old metadata is retired so it
cannot resurrect a removed link on another startup. A rollback to an older
release makes standalone links unavailable until this release is restored;
it must not republish retired links. Back up the database and replay directories
before upgrading, and prefer a forward fix after the new version accepts writes.
If an older release accepts new replay changes after rollback, returning to this
release refuses startup until those retired-table records are reconciled. It
does not silently import them or risk restoring links the owner removed.
The legacy `shares` table remains available for previously issued `/replay/` links.

Owner routes under `/api/games/{id}/archive` provide status, construction and
download. `GET ?variant=moves|chat` selects a version and also reports both
versions' status. An unscoped HTTP read is rejected when both versions exist,
so an older browser tab cannot silently switch from moves-only to chat. The
player is prompted to reload and choose a version. Construction still takes an explicit `include_commentary`
boolean. `POST /share` accepts an `archive_id` and optional `listed` boolean,
defaulting to false; that ID identifies the version being shared. `DELETE
/listing?variant=...` removes only that version's listing; `DELETE
/publication?variant=...` disables its standalone link. `DELETE
?variant=...` removes its saved version and sharing. Ambiguous unscoped deletion
is rejected rather than affecting both versions. The older `POST /publish`
continues to explicitly list the selected archive. Owner status also reports any legacy share link, which
can be disabled with the existing `DELETE /api/games/{id}/share` route. Unlisted
HTML responses also ask search engines not to index them; possession of the link
still grants access.

`/experiments/` mirrors the ten already-public experiment replays, including the
first hosted human game, using an explicit list of tracked HTML files. Its links
stay on this domain; the original repository index and Netlify deployments are
preserved. The bottom of the new public game list links to this collection.

Archive requests require the game owner and the existing Origin/CSRF checks.
Public readers receive only opted-in snapshots. Private records, account data,
query files and model transcripts are never served by the archive routes.
Generated HTML safely embeds player text as data. A dedicated content-security
policy allows the trusted embedded script by hash, without permitting arbitrary
inline scripts. Public pages are not cached so removal takes effect immediately.

Construction runs in a bounded background queue separate from the Astra worker.
An interrupted construction is reported as retryable after restart; a previously
ready download remains available during a refresh and after a failed refresh.
The `replay_variant_jobs` table tracks pending builds independently of saved versions. An update
must still wait for active chess responses to finish before restarting the
application. Existing archive tables are added without rewriting game records.

## Offline operator reconstruction

From `web-service`, using the application's virtual environment:

```sh
.venv/bin/python export_replay.py --game GAME_ID --data-dir /path/to/private/data --output /path/to/private/replay.html --omit-commentary
.venv/bin/python export_replay.py --from-record /path/to/private/replay.json --output /path/to/private/rebuilt.html
```

Omit `--omit-commentary` only when including the saved conversation is intended.
The first command writes a sanitized companion JSON by default. Use distinct
source and output paths. Neither command publishes anything; public listing is
an owner-controlled web action. Generated private exports and user publications
belong in runtime storage, not in the public source repository.

## Validation checkpoint — September 10, 2026

The Windows service suite passed 180 tests with two platform-related symlink
skips. The new coverage includes 14 archive-library tests, five historical-route
tests and CLI chat omission. Full HTTP/browser checks against an isolated local
fixture passed both chat choices, actual downloads before/after publication and
removal, immutable public versions, revoked URLs, reload, offline playback,
chat advancement/retraction, escaped hostile text, script-hash CSP, and desktop
and narrow layouts. The original human replay and Li draw also played through
their new routes; all ten historical links resolved.

A private temporary reconstruction of the operator's completed September 10
game on Lightsail succeeded with the existing `chess==1.11.2` installation:
33 plies and 45 messages, approximately 0.35 seconds. That check ran no model
request and did not publish the game. The Linux suite subsequently passed all
180 tests with three platform-related skips. The feature is live on Lightsail;
the [deployment checkpoint](LIGHTSAIL-DEPLOYMENT.md#standalone-replay-library--september-10-2026)
records the applied revision, public-browser verification and preserved games.

## Unified sharing follow-up — September 10, 2026

The two top-level replay controls are now one **Save/share replay** dialog.
The Windows suite passed 186 tests (two platform-related skips), including
20 archive-library tests. Browser checks against a disposable game verified
the single entry point, default unlisted sharing, explicit public listing,
independent downloads, same-URL listing changes, revocation, both chat choices,
reload, offline playback, synchronized conversation, CSP and desktop/mobile
layouts. A separate browser check verified that an older shared snapshot can
be relisted without exposing a newer private conversation, and that disabling
standalone and legacy links is independent. No model requests or live game
mutations were used for these checks.

The Linux suite also passed all 186 tests (three platform-related skips) from
a separate staged checkout. Revision `5cb1a2d` was deployed at 22:57 UTC;
read-only HTTPS browser checks confirmed the single entry point and public
library. All 14 saved games, clock records, usage rows, existing replay metadata
and HTML files were preserved. See the [deployment checkpoint](LIGHTSAIL-DEPLOYMENT.md#unified-replay-sharing--september-10-2026).
