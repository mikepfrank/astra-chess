"""Small, inspectable chess search written from scratch with the standard library.

There are two intentionally separate questions here:

* ``analyze`` ranks moves by bounded, adversarial alpha-beta search with a simple
  handwritten evaluation. Its reported top-N scores are exact *for the completed
  search horizon*, not chess-theoretic values. Quiescence searches captures,
  promotions, and every check evasion. No database, learned weights, engine,
  opening book, tablebase, or external service is used.
* ``probe`` checks one explicit goal with bounded AND/OR search, without material
  pruning. A cooperative witness is not a proof against a defending opponent.

``history`` contains hashable ``Position.repetition_key()`` values BEFORE the
supplied position, excluding that position. FEN alone cannot establish earlier
repetitions. Fifty-move and threefold claims are optional choices, including a
claim by declaring an intended legal move; 75-move and fivefold draws end play.
Mate takes precedence. Insufficient material uses the conservative rules module
test; this is not a solver for every possible FIDE dead position.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
import math
import time
from typing import Any

from .rules import BLACK, WHITE, Move, Position, color_of, parse_square, square_name

MATE = 30000
MATE_THRESHOLD = 29000
INF = 32000
VALUES = {"p": 100, "n": 320, "b": 335, "r": 500, "q": 900, "k": 0}
_SIDE_NAMES = {WHITE: "white", BLACK: "black"}
_GOAL_TYPES = frozenset(("capture", "avoid_capture", "castle", "check", "avoid_check",
                         "checkmate", "avoid_checkmate", "stalemate", "avoid_stalemate"))


class _Stopped(Exception):
    def __init__(self, reason: str = "time_limit") -> None:
        self.reason = reason


@dataclass(frozen=True)
class _Value:
    score: int
    pv: tuple[Move, ...] = ()
    ending: str | None = None
    claim_move: str | None = None


@dataclass(frozen=True)
class _Witness:
    moves: tuple[Move, ...] = ()
    ending: str = "goal_reached"
    claim_move: str | None = None
    evidence: str = "cooperative_witness"


def _limits(max_depth: int, time_limit: float, count: int) -> tuple[int, float, int]:
    if isinstance(max_depth, bool) or not isinstance(max_depth, int) or not 1 <= max_depth <= 12:
        raise ValueError("max_depth must be an integer from 1 to 12 plies")
    if isinstance(time_limit, bool) or not isinstance(time_limit, (int, float)):
        raise ValueError("time_limit must be a finite positive number of seconds")
    seconds = float(time_limit)
    if not math.isfinite(seconds) or not 0 < seconds <= 120:
        raise ValueError("time_limit must be greater than zero and at most 120 seconds")
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 20:
        raise ValueError("multipv/max_lines must be an integer from 1 to 20")
    return max_depth, seconds, count


def _counts(position: Position, history: Any) -> Counter:
    if isinstance(history, (str, bytes, dict)):
        raise ValueError("history must contain repetition keys, not FEN strings or mappings")
    try:
        counts = Counter(() if history is None else history)
    except (TypeError, ValueError) as exc:
        raise ValueError("history must be an iterable of hashable repetition keys") from exc
    counts[position.repetition_key()] += 1
    return counts


def _terminal(position: Position, legal: list[Move], counts: Counter) -> dict | None:
    if not legal:
        if position.in_check():
            winner = 1 - position.turn
            return {"reason": "checkmate", "winner": _SIDE_NAMES[winner],
                    "result": "1-0" if winner == WHITE else "0-1"}
        return {"reason": "stalemate", "winner": None, "result": "1/2-1/2"}
    if position.insufficient_material():
        reason = "insufficient_material"
    elif position.halfmove >= 150:
        reason = "seventy_five_moves"
    elif counts[position.repetition_key()] >= 5:
        reason = "fivefold_repetition"
    else:
        return None
    return {"reason": reason, "winner": None, "result": "1/2-1/2"}


def _claim_reasons(position: Position, counts: Counter) -> list[str]:
    reasons = []
    if position.halfmove >= 100:
        reasons.append("fifty_moves")
    if counts[position.repetition_key()] >= 3:
        reasons.append("threefold_repetition")
    return reasons


def _prospective_claim(child: Position, counts: Counter) -> bool:
    """The child has not yet been added to counts. A declaration is optional."""
    return child.halfmove >= 100 or counts[child.repetition_key()] >= 2


def _claim_candidates(position: Position, legal: list[Move], counts: Counter) -> list[Move]:
    """All legal declarations, including quiet moves at a quiescent frontier."""
    if position.halfmove < 99 and not any(count >= 2 for count in counts.values()):
        return []
    return [move for move in legal if _prospective_claim(position.play(move), counts)]


def evaluate(position: Position) -> int:
    """Simple geometry/material evaluation in centipawns, side to move's view.

    Formulae, rather than imported piece-square tables: centralization, pawn
    advancement/structure, rook files, a bishop pair, and phase-dependent king
    placement. Scores are deliberately modest and fully inspectable.
    """
    board = position.board
    pawn_files = [[0] * 8, [0] * 8]
    pawn_squares: list[list[int]] = [[], []]
    bishops = [0, 0]
    kings = [board.index("K"), board.index("k")]
    non_pawn_material = 0
    for square, piece in enumerate(board):
        if piece == ".":
            continue
        side = color_of(piece)
        kind = piece.lower()
        if kind == "p":
            pawn_files[side][square % 8] += 1
            pawn_squares[side].append(square)
        elif kind != "k":
            non_pawn_material += VALUES[kind]
        if kind == "b":
            bishops[side] += 1
    endgame = max(0.0, min(1.0, (4400 - non_pawn_material) / 4400))
    score = 0.0
    for square, piece in enumerate(board):
        if piece == ".":
            continue
        side = color_of(piece)
        kind = piece.lower()
        file, rank = square % 8, square // 8
        advance = rank if side == WHITE else 7 - rank
        center = 7 - abs(file - 3.5) - abs(rank - 3.5)
        value = float(VALUES[kind])
        if kind == "p":
            value += 5 * max(0, advance - 1) + 2 * center
            if pawn_files[side][file] > 1:
                value -= 11
            if not ((file and pawn_files[side][file - 1])
                    or (file < 7 and pawn_files[side][file + 1])):
                value -= 9
            passed = not any(abs(other % 8 - file) <= 1
                             and (other // 8 > rank if side == WHITE else other // 8 < rank)
                             for other in pawn_squares[1 - side])
            if passed:
                value += (5 + 4 * endgame) * max(0, advance - 1) ** 2
                next_square = square + (8 if side == WHITE else -8)
                if 0 <= next_square < 64 and board[next_square] != ".":
                    value -= 12 + 4 * advance
        elif kind == "n":
            value += 11 * center - 25
            if advance == 0:
                value -= 8
        elif kind == "b":
            value += 5 * center - 10
            if advance == 0:
                value -= 6
        elif kind == "r":
            if not pawn_files[side][file]:
                value += 13 if pawn_files[1 - side][file] else 22
            if advance == 6:
                value += 18
        elif kind == "q":
            value += 2 * center
        else:
            end_value = 13 * center
            shield_rank = rank + (1 if side == WHITE else -1)
            own_pawn = "P" if side == WHITE else "p"
            shield = sum(board[shield_rank * 8 + f] == own_pawn
                         for f in range(max(0, file - 1), min(7, file + 1) + 1)) \
                if 0 <= shield_rank < 8 else 0
            middle_value = 13 * shield - 8 * center
            if advance == 0 and file in (2, 6):
                middle_value += 24
            value += endgame * end_value + (1 - endgame) * middle_value
        score += value if side == WHITE else -value
    score += 28 * (bishops[WHITE] >= 2) - 28 * (bishops[BLACK] >= 2)
    # The stronger side gets a small incentive to approach in sparse endings.
    if endgame > 0.75 and abs(score) > 200:
        distance = max(abs(kings[0] % 8 - kings[1] % 8),
                       abs(kings[0] // 8 - kings[1] // 8))
        score += (7 - distance) * (3 if score > 0 else -3)
    return int(round(score if position.turn == WHITE else -score))


def _is_capture(position: Position, move: Move) -> bool:
    return (position.board[move.to_sq] != "."
            or (position.board[move.from_sq].lower() == "p"
                and move.to_sq == position.ep_square
                and move.from_sq % 8 != move.to_sq % 8))


def _order(position: Position, moves: list[Move], preferred: Move | None = None,
           killers: tuple[Move, ...] = (), history_scores: dict | None = None) -> list[Move]:
    def priority(move: Move) -> tuple[int, str]:
        attacker = position.board[move.from_sq].lower()
        victim = position.board[move.to_sq].lower()
        value = 0
        if move == preferred:
            value += 1000000
        if _is_capture(position, move):
            value += 100000 + 16 * VALUES.get(victim, 100) - VALUES[attacker]
        if move.promotion:
            value += 80000 + VALUES[move.promotion]
        if move in killers:
            value += 50000 - 1000 * killers.index(move)
        if history_scores:
            value += min(40000, history_scores.get((position.turn, move), 0))
        if attacker == "k" and abs(move.to_sq - move.from_sq) == 2:
            value += 300
        destination_center = 7 - abs(move.to_sq % 8 - 3.5) - abs(move.to_sq // 8 - 3.5)
        value += int(destination_center * 4)
        return (-value, move.uci())
    return sorted(moves, key=priority)


class _Search:
    def __init__(self, deadline: float, counts: Counter) -> None:
        self.deadline = deadline
        self.counts = counts
        self.nodes = 0
        self.qnodes = 0
        self.cutoffs = 0
        # Only moves, never scores, are reused across transpositions. This avoids
        # incorrect TT values when the same board has different draw histories.
        self.preferred: dict[Any, Move] = {}
        self.killers: dict[int, tuple[Move, ...]] = {}
        self.history_scores: dict[tuple[int, Move], int] = {}

    def check(self) -> None:
        if time.monotonic() >= self.deadline:
            raise _Stopped()

    def visit(self) -> None:
        self.check()
        self.nodes += 1

    def child(self, position: Position, move: Move, depth: int, alpha: int,
              beta: int, ply: int, qdepth: int | None = None) -> _Value:
        child = position.play(move)
        intended_claim = _prospective_claim(child, self.counts)
        key = child.repetition_key()
        self.counts[key] += 1
        try:
            answer = (self.negamax(child, depth, -beta, -alpha, ply + 1)
                      if qdepth is None
                      else self.quiescence(child, -beta, -alpha, ply + 1, qdepth + 1))
        finally:
            self.counts[key] -= 1
            if not self.counts[key]:
                del self.counts[key]
        score = -answer.score
        if intended_claim and score < 0:
            # FIDE's intended-move declaration ends the game BEFORE the move is
            # executed. Keep the declaration out of the played PV and FEN list.
            return _Value(0, (), "intended_move_draw_claim", move.uci())
        return _Value(score, (move,) + answer.pv, answer.ending, answer.claim_move)

    def negamax(self, position: Position, depth: int, alpha: int, beta: int, ply: int) -> _Value:
        if depth <= 0:
            return self.quiescence(position, alpha, beta, ply, 0)
        self.visit()
        legal = position.legal_moves()
        terminal = _terminal(position, legal, self.counts)
        if terminal:
            return _Value(-MATE + ply if terminal["reason"] == "checkmate" else 0,
                          ending=terminal["reason"])
        claimable = bool(_claim_reasons(position, self.counts))
        best = _Value(0, ending="draw_claim") if claimable else _Value(-INF)
        if best.score >= beta:
            return best
        alpha = max(alpha, best.score)
        key = position.repetition_key()
        moves = _order(position, legal, self.preferred.get(key),
                       self.killers.get(ply, ()), self.history_scores)
        best_move = None
        for move in moves:
            answer = self.child(position, move, depth - 1, alpha, beta, ply)
            if answer.score > best.score:
                best, best_move = answer, move
            alpha = max(alpha, answer.score)
            if alpha >= beta:
                self.cutoffs += 1
                if not _is_capture(position, move) and not move.promotion:
                    self.killers[ply] = (move,) + tuple(m for m in self.killers.get(ply, ())
                                                       if m != move)[:1]
                    hkey = (position.turn, move)
                    self.history_scores[hkey] = self.history_scores.get(hkey, 0) + depth * depth
                break
        if best_move is not None:
            self.preferred[key] = best_move
        return best

    def quiescence(self, position: Position, alpha: int, beta: int, ply: int, qdepth: int) -> _Value:
        self.visit()
        self.qnodes += 1
        # Even at the cap, determine mate/stalemate before evaluating material.
        legal = position.legal_moves()
        terminal = _terminal(position, legal, self.counts)
        if terminal:
            return _Value(-MATE + ply if terminal["reason"] == "checkmate" else 0,
                          ending=terminal["reason"])
        checked = position.in_check()
        if checked and ply >= 96:
            # Never substitute stand-pat for a compulsory check evasion. Abandon
            # this iteration and retain the last completed one in this rare case.
            raise _Stopped("check_extension_limit")
        claimable = bool(_claim_reasons(position, self.counts))
        best = _Value(0, ending="draw_claim") if claimable else _Value(-INF)
        if not claimable:
            declarations = _claim_candidates(position, legal, self.counts)
            if declarations:
                best = _Value(0, ending="intended_move_draw_claim", claim_move=declarations[0].uci())
        if not checked:
            stand = evaluate(position)
            if stand > best.score:
                best = _Value(stand)
            if qdepth >= 8:
                return best
        if best.score >= beta:
            return best
        alpha = max(alpha, best.score)
        tactical = legal if checked else [m for m in legal if m.promotion or _is_capture(position, m)]
        for move in _order(position, tactical):
            answer = self.child(position, move, 0, alpha, beta, ply, qdepth=qdepth)
            if answer.score > best.score:
                best = answer
            alpha = max(alpha, answer.score)
            if alpha >= beta:
                self.cutoffs += 1
                break
        return best


def _line(position: Position, moves: tuple[Move, ...], ending: str | None = None,
          claim_move: str | None = None) -> dict:
    san, uci, fens = [], [], [position.fen()]
    for move in moves:
        legal = position.legal_moves()
        if move not in legal:
            raise AssertionError(f"Search emitted illegal PV move {move.uci()}")
        san.append(position.san(move, legal_moves=legal))
        uci.append(move.uci())
        position = position.play(move)
        fens.append(position.fen())
    return {"uci": uci, "san": san, "fens": fens, "ending": ending,
            "claim_by_intended_move": claim_move}


def _mate_plies(score: int | None) -> int | None:
    if score is None or abs(score) < MATE_THRESHOLD:
        return None
    distance = MATE - abs(score)
    return distance if score > 0 else -distance


def analyze(position: Position, max_depth: int = 5, time_limit: float = 3.0,
            multipv: int = 3, root_moves: Any = None, history: Any = None) -> dict:
    """Rank legal root moves; preserve only fully completed top-N iterations.

    ``root_moves`` optionally restricts the root to legal UCI strings/Move values.
    Internal nodes always consider every legal reply. Scores are from the root
    player's view. ``mate_in_plies`` is signed and is not a full-move count.
    A depth-zero fallback has ``score_cp=None`` and is explicitly unevaluated.
    """
    started = time.monotonic()
    max_depth, seconds, multipv = _limits(max_depth, time_limit, multipv)
    if not isinstance(position, Position):
        raise ValueError("position must be a Position")
    counts = _counts(position, history)
    reserve = min(0.5, seconds * 0.08)
    search = _Search(started + seconds - reserve, counts)
    legal = position.legal_moves()
    all_legal = legal
    if root_moves is not None:
        if isinstance(root_moves, (str, bytes, dict)):
            raise ValueError("root_moves must be a nonempty iterable of UCI strings or Moves")
        by_uci = {move.uci(): move for move in legal}
        selected = []
        for value in root_moves:
            move = by_uci.get(value) if isinstance(value, str) else value
            if not isinstance(move, Move) or move not in legal:
                raise ValueError(f"Illegal root move: {value!r}")
            if move not in selected:
                selected.append(move)
        if not selected:
            raise ValueError("root_moves must not be empty")
        legal = selected
    terminal = _terminal(position, all_legal, counts)
    claim_reasons = [] if terminal else _claim_reasons(position, counts)
    declarations = [] if terminal else _claim_candidates(position, legal, counts)
    output = {"kind": "analysis", "start_fen": position.fen(),
              "turn": _SIDE_NAMES[position.turn], "requested_depth": max_depth,
              "completed_depth": 0, "nodes": 0, "elapsed_seconds": 0.0,
              "time_limit_seconds": seconds, "timed_out": False, "fallback": False,
              "candidates": [], "terminal": terminal,
              "draw_claim_available": bool(claim_reasons or declarations),
              "current_draw_claim_available": bool(claim_reasons),
              "draw_claim_reasons": claim_reasons,
              "draw_claim_by_intended_moves": [move.uci() for move in declarations],
              "intended_move": None,
              "root_score_cp": None, "recommended_action": "game_over" if terminal else "move",
              "history_supplied": history is not None,
              "diagnostics": {"score_view": "root side", "depth_unit": "plies",
                              "history_note": "Earlier repetition is unknown without supplied history.",
                              "quiescence_capture_depth": 8,
                              "score_scope": "Completed bounded search with heuristic evaluation; not an exact game value.",
                              "transposition_reuse": "move ordering only; no cached evaluation bounds",
                              "dead_positions": "Conservative insufficient-material recognition, not an exhaustive dead-position solver.",
                              "stop_reason": "terminal" if terminal else None}}
    if terminal:
        output["root_score_cp"] = -MATE if terminal["reason"] == "checkmate" else 0
        output["elapsed_seconds"] = round(time.monotonic() - started, 6)
        return output
    ordered = _order(position, legal)
    completed: list[tuple[Move, _Value]] = []
    stop_reason = "depth_limit"
    for depth in range(1, max_depth + 1):
        iteration: list[tuple[Move, _Value]] = []
        try:
            search.check()
            for move in ordered:
                search.check()
                # Once top-N is full, fail-low roots can only rank below its
                # weakest member. They are excluded, never reported as exact.
                threshold = iteration[-1][1].score if len(iteration) >= multipv else -INF
                answer = search.child(position, move, depth - 1, threshold, INF, 0)
                if len(iteration) < multipv or answer.score > threshold:
                    iteration.append((move, answer))
                    iteration.sort(key=lambda item: (-item[1].score, item[0].uci()))
                    iteration = iteration[:multipv]
            # Completion requires examining every permitted root move. A partial
            # next iteration never overwrites these scores or candidates.
            completed = iteration
            output["completed_depth"] = depth
            preferred = [move for move, _ in completed]
            ordered = preferred + [move for move in ordered if move not in preferred]
        except _Stopped as stopped:
            stop_reason = stopped.reason
            output["timed_out"] = stopped.reason == "time_limit"
            break
    if not completed:
        output["fallback"] = True
        fallback = _line(position, (ordered[0],), "unevaluated_legal_fallback")
        fallback.update(rank=1, root_move=ordered[0].uci(), score_cp=None, mate_in_plies=None, depth=0,
                        score_is_exact_for_search=False)
        output["candidates"] = [fallback]
    else:
        for rank, (move, value) in enumerate(completed, 1):
            candidate = _line(position, value.pv, value.ending, value.claim_move)
            candidate.update(rank=rank, root_move=move.uci(), score_cp=value.score, mate_in_plies=_mate_plies(value.score),
                             depth=output["completed_depth"], score_is_exact_for_search=True)
            output["candidates"].append(candidate)
        output["root_score_cp"] = completed[0][1].score
    if (claim_reasons or declarations) and (output["root_score_cp"] is None or output["root_score_cp"] <= 0):
        output["root_score_cp"] = 0
        output["recommended_action"] = "claim_draw"
        if not claim_reasons:
            output["intended_move"] = declarations[0].uci()
    output["nodes"] = search.nodes
    output["diagnostics"].update(qnodes=search.qnodes, cutoffs=search.cutoffs, stop_reason=stop_reason)
    output["elapsed_seconds"] = round(time.monotonic() - started, 6)
    output["budget_overrun_seconds"] = round(max(0.0, output["elapsed_seconds"] - seconds), 6)
    return output


@dataclass(frozen=True)
class _Goal:
    type: str
    side: int
    target: int | None

    @property
    def avoidance(self) -> bool:
        return self.type.startswith("avoid_")


def _goal(position: Position, specification: dict) -> _Goal:
    if not isinstance(specification, dict):
        raise ValueError("goal must be a mapping")
    extra = set(specification) - {"type", "side", "target"}
    if extra:
        raise ValueError("Unknown goal fields: " + ", ".join(sorted(map(str, extra))))
    kind = specification.get("type")
    if not isinstance(kind, str) or kind not in _GOAL_TYPES:
        raise ValueError("goal.type must be one of " + ", ".join(sorted(_GOAL_TYPES)))
    side_text = specification.get("side", _SIDE_NAMES[position.turn])
    if side_text not in ("white", "black"):
        raise ValueError("goal.side must be white or black")
    side = WHITE if side_text == "white" else BLACK
    target = None
    if kind in ("capture", "avoid_capture"):
        if "target" not in specification:
            raise ValueError(f"{kind} requires the initial square of the tracked piece")
        target = parse_square(specification["target"])
        piece = position.board[target]
        if piece == "." or piece.lower() == "k":
            raise ValueError("A capture target must be an existing non-king piece")
        expected = side if kind == "avoid_capture" else 1 - side
        if color_of(piece) != expected:
            raise ValueError("capture targets an enemy piece; avoid_capture protects an own piece")
    elif "target" in specification:
        raise ValueError(f"{kind} does not use a target square")
    return _Goal(kind, side, target)


def _target_after(position: Position, move: Move, target: int | None) -> int | None:
    if target is None:
        return None
    if move.from_sq == target:
        # The original identity survives promotion (and a rook's ordinary move).
        return move.to_sq
    if move.to_sq == target:
        return None
    piece = position.board[move.from_sq]
    if (piece.lower() == "p" and move.to_sq == position.ep_square
            and move.from_sq % 8 != move.to_sq % 8):
        victim = move.to_sq - 8 if position.turn == WHITE else move.to_sq + 8
        if target == victim:
            return None
    # A tracked rook can move as the other half of castling.
    if piece.lower() == "k" and abs(move.to_sq - move.from_sq) == 2:
        rook_from = move.from_sq + 3 if move.to_sq > move.from_sq else move.from_sq - 4
        rook_to = move.from_sq + 1 if move.to_sq > move.from_sq else move.from_sq - 1
        if target == rook_from:
            return rook_to
    return target


def _goal_order(position: Position, legal: list[Move], goal: _Goal, target: int | None) -> list[Move]:
    ordinary = _order(position, legal)
    def priority(move: Move) -> int:
        score = 0
        if goal.type == "capture" and target is not None:
            after = _target_after(position, move, target)
            if after is None:
                score += 100
        if goal.type == "castle" and position.turn == goal.side:
            if position.board[move.from_sq].lower() == "k" and abs(move.to_sq - move.from_sq) == 2:
                score += 100
        if goal.type in ("check", "checkmate") and position.turn == goal.side:
            if position.play(move).in_check():
                score += 50
        return -score
    return sorted(ordinary, key=priority)


class _Probe:
    def __init__(self, goal: _Goal, counts: Counter, deadline: float) -> None:
        self.goal = goal
        self.counts = counts
        self.deadline = deadline
        self.nodes = 0
        self.proof_nodes = 0
        self.witness_nodes = 0

    def check(self, proof: bool) -> None:
        if time.monotonic() >= self.deadline:
            raise _Stopped()
        self.nodes += 1
        if proof:
            self.proof_nodes += 1
        else:
            self.witness_nodes += 1

    def base(self, position: Position, remaining: int, target: int | None,
             castled: bool) -> tuple[bool | None, str | None, list[Move], dict | None]:
        goal = self.goal
        # Identity-based goals can resolve without generating an unnecessary
        # reply. A captured original target cannot later be replaced on its square.
        if goal.type == "capture" and target is None:
            return True, "goal_reached", [], None
        if goal.type == "avoid_capture" and target is None:
            return False, "target_captured", [], None
        if goal.type == "castle" and castled:
            return True, "goal_reached", [], None
        legal = position.legal_moves()
        terminal = _terminal(position, legal, self.counts)
        kind = goal.type
        reached = False
        violated = False
        if kind == "check":
            reached = position.in_check(1 - goal.side)
        elif kind == "avoid_check":
            violated = position.in_check(goal.side)
        elif kind == "checkmate":
            reached = bool(terminal and terminal["reason"] == "checkmate"
                           and position.turn != goal.side)
        elif kind == "avoid_checkmate":
            violated = bool(terminal and terminal["reason"] == "checkmate"
                            and position.turn == goal.side)
        elif kind == "stalemate":
            reached = bool(terminal and terminal["reason"] == "stalemate"
                           and position.turn != goal.side)
        elif kind == "avoid_stalemate":
            violated = bool(terminal and terminal["reason"] == "stalemate")
        if reached:
            return True, "goal_reached", legal, terminal
        if violated:
            return False, "avoidance_violated", legal, terminal
        if terminal:
            return goal.avoidance, "safe_terminal" if goal.avoidance else "terminal_without_goal", legal, terminal
        if remaining <= 0:
            return goal.avoidance, "safe_through_horizon" if goal.avoidance else "horizon_without_goal", legal, None
        return None, None, legal, None

    def next_state(self, position: Position, move: Move, target: int | None,
                   castled: bool) -> tuple[Position, int | None, bool]:
        new_target = _target_after(position, move, target)
        new_castled = castled or (position.turn == self.goal.side
                                 and position.board[move.from_sq].lower() == "k"
                                 and abs(move.to_sq - move.from_sq) == 2)
        return position.play(move), new_target, new_castled

    def prove(self, position: Position, remaining: int, target: int | None,
              castled: bool = False) -> tuple[bool, _Witness | None]:
        """OR at the goal side, AND at the opponent; every defense is legal."""
        self.check(True)
        value, ending, legal, _ = self.base(position, remaining, target, castled)
        if value is not None:
            return value, _Witness(ending=ending) if value else None
        own_turn = position.turn == self.goal.side
        claim_value = self.goal.avoidance
        if _claim_reasons(position, self.counts):
            if own_turn and claim_value:
                return True, _Witness(ending="draw_claim")
            if not own_turn and not claim_value:
                return False, None
        representative = None
        for move in _goal_order(position, legal, self.goal, target):
            self.check(True)
            child, new_target, new_castled = self.next_state(position, move, target, castled)
            if _prospective_claim(child, self.counts):
                if own_turn and claim_value:
                    return True, _Witness(ending="intended_move_draw_claim", claim_move=move.uci())
                if not own_turn and not claim_value:
                    return False, None
            key = child.repetition_key()
            self.counts[key] += 1
            try:
                result, line = self.prove(child, remaining - 1, new_target, new_castled)
            finally:
                self.counts[key] -= 1
                if not self.counts[key]:
                    del self.counts[key]
            if own_turn and result:
                return True, _Witness((move,) + line.moves, line.ending, line.claim_move)
            if not own_turn and not result:
                return False, None
            if result and line is not None:
                representative = _Witness((move,) + line.moves, line.ending, line.claim_move)
        return (False, None) if own_turn else (True, representative)

    def witnesses(self, position: Position, remaining: int, target: int | None,
                  limit: int, castled: bool = False,
                  prefix: tuple[Move, ...] = ()):
        """Existential on BOTH turns: yielded paths may require cooperation."""
        self.check(False)
        value, ending, legal, _ = self.base(position, remaining, target, castled)
        if value is not None:
            if value:
                yield _Witness(prefix, ending)
            return
        if self.goal.avoidance and _claim_reasons(position, self.counts):
            yield _Witness(prefix, "draw_claim")
            limit -= 1
            if not limit:
                return
        for move in _goal_order(position, legal, self.goal, target):
            self.check(False)
            child, new_target, new_castled = self.next_state(position, move, target, castled)
            if self.goal.avoidance and _prospective_claim(child, self.counts):
                yield _Witness(prefix, "intended_move_draw_claim", move.uci())
                limit -= 1
                if not limit:
                    return
            key = child.repetition_key()
            self.counts[key] += 1
            try:
                for line in self.witnesses(child, remaining - 1, new_target, limit,
                                           new_castled, prefix + (move,)):
                    yield line
                    limit -= 1
                    if not limit:
                        return
            finally:
                self.counts[key] -= 1
                if not self.counts[key]:
                    del self.counts[key]


def probe(position: Position, goal: dict, max_depth: int = 4, time_limit: float = 2.0,
          max_lines: int = 3, history: Any = None) -> dict:
    """Search one goal from an arbitrary position without quiet-move pruning.

    Achievement goals hold at least once within <= max_depth plies. Avoidance
    goals must hold at EVERY position through the full horizon or game end.
    ``forced`` means a goal-side strategy survives every legal defense within
    that bound. ``possible`` means a witness exists AND a complete adversarial
    search refuted a forcing strategy. ``unknown`` includes witnesses for which
    that proof/refutation could not finish. ``unreachable`` means exhaustive
    cooperative search found no witness. A displayed line alone is never proof.

    check/checkmate/stalemate concern the opponent; avoid_check/avoid_checkmate
    protect the goal side; avoid_stalemate avoids either side being stalemated.
    capture tracks an initial enemy non-king piece; avoid_capture tracks an own
    piece, including its new identity-square after promotion/castling/EP.
    """
    started = time.monotonic()
    max_depth, seconds, max_lines = _limits(max_depth, time_limit, max_lines)
    if not isinstance(position, Position):
        raise ValueError("position must be a Position")
    specification = _goal(position, goal)
    counts = _counts(position, history)
    reserve = min(0.5, seconds * 0.08)
    finish_search = started + seconds - reserve
    proof_deadline = started + (seconds - reserve) * 0.68
    worker = _Probe(specification, counts, proof_deadline)
    proof_status = "unknown"
    proof_depth = 0
    witness_status = "unknown"
    found: list[_Witness] = []
    seen = set()
    timed_out = False
    proof_interrupted = False
    witness_interrupted = False

    def add(line: _Witness) -> None:
        key = (line.moves, line.ending, line.claim_move)
        if key not in seen and len(found) < max_lines:
            seen.add(key)
            found.append(line)

    horizons = [max_depth] if specification.avoidance else range(1, max_depth + 1)
    try:
        for depth in horizons:
            proved, representative = worker.prove(position, depth, specification.target)
            proof_depth = depth
            if proved:
                proof_status = "forced"
                if representative is not None:
                    add(replace(representative, evidence="proof_representative"))
                break
            if depth == max_depth:
                proof_status = "refuted"
    except _Stopped:
        proof_interrupted = True
    worker.deadline = finish_search
    witness_depth = 0
    if found:
        witness_status = "found"
    try:
        for depth in horizons:
            # Fully consume or explicitly close each generator, so timeout or a
            # max_lines stop always unwinds its repetition-count bookkeeping.
            generator = worker.witnesses(position, depth, specification.target, max_lines)
            exhausted = True
            try:
                for line in generator:
                    add(line)
                    witness_status = "found"
                    if len(found) >= max_lines:
                        exhausted = False
                        break
            finally:
                generator.close()
            if exhausted:
                witness_depth = depth
            if len(found) >= max_lines:
                break
            if depth == max_depth and not found:
                witness_status = "absent"
    except _Stopped:
        witness_interrupted = True
        timed_out = True
    if proof_status == "forced":
        status = "forced"
    elif witness_status == "absent":
        status = "unreachable"
        # An exhaustive existential failure also logically refutes AND/OR.
        proof_status = "refuted"
    elif witness_status == "found" and proof_status == "refuted":
        status = "possible"
    else:
        status = "unknown"
    canonical_goal = {"type": specification.type, "side": _SIDE_NAMES[specification.side]}
    if specification.target is not None:
        canonical_goal["target"] = square_name(specification.target)
    lines = []
    for witness in found:
        line = _line(position, witness.moves, witness.ending, witness.claim_move)
        line["evidence"] = witness.evidence
        lines.append(line)
    output = {"kind": "goal_probe", "start_fen": position.fen(), "goal": canonical_goal,
              "horizon_plies": max_depth, "status": status, "proof_status": proof_status,
              "witness_status": witness_status, "proof_completed_depth": proof_depth,
              "witness_exhausted_depth": witness_depth, "lines": lines,
              "nodes": worker.nodes, "time_limit_seconds": seconds, "timed_out": timed_out,
              "history_supplied": history is not None,
              "semantics": {
                  "forced": "Goal-side strategy covers every legal opponent reply within the stated horizon; not beyond it.",
                  "possible": "A cooperative witness exists, but no forcing strategy exists within this horizon.",
                  "unreachable": "Exhaustive cooperative search found no successful line within this horizon.",
                  "unknown": "The available search did not establish the full result; a listed witness may still exist.",
                  "line_warning": "Lines are witnesses, not a complete strategy tree. Opponent choices may cooperate.",
                  "achievement": "At least once within the horizon; an already satisfied initial check/mate/stalemate counts.",
                  "avoidance": "Every position through the full horizon or earlier game termination; no immediate vacuous success.",
                  "target": "The original piece is tracked through movement, en passant, castling and promotion.",
                  "stalemate": "stalemate targets the opponent; avoid_stalemate forbids either side being stalemated.",
                  "draw_claims": "Optional current or intended-move claims can end the game; all-defenses proof includes them.",
                  "history": "Earlier repetitions cannot be inferred from FEN; supply keys for preceding positions.",
                  "dead_positions": "Conservative insufficient-material recognition, not an exhaustive dead-position solver."},
              "diagnostics": {"proof_nodes": worker.proof_nodes, "witness_nodes": worker.witness_nodes,
                              "proof_budget_exhausted": proof_interrupted,
                              "witness_budget_exhausted": witness_interrupted,
                              "material_pruning": False, "quiet_moves_included": True}}
    output["elapsed_seconds"] = round(time.monotonic() - started, 6)
    output["budget_overrun_seconds"] = round(max(0.0, output["elapsed_seconds"] - seconds), 6)
    return output
