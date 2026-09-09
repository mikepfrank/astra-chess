# Hosted game replays

These standalone archives use the experiment's original vector pieces and replay
builder, with a move-synchronized conversation sidebar. They belong to the hosted
service and do not change the numbering of the earlier bot trials.

## Astra vs. Dr. Thanos — September 9, 2026

[Open the replay](astra-vs-dr-thanos-2026-09-09.html) ·
[Saved game record](astra-vs-dr-thanos-2026-09-09.json) ·
[PGN](astra-vs-dr-thanos-2026-09-09.pgn)

- Dr. Thanos played White; Astra (`gpt-6-astra`, `ultra`) played Black.
- Black won by checkmate, **27...Rd1#**, after 54 plies.
- The archive includes all **71 public messages** in the export snapshot,
  including the post-game discussion. Moving forward reveals messages through
  that position; moving backward retracts later messages. The final position
  includes the closing conversation.
- All **26 nonterminal Astra moves** have saved engine evaluations. The verified
  finish appears as Mate in 3, Mate in 2, Mate in 1, then the actual checkmate.
  Scores favor Astra. No new engine searches or model calls were used to create
  this archive.

The HTML embeds its board artwork, script, game data and conversation. It opens
offline and can be shared as one file. Generation does not publish it anywhere.
This particular game and its conversation were archived at Mike's request;
ordinary service records remain private and ignored by Git.

The JSON is a validated, portable snapshot of public game information. It omits
account identifiers, credentials, private model deliberation and raw query files.
Evaluation provenance retains hashes of the saved evidence. Those hashes are
useful for comparison with retained originals; they are not a substitute for
the original evidence or an independent proof of a chess evaluation.

To rebuild from the snapshot, run from `web-service` after installing the optional
`requirements-replay.txt` dependency:

```powershell
./.venv/Scripts/python.exe export_replay.py --from-record replays/astra-vs-dr-thanos-2026-09-09.json --output replays/astra-vs-dr-thanos-2026-09-09.html
```

The exporter validates the entire move sequence, SAN, FENs, captures and result,
as well as message ordering and saved evaluation structure. Archive regression
tests cover reconstruction, provenance, safe text embedding and read-only
database snapshots. Browser checks cover the mating sequence, cumulative chat
and its retraction, post-game messages, orientation and narrow-screen layout.

For this archive, 16 regression tests passed; one symlink test was skipped
because the Windows account cannot create symlinks. The existing hard-link
alias test passed. The generated page's JavaScript passed syntax checking;
browser playback, transport buttons and keyboard timeline navigation passed
with no browser errors.
