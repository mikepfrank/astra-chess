# Handoff to a new Astra session

Prepared September 9, 2026, from the surviving conversation context and the
repository at `125c669`. This is a dated orientation, not live game state.
Check the current checkout and journals before relying on its status snapshot.
Detailed specifications and historical evidence are linked rather than copied.

## Purpose and the latest direction from Mike

Michael P. Frank (Mike), a reversible-computing researcher and AI enthusiast,
is exploring how an LLM's deliberation can work with a small, understandable
chess engine. Astra proposes plans and questions, directs bounded searches,
inspects candidate positions and opponent counterplay, and chooses the move.
The engine supplies systematic tactical search and inspectable evidence.

The original experiment began with unaided play against Chess.com bots, added
explicit prospective board visualization, then introduced a from-scratch Python
engine. Mike watches the games and values the commentary explaining decisions
and concrete examples of where tooling helped or failed. He also shares the
replays publicly. The player/model label is **Astra**, while **Codex** names the
agent harness. Preserve historical PGN identities; presentation overrides and
thinking levels belong in replay metadata.

The conversation after the first Li game established these priorities:

- **Keep the engine relatively simple and understandable.** Mike explicitly
  declined pursuing a reconstruction of classical Stockfish. The discussion of
  Stockfish techniques was hypothetical, not an implementation request.
- Explore better questions, selective depth/time allocation, future-position
  searches, and focused goals. Stronger autonomous engine play is not the sole
  objective; the interaction between deliberation and search is the experiment.
- No external chess engines, opening books, endgame tablebases, game-database
  lookup for move selection, or large self-training exercise are part of this
  method. The engine uses rules and authored evaluation/search code. Astra's
  general chess knowledge comes from the language model; the whole combined
  system should not be described as having learned chess solely from the rules.
- Keep experimental evaluation terms and extensions optional, measure their
  cost, and explain proposed changes. The recent wins/draw did not require
  enabling every optional feature. Preserve engine behavior during a trial.
- Keep all substantive tools, notes, records and reusable artifacts in the repo,
  so continuity does not depend on this chat, a local memory service, or a
  particular desktop installation.

**Current request:** prepare this handoff for a separate development session.
Mike intends to explore spin-offs, potentially an interactive web service where
people can play against Astra, eventually on an AWS host or other Codex CLI
environment. That work should proceed separately from the original playing
session. No service architecture or deployment has been selected or implemented
as part of this handoff.

## Read the existing sources in this order

| Need | Source |
| --- | --- |
| Project instructions and artifact locations | [AGENTS.md](AGENTS.md) |
| Layout, archive list, replay build commands | [README.md](README.md) |
| Fresh checkout, dependencies, portability and checks | [SETUP.md](SETUP.md) |
| Engine requests, results, examples and live interface | [ENGINE.md](ENGINE.md) |
| Exact evaluation formulas, algorithms, goals and options | [Engine design reference](docs/engine-design.md) |
| Deliberative play, verification and compaction recovery | [Play skill](skills/astra-chess-play/SKILL.md) |
| Replay generation, historical scores and publishing conventions | [Archive skill](skills/astra-chess-archive/SKILL.md) |
| Current clock policy and its historical boundary | [TIME-CONTROL-NEXT.md](TIME-CONTROL-NEXT.md) |
| Equipment inventory and validation history | [REPRODUCIBILITY.md](REPRODUCIBILITY.md) |
| Source ZIP/history bundle and GitHub workflow | [PACKAGING.md](PACKAGING.md) |
| Earlier improvement rationale and measured changes | [Proposal](IMPROVEMENT-PROPOSAL.md), [v0.2 changes](ENGINE-CHANGES.md) |

Date-scoped reports retain their original test counts and conditions. Do not
read an old proposal's future tense as proof that a feature is still absent;
check the maintained references and actual implementation.

## Status at this handoff

