"""Optional, rule-derived threat hints; never a proof of a trapped piece.

The report runs outside search nodes. Its pawn-safe mobility means only "not
controlled by an enemy pawn", not a legal or safe escape. The additive evaluator
and frontier trigger are deliberately separate, opt-in, inexpensive heuristics.
No piece-square tables, opening knowledge, or external engine is used here.
"""

from __future__ import annotations

from .rules import (BLACK, WHITE, Move, Position, color_of, square_name,
                    _KINGS, _KNIGHTS, _RAYS)


def _pawn_table(side: int) -> tuple[tuple[int, ...], ...]:
    step = 1 if side == WHITE else -1
    return tuple(tuple((sq // 8 + step) * 8 + sq % 8 + df
                       for df in (-1, 1)
                       if 0 <= sq // 8 + step < 8 and 0 <= sq % 8 + df < 8)
                 for sq in range(64))


_PAWN_ATTACKS = (_pawn_table(WHITE), _pawn_table(BLACK))
_BITS = tuple(1 << sq for sq in range(64))
_PAWN_MASKS = tuple(tuple(sum(_BITS[to] for to in targets) for targets in table)
                    for table in _PAWN_ATTACKS)
_VALUES = {"p": 100, "n": 320, "b": 330, "r": 500, "q": 900, "k": 20000}


def _pawn_controls(board: tuple[str, ...]) -> tuple[int, int]:
    white = black = 0
    for sq, piece in enumerate(board):
        if piece == "P":
            white |= _PAWN_MASKS[WHITE][sq]
        elif piece == "p":
            black |= _PAWN_MASKS[BLACK][sq]
    return white, black


def _minor_geometry(board: tuple[str, ...], sq: int, enemy_pawns: int):
    """Return destinations, first friendly blockers, and pawn-safe destinations."""
    piece = board[sq]
    own_upper = piece.isupper()
    destinations, blockers = [], []
    if piece.lower() == "n":
        for to in _KNIGHTS[sq]:
            occupant = board[to]
            if occupant != "." and occupant.isupper() == own_upper:
                blockers.append(to)
            elif occupant.lower() != "k":
                destinations.append(to)
    else:
        for ray in _RAYS[sq][4:]:
            for to in ray:
                occupant = board[to]
                if occupant == ".":
                    destinations.append(to)
                    continue
                if occupant.isupper() == own_upper:
                    blockers.append(to)
                elif occupant.lower() != "k":
                    destinations.append(to)
                break
    safe = [to for to in destinations if not enemy_pawns & _BITS[to]]
    return destinations, blockers, safe


def _minor_safe_count(board: tuple[str, ...], sq: int, enemy_pawns: int, cap: int) -> int:
    """Count only as far as the caller needs, without allocating report lists."""
    own_upper = board[sq].isupper()
    count = 0
    if board[sq].lower() == "n":
        for to in _KNIGHTS[sq]:
            occupant = board[to]
            if (occupant == "." or (occupant.isupper() != own_upper and occupant.lower() != "k")):
                if not enemy_pawns & _BITS[to]:
                    count += 1
                    if count >= cap:
                        return count
    else:
        for ray in _RAYS[sq][4:]:
            for to in ray:
                occupant = board[to]
                if occupant != "." and (occupant.isupper() == own_upper or occupant.lower() == "k"):
                    break
                if not enemy_pawns & _BITS[to]:
                    count += 1
                    if count >= cap:
                        return count
                if occupant != ".":
                    break
    return count


def _view(position: Position, side: int) -> Position:
    """A side-to-move hypothesis; an EP right never survives changing the turn."""
    if side == position.turn:
        return position
    return Position(position.board, side, position.castling, None,
                    position.halfmove, position.fullmove)


def _capture_threats(position: Position, target: int, by: int) -> list[Move]:
    """Generate legal captures of one occupied square, respecting pinned attackers.

    This is a next-turn hypothesis when ``by`` is not the actual side to move.
    Targets are minor pieces, so en passant is irrelevant here.
    """
    board = position.board
    victim = board[target]
    if victim == "." or victim.lower() == "k" or color_of(victim) == by:
        return []
    attackers = []
    pawn, knight, king = ("P", "N", "K") if by == WHITE else ("p", "n", "k")
    for origin in _PAWN_ATTACKS[1 - by][target]:
        if board[origin] == pawn:
            attackers.append(origin)
    for origin in _KNIGHTS[target]:
        if board[origin] == knight:
            attackers.append(origin)
    for origin in _KINGS[target]:
        if board[origin] == king:
            attackers.append(origin)
    for direction, ray in enumerate(_RAYS[target]):
        for origin in ray:
            piece = board[origin]
            if piece == ".":
                continue
            if color_of(piece) == by and piece.lower() in ("rq" if direction < 4 else "bq"):
                attackers.append(origin)
            break
    view = _view(position, by)
    legal = []
    for origin in attackers:
        promotions = "qrbn" if board[origin].lower() == "p" and target // 8 in (0, 7) else ("",)
        for promotion in promotions:
            move = Move(origin, target, promotion)
            if not view.play(move).in_check(by):
                legal.append(move)
    return legal


def _pawn_pushes(position: Position, side: int) -> list[tuple[Move, int]]:
    """Only legal non-capturing pawn advances, with their new control masks."""
    view = _view(position, side)
    board = position.board
    pawn = "P" if side == WHITE else "p"
    step, start = (8, 1) if side == WHITE else (-8, 6)
    moves = []
    for origin, piece in enumerate(board):
        if piece != pawn:
            continue
        one = origin + step
        if not 0 <= one < 64 or board[one] != ".":
            continue
        # A promoted pawn no longer has pawn control. Promotion threats belong
        # in ordinary search, rather than being mislabeled as pawn-push attacks.
        if one // 8 in (0, 7):
            continue
        targets = [one]
        two = one + step
        if origin // 8 == start and board[two] == ".":
            targets.append(two)
        for to in targets:
            move = Move(origin, to)
            if not view.play(move).in_check(side):
                moves.append((move, _PAWN_MASKS[side][to]))
    return moves


def _credible_capture(position: Position, target: int, by: int) -> bool:
    """Cheap material plausibility filter, not a static exchange proof."""
    victim_value = _VALUES[position.board[target].lower()]
    view = _view(position, by)
    for move in _capture_threats(position, target, by):
        if _VALUES[position.board[move.from_sq].lower()] <= victim_value:
            return True
        if not view.play(move).is_attacked(target, 1 - by):
            return True
    return False


def _open_file_access(position: Position, side: int) -> list[dict]:
    board = position.board
    king = board.index("K" if side == WHITE else "k")
    own_pawn = "P" if side == WHITE else "p"
    enemy_heavy = "rq" if side == WHITE else "RQ"
    result = []
    for file in range(max(0, king % 8 - 1), min(7, king % 8 + 1) + 1):
        if any(board[rank * 8 + file] == own_pawn for rank in range(8)):
            continue
        entry = (king // 8) * 8 + file
        for rank in range(8):
            origin = rank * 8 + file
            if board[origin] not in enemy_heavy:
                continue
            if origin != entry and color_of(board[entry]) == 1 - side:
                continue
            target_rank = king // 8
            if any(board[r * 8 + file] != "."
                   for r in range(min(rank, target_rank) + 1, max(rank, target_rank))):
                continue
            step = 1 if rank <= target_rank else -1
            result.append({"kind": "open_file_access", "attacker": square_name(origin),
                           "king": square_name(king), "screen": None,
                           "entry": square_name(entry),
                           "line": [square_name(r * 8 + file)
                                    for r in range(rank, target_rank + step, step)]})
    return result


def _king_lines(position: Position, side: int) -> list[dict]:
    """Enemy sliders aligned with the king, clear or behind one friendly screen."""
    board = position.board
    king = board.index("K" if side == WHITE else "k")
    lines = []
    for direction, ray in enumerate(_RAYS[king]):
        screen = None
        path = [king]
        for sq in ray:
            path.append(sq)
            piece = board[sq]
            if piece == ".":
                continue
            if color_of(piece) == side and screen is None:
                screen = sq
                continue
            if color_of(piece) != side and piece.lower() in ("rq" if direction < 4 else "bq"):
                lines.append({"kind": "clear_line" if screen is None else "single_screen",
                              "attacker": square_name(sq), "king": square_name(king),
                              "screen": None if screen is None else square_name(screen),
                              "line": [square_name(to) for to in reversed(path)]})
            break
    return lines + _open_file_access(position, side)


def diagnose(position: Position, *, side: int | None = None,
             previous: Position | None = None) -> dict:
    """Explain mobility and immediate threats without asserting forced outcomes.

    ``side`` is the player whose pieces are inspected (defaults to side to move).
    ``previous`` optionally supplies the board before a candidate continuation.
    An enemy move is literal only when that enemy is actually to move; otherwise
    it is explicitly a next-turn hypothesis, not a predicted legal continuation.
    """
    side = position.turn if side is None else side
    if side not in (WHITE, BLACK):
        raise ValueError("Diagnostic side must be WHITE or BLACK")
    enemy = 1 - side
    controls = _pawn_controls(position.board)
    pushes = _pawn_pushes(position, enemy)
    pieces, warnings = [], []
    for sq, piece in enumerate(position.board):
        if color_of(piece) != side or piece.lower() not in ("n", "b"):
            continue
        destinations, blockers, pawn_safe = _minor_geometry(position.board, sq, controls[enemy])
        captures = _capture_threats(position, sq, enemy)
        push_threats = [move.uci() for move, mask in pushes if mask & _BITS[sq]]
        restricted = len(pawn_safe) <= 1
        item = {"square": square_name(sq), "piece": piece,
                "own_blockers": [square_name(to) for to in blockers],
                "geometric_destinations": [square_name(to) for to in destinations],
                "pawn_safe_destinations": [square_name(to) for to in pawn_safe],
                "pawn_controlled_destinations": [square_name(to) for to in destinations
                                                  if controls[enemy] & _BITS[to]],
                "restricted_mobility": restricted,
                "legal_capture_threats": [move.uci() for move in captures],
                "pawn_push_threats": push_threats}
        pieces.append(item)
        if restricted:
            warnings.append(f"Restricted mobility at {square_name(sq)}: {len(pawn_safe)} destination(s) outside enemy pawn control.")
        if captures:
            warnings.append(f"Capture threat at {square_name(sq)}: {', '.join(move.uci() for move in captures)}.")
        if push_threats:
            warnings.append(f"Pawn advances can attack {square_name(sq)}: {', '.join(push_threats)}.")
    lines = _king_lines(position, side)
    previous_lines = _king_lines(previous, side) if previous is not None else []
    new_lines = [line for line in lines if line not in previous_lines] if previous is not None else []
    for line in lines:
        if line["kind"] == "clear_line":
            warnings.append(f"Open king line from {line['attacker']} to {line['king']}.")
        elif line["kind"] == "open_file_access":
            warnings.append(f"Open-file access from {line['attacker']} to {line['entry']} near the king on {line['king']}.")
    return {"kind": "heuristic_threat_diagnostics", "fen": position.fen(),
            "side": "white" if side == WHITE else "black",
            "turn_context": "enemy_to_move" if enemy == position.turn else "enemy_next_turn_hypothesis",
            "minor_pieces": pieces, "king_lines": lines, "new_king_lines": new_lines,
            "warnings": warnings,
            "limitations": ["Pawn-safe mobility is geometric; other attackers and king pins can restrict it further.",
                            "A capture threat or restricted piece does not prove forced loss or lack of compensation.",
                            "When the enemy is not to move, threat moves assume that enemy could move next on this unchanged board.",
                            "Moving a blocker, capturing the attacker, exchanges, and counterchecks require adversarial search."]}


def extra_evaluate(position: Position, options: dict | None = None) -> int:
    """Modest optional additive centipawns, always from White's perspective.

    Flags are ``mobility``, ``restricted_piece``, and ``king_exposure``. These
    features remain heuristic and independently switchable. With no flags set,
    no board scan or attack generation is performed.
    """
    if not options:
        return 0
    mobility = options.get("mobility", False)
    restricted = options.get("restricted_piece", False)
    exposure = options.get("king_exposure", False)
    if not (mobility or restricted or exposure):
        return 0
    board = position.board
    score = 0
    if mobility or restricted:
        controls = _pawn_controls(board)
        for sq, piece in enumerate(board):
            if piece.lower() not in ("n", "b"):
                continue
            side = WHITE if piece.isupper() else BLACK
            count = _minor_safe_count(board, sq, controls[1 - side], 8 if mobility else 2)
            value = 3 * (min(count, 8) - 4) if mobility else 0
            if restricted and count <= 1 and _credible_capture(position, sq, 1 - side):
                value -= 48 if count == 0 else 28
            score += value if side == WHITE else -value
    if exposure:
        # Measure heavy-piece file access only, not the pawn-shield term already
        # in the base evaluation. No bonus for an open file without enemy access.
        for side in (WHITE, BLACK):
            penalty = min(36, sum(12 if line["entry"] == line["king"] else 6
                                  for line in _open_file_access(position, side)))
            score += -penalty if side == WHITE else penalty
    return score


def threat_frontier(position: Position) -> bool:
    """Trigger a bounded full-width ply for an attacked restricted minor piece.

    Pinned geometric attackers alone do not trigger it. This does not prove a
    forced material loss: search must retain blocker moves and counterchecks.
    Check evasions remain the ordinary search's responsibility.
    """
    side = position.turn
    controls = _pawn_controls(position.board)
    for sq, piece in enumerate(position.board):
        if color_of(piece) != side or piece.lower() not in ("n", "b"):
            continue
        if _minor_safe_count(position.board, sq, controls[1 - side], 2) <= 1:
            if _credible_capture(position, sq, 1 - side):
                return True
    return False
