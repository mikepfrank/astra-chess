"""Orthodox chess rules written for this project, without chess dependencies.

Squares run from a1=0 to h8=63. Positions are immutable. ``play`` is the fast
internal transition for an already legal move; ``parse_uci`` is the validating
public entry point for a user-supplied move. FEN loading validates structure,
not the existence of a complete legal game reaching that position.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

WHITE = 0
BLACK = 1
START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

_PIECES = frozenset("PNBRQKpnbrqk")
_DIRECTIONS = ((1, 0), (-1, 0), (0, 1), (0, -1),
               (1, 1), (1, -1), (-1, 1), (-1, -1))


def square_name(index: int) -> str:
    if not isinstance(index, int) or not 0 <= index < 64:
        raise ValueError("Square index must be between 0 and 63")
    return chr(97 + index % 8) + str(index // 8 + 1)


def parse_square(name: str) -> int:
    if not isinstance(name, str) or re.fullmatch(r"[a-h][1-8]", name) is None:
        raise ValueError(f"Invalid square: {name!r}")
    return ord(name[0]) - 97 + (int(name[1]) - 1) * 8


def color_of(piece: str) -> int | None:
    """Return WHITE/BLACK for a piece, or None for an empty square."""
    if piece == ".":
        return None
    return WHITE if piece.isupper() else BLACK


def _jump_table(offsets: tuple[tuple[int, int], ...]) -> tuple[tuple[int, ...], ...]:
    return tuple(tuple((rank + dr) * 8 + file + df
                       for df, dr in offsets
                       if 0 <= file + df < 8 and 0 <= rank + dr < 8)
                 for rank in range(8) for file in range(8))


_KNIGHTS = _jump_table(((1, 2), (2, 1), (2, -1), (1, -2),
                       (-1, -2), (-2, -1), (-2, 1), (-1, 2)))
_KINGS = _jump_table(_DIRECTIONS)
_RAYS = tuple(tuple(tuple((rank + dr * step) * 8 + file + df * step
                         for step in range(1, 8)
                         if 0 <= file + df * step < 8 and 0 <= rank + dr * step < 8)
                   for df, dr in _DIRECTIONS)
              for rank in range(8) for file in range(8))


@dataclass(frozen=True, slots=True)
class Move:
    from_sq: int
    to_sq: int
    promotion: str = ""

    def uci(self) -> str:
        return square_name(self.from_sq) + square_name(self.to_sq) + self.promotion

    def __str__(self) -> str:
        return self.uci()


@dataclass(frozen=True, slots=True)
class Position:
    board: tuple[str, ...]
    turn: int = WHITE
    castling: str = "KQkq"
    ep_square: int | None = None
    halfmove: int = 0
    fullmove: int = 1

    @classmethod
    def from_fen(cls, fen: str) -> Position:
        if not isinstance(fen, str):
            raise ValueError("FEN must be a string")
        fields = fen.split()
        if len(fields) != 6:
            raise ValueError("FEN must have six fields")
        placement, active, rights, ep, halfmove_text, fullmove_text = fields
        rows = placement.split("/")
        if len(rows) != 8:
            raise ValueError("FEN board must have eight ranks")
        board = ["."] * 64
        for row_index, row in enumerate(rows):
            file = 0
            for token in row:
                if token in "12345678":
                    file += int(token)
                elif token in _PIECES:
                    if file >= 8:
                        raise ValueError("FEN rank exceeds eight squares")
                    board[(7 - row_index) * 8 + file] = token
                    file += 1
                else:
                    raise ValueError(f"Invalid FEN board character: {token!r}")
                if file > 8:
                    raise ValueError("FEN rank exceeds eight squares")
            if file != 8:
                raise ValueError("Each FEN rank must contain eight squares")
        if active not in ("w", "b"):
            raise ValueError("FEN active color must be w or b")
        turn = WHITE if active == "w" else BLACK
        if rights == "-":
            rights = ""
        elif (not rights or any(char not in "KQkq" for char in rights)
              or len(set(rights)) != len(rights)):
            raise ValueError("Invalid FEN castling rights")
        rights = "".join(char for char in "KQkq" if char in rights)
        if (re.fullmatch(r"[0-9]+", halfmove_text) is None
                or re.fullmatch(r"[0-9]+", fullmove_text) is None):
            raise ValueError("FEN counters must be nonnegative integers")
        halfmove = int(halfmove_text)
        fullmove = int(fullmove_text)
        if fullmove < 1:
            raise ValueError("FEN fullmove number must be at least one")
        if board.count("K") != 1 or board.count("k") != 1:
            raise ValueError("A position must contain exactly one king per side")
        if any(piece.lower() == "p" for piece in board[:8] + board[56:]):
            raise ValueError("Pawns cannot stand on the first or eighth rank")
        for color, pawn in ((WHITE, "P"), (BLACK, "p")):
            if board.count(pawn) > 8 or sum(color_of(piece) == color for piece in board) > 16:
                raise ValueError("A side cannot have more than eight pawns or sixteen pieces")
        if board.index("k") in _KINGS[board.index("K")]:
            raise ValueError("Kings cannot occupy adjacent squares")
        for right, king_square, rook_square, king, rook in (
            ("K", 4, 7, "K", "R"), ("Q", 4, 0, "K", "R"),
            ("k", 60, 63, "k", "r"), ("q", 60, 56, "k", "r"),
        ):
            if right in rights and (board[king_square] != king or board[rook_square] != rook):
                raise ValueError("Castling rights require the king and rook on their home squares")
        ep_square = None if ep == "-" else parse_square(ep)
        if ep_square is not None:
            expected_rank = 5 if turn == WHITE else 2
            victim_square = ep_square - 8 if turn == WHITE else ep_square + 8
            origin_square = ep_square + 8 if turn == WHITE else ep_square - 8
            victim = "p" if turn == WHITE else "P"
            if (ep_square // 8 != expected_rank or board[ep_square] != "."
                    or board[victim_square] != victim or board[origin_square] != "."
                    or halfmove != 0):
                raise ValueError("Invalid en passant target or double-push history")
        position = cls(tuple(board), turn, rights, ep_square, halfmove, fullmove)
        if position.in_check(1 - turn):
            raise ValueError("The side that just moved cannot have left its king in check")
        return position

    def fen(self) -> str:
        rows = []
        for rank in range(7, -1, -1):
            row = ""
            empty = 0
            for piece in self.board[rank * 8:rank * 8 + 8]:
                if piece == ".":
                    empty += 1
                else:
                    if empty:
                        row += str(empty)
                        empty = 0
                    row += piece
            if empty:
                row += str(empty)
            rows.append(row)
        return ("/".join(rows) + (" w " if self.turn == WHITE else " b ")
                + (self.castling or "-") + " "
                + (square_name(self.ep_square) if self.ep_square is not None else "-")
                + f" {self.halfmove} {self.fullmove}")

    def is_attacked(self, square: int, by_color: int) -> bool:
        """Include attacks by pinned pieces, as required for king safety."""
        board = self.board
        file = square % 8
        if by_color == WHITE:
            pawn, knight, king = "P", "N", "K"
            rook, bishop, queen = "R", "B", "Q"
            if square >= 8:
                if file > 0 and board[square - 9] == pawn:
                    return True
                if file < 7 and board[square - 7] == pawn:
                    return True
        else:
            pawn, knight, king = "p", "n", "k"
            rook, bishop, queen = "r", "b", "q"
            if square < 56:
                if file > 0 and board[square + 7] == pawn:
                    return True
                if file < 7 and board[square + 9] == pawn:
                    return True
        for origin in _KNIGHTS[square]:
            if board[origin] == knight:
                return True
        for origin in _KINGS[square]:
            if board[origin] == king:
                return True
        for direction_index, ray in enumerate(_RAYS[square]):
            slider = rook if direction_index < 4 else bishop
            for origin in ray:
                piece = board[origin]
                if piece != ".":
                    if piece == slider or piece == queen:
                        return True
                    break
        return False

    def in_check(self, color: int | None = None) -> bool:
        if color is None:
            color = self.turn
        king_square = self.board.index("K" if color == WHITE else "k")
        return self.is_attacked(king_square, 1 - color)

    def _iter_pseudo_moves(self, tactical_only: bool = False):
        """Yield in the historical deterministic order, without quiet allocation.

        ``tactical_only`` includes captures, en passant, and every promotion.
        It is not an evasion generator; callers in check must request all moves.
        """
        board, turn = self.board, self.turn
        enemy_king = "k" if turn == WHITE else "K"
        own_upper = turn == WHITE
        for origin, piece in enumerate(board):
            if piece == "." or piece.isupper() != own_upper:
                continue
            kind = piece.lower()
            if kind == "p":
                step = 8 if turn == WHITE else -8
                promotion_rank = 7 if turn == WHITE else 0
                start_rank = 1 if turn == WHITE else 6
                forward = origin + step
                if 0 <= forward < 64 and board[forward] == ".":
                    if forward // 8 == promotion_rank:
                        for promotion in "qrbn":
                            yield Move(origin, forward, promotion)
                    elif not tactical_only:
                        yield Move(origin, forward)
                        double = forward + step
                        if origin // 8 == start_rank and board[double] == ".":
                            yield Move(origin, double)
                for df in (-1, 1):
                    if not 0 <= origin % 8 + df < 8:
                        continue
                    target = origin + step + df
                    if not 0 <= target < 64:
                        continue
                    victim = board[target]
                    capture = victim != "." and victim.isupper() != own_upper and victim != enemy_king
                    ep_capture = (target == self.ep_square and victim == "."
                                  and board[target - step] == ("p" if own_upper else "P"))
                    if capture or ep_capture:
                        if target // 8 == promotion_rank:
                            for promotion in "qrbn":
                                yield Move(origin, target, promotion)
                        else:
                            yield Move(origin, target)
            elif kind in ("n", "k"):
                for target in (_KNIGHTS if kind == "n" else _KINGS)[origin]:
                    victim = board[target]
                    if ((victim == "." and not tactical_only)
                            or (victim != "." and victim.isupper() != own_upper and victim != enemy_king)):
                        yield Move(origin, target)
            else:
                direction_indices = range(4) if kind == "r" else range(4, 8) if kind == "b" else range(8)
                for direction_index in direction_indices:
                    for target in _RAYS[origin][direction_index]:
                        victim = board[target]
                        if victim == ".":
                            if not tactical_only:
                                yield Move(origin, target)
                        else:
                            if victim.isupper() != own_upper and victim != enemy_king:
                                yield Move(origin, target)
                            break
        if tactical_only:
            return
        base = 0 if turn == WHITE else 56
        king, rook = ("K", "R") if turn == WHITE else ("k", "r")
        kingside, queenside = ("K", "Q") if turn == WHITE else ("k", "q")
        if board[base + 4] == king and not self.is_attacked(base + 4, 1 - turn):
            if (kingside in self.castling and board[base + 7] == rook
                    and board[base + 5] == board[base + 6] == "."
                    and not self.is_attacked(base + 5, 1 - turn)
                    and not self.is_attacked(base + 6, 1 - turn)):
                yield Move(base + 4, base + 6)
            if (queenside in self.castling and board[base] == rook
                    and board[base + 1] == board[base + 2] == board[base + 3] == "."
                    and not self.is_attacked(base + 3, 1 - turn)
                    and not self.is_attacked(base + 2, 1 - turn)):
                yield Move(base + 4, base + 2)

    def _pseudo_moves(self) -> list[Move]:
        return list(self._iter_pseudo_moves())

    def iter_legal_children(self, tactical_only: bool = False):
        """Yield legal moves together with the already constructed child board."""
        turn = self.turn
        for move in self._iter_pseudo_moves(tactical_only):
            child = self.play(move)
            if not child.in_check(turn):
                yield move, child

    def legal_children(self, tactical_only: bool = False) -> dict[Move, Position]:
        return dict(self.iter_legal_children(tactical_only))

    def has_legal_move(self) -> bool:
        """Stop on the first legal move; used to exclude a quiet stalemate."""
        return next(self.iter_legal_children(), None) is not None

    def legal_moves(self) -> list[Move]:
        return [move for move, _ in self.iter_legal_children()]

    def play(self, move: Move) -> Position:
        """Apply an already legal move. Use parse_uci at untrusted boundaries."""
        board = list(self.board)
        piece = board[move.from_sq]
        victim = board[move.to_sq]
        is_pawn = piece.lower() == "p"
        board[move.from_sq] = "."
        board[move.to_sq] = piece
        if is_pawn and move.to_sq == self.ep_square and victim == "." and move.from_sq % 8 != move.to_sq % 8:
            captured_square = move.to_sq - 8 if self.turn == WHITE else move.to_sq + 8
            victim = board[captured_square]
            board[captured_square] = "."
        if move.promotion:
            board[move.to_sq] = move.promotion.upper() if self.turn == WHITE else move.promotion.lower()
        rights = self.castling
        if piece.lower() == "k":
            rights = rights.replace("K", "").replace("Q", "") if self.turn == WHITE else rights.replace("k", "").replace("q", "")
            if abs(move.to_sq - move.from_sq) == 2:
                if move.to_sq > move.from_sq:
                    rook_from, rook_to = move.from_sq + 3, move.from_sq + 1
                else:
                    rook_from, rook_to = move.from_sq - 4, move.from_sq - 1
                board[rook_to] = board[rook_from]
                board[rook_from] = "."
        for corner, right, rook in ((0, "Q", "R"), (7, "K", "R"), (56, "q", "r"), (63, "k", "r")):
            if ((move.from_sq == corner and piece == rook)
                    or (move.to_sq == corner and victim == rook)):
                rights = rights.replace(right, "")
        ep_square = (move.from_sq + move.to_sq) // 2 if is_pawn and abs(move.to_sq - move.from_sq) == 16 else None
        halfmove = 0 if is_pawn or victim != "." else self.halfmove + 1
        return Position(tuple(board), 1 - self.turn, rights, ep_square, halfmove,
                        self.fullmove + (1 if self.turn == BLACK else 0))

    def parse_uci(self, text: str) -> Move:
        if not isinstance(text, str) or re.fullmatch(r"[a-h][1-8][a-h][1-8][qrbn]?", text.strip()) is None:
            raise ValueError(f"Invalid UCI move: {text!r}")
        text = text.strip()
        move = Move(parse_square(text[:2]), parse_square(text[2:4]), text[4:])
        if move not in self.legal_moves():
            raise ValueError(f"Illegal move {text} in {self.fen()}")
        return move

    def san(self, move: Move, legal_moves: list[Move] | None = None) -> str:
        if legal_moves is None:
            legal_moves = self.legal_moves()
        if move not in legal_moves:
            raise ValueError(f"Cannot format illegal move {move.uci()} as SAN")
        piece = self.board[move.from_sq]
        kind = piece.upper()
        if kind == "K" and abs(move.to_sq - move.from_sq) == 2:
            notation = "O-O" if move.to_sq > move.from_sq else "O-O-O"
        else:
            capture = self.board[move.to_sq] != "." or (kind == "P" and move.from_sq % 8 != move.to_sq % 8)
            notation = "" if kind == "P" else kind
            if kind == "P":
                if capture:
                    notation += square_name(move.from_sq)[0]
            else:
                alternatives = [other for other in legal_moves
                                if other != move and other.to_sq == move.to_sq
                                and self.board[other.from_sq] == piece]
                if alternatives:
                    same_file = any(other.from_sq % 8 == move.from_sq % 8 for other in alternatives)
                    same_rank = any(other.from_sq // 8 == move.from_sq // 8 for other in alternatives)
                    if not same_file:
                        notation += square_name(move.from_sq)[0]
                    elif not same_rank:
                        notation += square_name(move.from_sq)[1]
                    else:
                        notation += square_name(move.from_sq)
            if capture:
                notation += "x"
            notation += square_name(move.to_sq)
            if move.promotion:
                notation += "=" + move.promotion.upper()
        child = self.play(move)
        if child.in_check():
            notation += "+" if child.legal_moves() else "#"
        return notation

    def repetition_key(self) -> tuple:
        """FIDE position identity: retain EP only if an EP capture is legal."""
        effective_ep = None
        if self.ep_square is not None:
            pawn = "P" if self.turn == WHITE else "p"
            step = 8 if self.turn == WHITE else -8
            for df in (-1, 1):
                origin = self.ep_square - step + df
                if (0 <= origin < 64 and abs(origin % 8 - self.ep_square % 8) == 1
                        and self.board[origin] == pawn
                        and not self.play(Move(origin, self.ep_square)).in_check(self.turn)):
                    effective_ep = self.ep_square
                    break
        return self.board, self.turn, self.castling, effective_ep

    def insufficient_material(self) -> bool:
        """Conservative dead-position subset; never declare two knights dead.

        Covers bare kings, one minor against a bare king, and any number of
        bishops confined to a single square color with no other nonking pieces.
        More unusual blocked dead positions are deliberately not inferred.
        """
        minors = []
        for square, piece in enumerate(self.board):
            kind = piece.lower()
            if kind in (".", "k"):
                continue
            if kind in ("p", "r", "q"):
                return False
            minors.append((square, kind))
        if len(minors) <= 1:
            return True
        if any(kind != "b" for _, kind in minors):
            return False
        return len({(square % 8 + square // 8) % 2 for square, _ in minors}) == 1

    def ascii(self) -> str:
        rows = [str(rank + 1) + "  " + " ".join(self.board[rank * 8:rank * 8 + 8])
                for rank in range(7, -1, -1)]
        return "\n".join(rows + ["   a b c d e f g h"])