The repository is on `main`, tracking `origin/main` at
[mikepfrank/astra-chess](https://github.com/mikepfrank/astra-chess).
Before this documentation task, the working tree was clean at `125c669`.

There have been **11 original-session games**, with **nine standalone replay
archives** for games 2 and 4–11. See the [game list](README.md#replay-collection)
and [early records](early-games/README.md) for details. Game 1 was a Sven loss
at High; games 2–3 used Extra High; games 4–11 used Ultra. Explicit prospective
visualization began with the successful Nelson rematch, game 4. Engine assistance
began in game 8: a Wally loss, followed by v0.2 wins against Wally as White and
Black (games 9–10), then the Li draw (game 11). Astra played Black only in game 10.
Mike rechecked Chess.com on September 9, 2026 and confirmed Sven's displayed
rating is **1100**, matching the saved records. Use 1100 for both Sven games
and disregard any conflicting rating mentioned earlier in the conversation.

The latest completed game is **Li (displayed bot rating 2000), Astra White,
1/2–1/2 after 70.Kxe6 by insufficient material**. Its directory is
[engine-games/li-v02-classical/](engine-games/li-v02-classical/).
The read-only recovery check during this task reported `phase: finished`,
139 verified plies, no pending move, no active clock turn, and no consistency
issues within the helper's limited scope. This was not a fresh browser observation.

Mike's intended next original-session trial is a rematch against Li as Black.
At this handoff no new journal has been initialized and no rematch started.
A development session should leave that game to the original playing session;
this orientation does not dispatch another agent to play it. If the session
sequence is unchanged, that next trial would be round 12. Recheck before assigning
any round/slug. Spin-off user games should have their own identifiers and records.

The current rules/search/evaluation fingerprint matches the last Li query:

```text
96e9ed243d69eede25b24c4c22248753053ee162b51fd0eb4cc081f47a311174
```

It covers `rules.py`, `search.py` and `diagnostics.py`, not the wrapper, clock,
UI or full repository. Li began at machinery commit `b613424`; the completed record
was committed in `8470369`, its scored replay in `f5855c7`, and subsequent
documentation in `bdfd048` and `125c669`. Engine rules/search/evaluation remained
unchanged through that game and the later discussion. Verify again before play.

## Lessons that matter more than another list of heuristics

The [Li assessment](engine-games/li-v02-classical/experiment.md) contains the
full examples and their query links. Several deserve carrying into the next
session's operating approach:

1. **Use future-position queries to investigate the opponent's obvious reply.**
   Before 44.Re7+, a query after the hypothetical `Rh7 Ke3` exposed that taking
   h4 would allow `Ra1#`. The interface worked well when deliberately asked that
   question. This was ordinary analysis, not an all-defenses goal proof.
2. **A plausible plan needs tactical support, especially when sacrificing.**
   At 62.Re6, Astra overrode the preference for Rd4 to pursue a concrete pawn
   advance, without separately investigating `Re6 Kxh4`. The next rooted search
   sharply reduced the estimate. A representative principal variation was
   insufficient coverage of the opponent's resources.
3. **A positive score is not demonstrated endgame progress.** Rook and two
   connected pawns against rook produced favorable heuristic scores, but no
   established promotion route. Ask what improves king access, blockade,
   exchanges, or a forcing line. Repeated favorable shuffles should prompt an
   investigation of the defense rather than an impatient sacrifice. We have
   not established that the earlier position was theoretically won.
4. **Keep hypothetical and actual boards separate.** Before 25.a4, fresh
   inspection caught an intended rook move carried over from a variation where
   Black's pawn had moved; on the actual board it could capture the rook.
5. **The engine can catch very elementary deliberative errors too.** The
   move-20 comparison rejected Qg7+, which would hang the queen. Tool usefulness
   includes these corrections as well as sophisticated combinations.

Earlier useful counterexamples include the first engine trial's
[bishop trap and search-horizon failures](engine-games/wally-2026-09-07/experiment-notes.md)
and game 9's [tactical discoveries and bounded mate proof](engine-games/wally-engine-v02/experiment-notes.md).
These are evidence for investigating the method, not a library to consult for
live move advice. Neither bot ratings nor this small, changing experimental
sample establish an Astra Elo, win probability, or isolated effect of a setting.

The agreed next emphasis is more disciplined use of existing tools. The above
lessons do not silently enable new search options or change evaluation weights.
During Li, diagnostics were enabled; optional mobility/restricted-piece/
king-exposure evaluation terms and threat extensions stayed off. Its 91 queries
were ordinary analysis, with no goal probes, and completed depths 4–9.
A requested depth ceiling is not achieved depth.

## Essential workflow and evidence boundaries

The [play skill](skills/astra-chess-play/SKILL.md) is the executable procedure.
In brief: observe the real position and turn time; record an initial candidate
and concern; search; inspect prospective boards and opponent checks/captures/
threats; ask targeted follow-ups; record a choice and concise assessment; submit;
observe acceptance; verify; then observe the actual reply. Record whether the
engine changed the initial idea and the concrete reason, including failures.

Analysis supports arbitrary FENs and hypothetical `after` moves. Restricting
`root_moves` narrows the queried side's choices while retaining opponent replies.
Goal probes distinguish bounded adversarial `forced` results from cooperative
witnesses and `unknown` outcomes. A witness is not a forced line; a timeout is
not a refutation; a safety goal holds only through its tested horizon. Preserve
real position history for repetition: FEN alone does not contain it. See the
[goal reference](docs/engine-design.md#goal-oriented-queries).

Query labels are descriptive text, not natural-language instructions interpreted
by the engine. Astra translates a question into the supported structured fields.

Normal candidate scores favor the **query root's side to move**. That can be
Black, including after a hypothetical continuation. They are heuristic
centipawns, distinct from mate distances, bounded proofs, and actual game results.
Archived scores are original pre-move searches for the actual chosen move,
displayed on its subsequent board; they are not newly computed position grades.
Missing evaluations stay missing. The exporter and archive skill define the
exact matching/perspective rules.

Original live games use the **embedded sidebar browser**, at Mike's request,
so they do not interfere with his desktop. Do not substitute the main desktop
browser merely because a different computer-use tool is available. Reacquire
the current supported browser API and inspect fresh state; old tab IDs, element
handles, coordinates, local preview ports, and screenshots are not active state.
Site hints, takebacks, external engine advice, and other agents choosing moves
are excluded. Independent agents can help develop tools and audit completed
records, as in this handoff, without providing live move advice.

Compaction recovery starts with these read-only commands from the checkout:

```text
python resume_chess.py
python resume_chess.py --game GAME-SLUG
```

Reconcile `game.json`, `clock.jsonl`, query evidence and any unresolved
`continuation.md` with the actual board before acting. `choose` records a pending
move; the journal helper does not control or inspect the browser. A promotion
selector or lost tool response can mean the move is partly entered or already
accepted. Never replay it blindly or invent a submission timestamp. This happened
in game 9; Mike completed the promotion and explicitly authorized a clock credit.
That exception does not authorize automatic refunds in later games.

New trials explicitly select `--time-control classical --own-time-only`:
90 minutes initially, +30 minutes after the 40th verified own move, +30 seconds
per verified own move. Ordinary/critical targets are 120/240 seconds, including
40 seconds for review and entry. The normal initial query is 15 seconds, depth
ceiling 8, three candidates, diagnostics on. Available balances and query caps
still apply. See [the clock policy](TIME-CONTROL-NEXT.md) rather than copying old
fixed-clock commands. Opponent time is excluded; deliberation, commentary,
queries, UI entry, retries and compaction count. Refunds or extra discretionary
time require explicit user authorization and preserved original events; the
selected preset's ordinary increments and stage credit accrue automatically.

Li used **109:56.720** of earned own time and retained **45:03.280**, with no
refund or overall overrun. Search itself consumed **23:07.817**; the rest includes
deliberation, commentary, UI work and interruptions, not separately measured.
This motivates better-directed questions and a tighter surrounding workflow,
as well as any measured engine optimization. See the [time audit](engine-games/li-v02-classical/time-audit.md).

## Parallel development and a future hosted version

**Separate sessions in the same folder share the same files.** A new session
does not isolate edits, default scratch state, test outputs, journal writes,
installed skill copies, or CPU contention. In particular, changing search code
while the original session plays can invalidate the frozen-version experiment.

Recommended working arrangement, to establish with the new development session:

- Use a separate Git worktree or clone and a development branch (`codex/` is the
  branch convention for new work). Pin the experimental playing checkout to its
  chosen engine revision. No worktree or branch was created for this handoff.
- Keep each game's journals, clocks, requests, outputs and UI ownership separate.
  Use distinct paths and ports. Do not run cleanup, generated-file rewrites,
  global skill installation, or branch switches against the playing checkout
  during a trial. Coordinate integration between games.
- Treat the current helpers as local tools, not a complete concurrent service.
  Query locks and atomic JSON writes do not make the entire journal transaction
  safe for multiple writers. Give each game a single state owner. Heavy local
  development/benchmarks can also affect wall-clock-limited search depth.

Useful integration entry points are already present:

| Component | What it provides |
| --- | --- |
| [astra_chess.py](astra_chess.py) | Validated JSON query boundary, arbitrary positions/history, analysis/probes, reports and clock attachment |
| [astra_engine/](astra_engine/) | Importable rules, evaluation/search, diagnostics, reporting and clocks; exact source map in ENGINE.md |
| [play_engine_game.py](play_engine_game.py) | Standard-start, either-color journal and manual choose/submit/verify lifecycle; paths rooted in its checkout |
| [resume_chess.py](resume_chess.py) | Read-only durable-state summary and engine-fingerprint comparison |
| [export_evaluations.py](export_evaluations.py), [build_replay.py](build_replay.py) | Historical score extraction and standalone archive generation |

The report HTML is an evidence viewer that exports follow-up JSON; it does not
run searches, and review notes must be downloaded to persist them. The loopback
`serve_replay.py` serves one static page. Neither supplies a live-game service.

The core is standard-library Python with no network requirement. It is not a
bundled LLM, model API client, UCI-engine service, or unattended browser player.
A public interactive version still needs its own authoritative game transport,
LLM orchestration, per-game isolation, scheduling/resource limits, and deployment
design. The file-oriented local CLI is a useful integration boundary; it is not
an HTTP endpoint to expose unchanged. Those are future engineering decisions.

To preserve this experiment's character, a hosted player should retain the
deliberative query/review/choice loop and evidence of why a move was selected.
Serving only the engine's highest-scoring move would test a different system.
Label the engine revision, model/reasoning configuration, assistance policy and
time policy for each trial so changes can be interpreted. For a service with its
own board, acknowledgment of accepted moves can replace browser observation;
that adaptation must be implemented and tested, not assumed already supported.

## Portability, local memory and exported assets

This handoff includes the relevant surviving conversational context, especially
the simplicity constraint and post-Li operating lessons. No complete transcript
was reconstructed. The actual games and recorded turn assessments remain the
evidence; compaction summaries cannot recover details that were never recorded.

A scoped audit during this task found:

- A keyword search of the available local memory registry
  (`~/.codex/memories/MEMORY.md`) for chess, Astra, Wally, Nelson, Li's slug and
  replays found no matching entries. No additional critical chess memory was
  identified there to export. This is not a claim that every global memory,
  transcript or other session directory has been exhaustively audited.
- Both installed chess skill directories match the versioned copies byte for
  byte, including `SKILL.md` and `agents/openai.yaml`. The canonical
  [skills/](skills/) tree is sufficient; new hosts can read it directly or install
  the complete directories using their own supported skill mechanism.
- The known external visualization asset, `wally-evaluation-history.html`, is
  identical to the tracked
  [visualization.html](engine-output/wally-v02-evaluation/visualization.html).
  Its dataset, build wrapper, preview and checks are also represented in the
  repository inventory. There is no sole external copy of that chart.

For provenance, the original checkout was
`C:/Users/MikeFrank/Documents/ChatGPT/Chess`, installed skills were under
`C:/Users/MikeFrank/.codex/skills`, and the audited visualization directory was
`C:/Users/MikeFrank/.codex/visualizations/2026/09/05/01a07293-7104-7f12-a4ae-26bfbebe674a`.
These paths locate the local audit; they are **not dependencies for a new host**.
Prefer the actual checkout and runtime paths. Do not transplant old process IDs,
monotonic clock state, browser handles, credentials, or ephemeral preview URLs.

[SETUP.md](SETUP.md) distinguishes the standard-library engine from optional
rules-only replay validation (`chess==1.11.2`), PNG rendering (Pillow), and browser
checks (Node/Playwright). These packages and the host's model/browser integration
are not bundled. The original full runtime checks used Windows and Edge;
AWS/Linux/headless interactive play has not been validated. Follow the setup
instructions and establish verification status on the destination environment.

All nine replay pages are standalone and offline, with inline SVG pieces.
Mike verified the eight pre-Li archives on iPhone. Preserve that fix instead of
reintroducing Unicode pawn glyphs with device-dependent emoji rendering. The separate historical chart
uses a pinned D3 CDN and is not fully offline. A replay's HTML is an archive,
not an interactive opponent or a backend. See the [archive skill](skills/astra-chess-archive/SKILL.md).

The separate analysis-report template still uses Unicode piece glyphs. The
replay's iPhone fix should not be assumed to cover that interface; inspect it
on the intended devices if reusing it for a spin-off.

The collection is [astra-plays-chess.netlify.app](https://astra-plays-chess.netlify.app/),
with each replay deployed separately as its project's root `index.html`. Mike
handles Netlify uploads. Existing deployment names are in [replays/index.html](replays/index.html);
`astra-vs-li` remains a proposed name until deployment is confirmed. GitHub pushes
do not redeploy those pages. No `LICENSE` file had been added at this snapshot;
see the current repository and Mike's subsequent decisions for reuse terms.

## Verification and keeping this handoff useful

The last full Python run at the Li archive checkpoint passed **168 tests**, and
four offline replay browser suites passed with Edge. The subsequent documentation
task reran the Li browser suite and reproduced its HTML byte for byte. These are
recorded results, not a claim that this handoff task reran every test or that the
same checks already pass on another OS. Commands are in [SETUP.md](SETUP.md).

Preserve `.gitattributes`: source and evidence fingerprints depend on exact
bytes, and earlier packaging exposed a real line-ending/hash failure. Retain
saved query hashes instead of rewriting them to fit altered files. Temporary
outputs/dependencies stay ignored; only `scratch/README.md` is tracked under
scratch. Promote substantive evidence into the appropriate permanent directory.

Commit authored tools and notes at completion checkpoints. Portable packages
come from a clean committed tree via `package_repo.py`; old packages do not
automatically acquire later changes. The existing
[fresh-source validation](PACKAGING-VALIDATION.md) describes its own historical
checkpoint, not a current AWS deployment test.

For future handoffs, update the snapshot date, current work/ownership, engine
revision, latest experiment and open questions. Keep detailed live recovery
facts beside the game's journal and link them here. New source/state and Mike's
current instructions take precedence over this dated orientation.
