# Paused at the own-time budget, not a completed game

User authorized this game as Black. An asynchronous question is pending:
finish with a recorded overrun, or pause at one hour. No extension has yet
been received. Do not resume play without that answer or equivalent permission.

Last fresh browser observation: `2026-09-08T01:39:41.674Z`, after White's
`45. Kf2`. Verified journal has 89 plies, Black to move, no pending move.
FEN: `2r3k1/1p4pp/4b3/P2n4/7P/6P1/3B1K2/2r5 b - - 4 45`.
Black: Kg8, Rc8/Rc1, Be6, Nd5, pawns b7/g7/h7.
White: Kf2, Bd2, pawns a5/g3/h4.
Initial candidate recorded for move 45 is c1d1, but no choice or submission
has been made. Reconsider it after recovery rather than treating it as an order.

Own clock was checked at 3648.149 seconds (48.149 seconds over). Play was then
paused. Conservative preserved status at `2026-09-08T01:41:35.130231+00:00`
was 3690.855 seconds (61:30.855), including reporting/reconciliation overhead.
The current ledger has no pause operation: its active-ply counter continues
to grow during unattended waiting. Do not report that later raw total as
continued deliberation or reset/refund it silently. Preserve this explicit
pause boundary and resolve resumption/extension accounting with the user's
answer. No credit or refund has been applied.

Browser: embedded Codex tab only. Reacquire via cua.getState/getTab and inspect
fresh state. In this runtime, tab.playwright DOM snapshots/evaluate/locators
worked; tab.cua.click and direct tab.click coordinate attempts did not.
Board is flipped for Black. Visible DOM piece classes encode file/rank, e.g.
piece br square-38 is rook c8. Moves were entered by clicking the observed
piece, then an observed legal-move dot (.hint.square-XY) or opposing piece.
Never invoke site Show Hint, analysis/evaluation, takeback, or external engine.

Engine remains unchanged v0.2, fingerprint
`96e9ed243d69eede25b24c4c22248753053ee162b51fd0eb4cc081f47a311174`.
All search requests/results are saved. Last completed search is move 41;
move 42 query was rejected for move-entry reserve. Moves 42-44 used direct
board review, with no new score. Do not relabel earlier scores as current.

Lessons to revisit after play: minimum 12 expected remaining turns combined
with a fixed 40-second reserve makes search unavailable late in a long game,
even with minutes left in the total clock. Conversion was also too slow and
my own deliberation too verbose. No algorithm/allocator changes were made
during this trial. Do not change frozen search/evaluation while resuming it.
