"""Read a historical score for Astra's actual latest move; never run a search.

Scores are from the query's root player's perspective, including when Astra is
Black. The latest qualifying completed query for the chosen move wins. A later
human reply does not change the historical score. Missing/incomplete evidence
is not cached, so restored or newly completed files can appear immediately.
"""
import json
import math
from pathlib import Path, PurePosixPath
import re

from .chess_game import START_FEN


MAX_RESULT_BYTES = 2_000_000


def _read_result(data_dir, game_id, raw_path):
    if not isinstance(raw_path, str) or not 1 <= len(raw_path) <= 4096:
        return None
    # Saved Windows records also remain readable after migration to Linux.
    relative = PurePosixPath(raw_path.replace("\\", "/"))
    if (relative.is_absolute() or len(relative.parts) < 4
            or relative.parts[:3] != ("games", game_id, "queries")
            or any(part == ".." or ":" in part for part in relative.parts)
            or not relative.name.endswith(".result.json")):
        return None
    try:
        base = Path(data_dir).resolve()
        game_dir = base / "games" / game_id
        folder = (game_dir / "queries").resolve()
        path = base.joinpath(*relative.parts).resolve()
        # Also reject a game-directory symlink into another game's evidence.
        if not folder.is_relative_to(game_dir) or not path.is_relative_to(folder):
            return None
        if not path.is_file() or path.stat().st_size > MAX_RESULT_BYTES:
            return None
        with path.open("rb") as file:
            raw = file.read(MAX_RESULT_BYTES + 1)
        if len(raw) > MAX_RESULT_BYTES:
            return None
        result = json.loads(raw)
        return result if isinstance(result, dict) else None
    except (OSError, ValueError, RuntimeError):
        return None


def _qualifying(result, *, side, before, after, uci, san, ply):
    if not isinstance(result, dict):
        return None
    depth = result.get("completed_depth")
    if (result.get("kind") != "analysis" or result.get("start_fen") != before
            or result.get("turn") != side or type(depth) is not int or depth < 1
            or result.get("fallback") is not False):
        return None
    request = result.get("query")
    if request is not None and (not isinstance(request, dict) or request.get("after")
                                or request.get("fen", before) != before
                                or request.get("mode", "analyze") != "analyze"):
        return None
    candidates = result.get("candidates")
    if not isinstance(candidates, list):
        return None
    matches = [candidate for candidate in candidates
               if isinstance(candidate, dict) and candidate.get("root_move") == uci]
    if len(matches) != 1:
        return None
    candidate = matches[0]
    if (not all(isinstance(candidate.get(field), list) for field in ("uci", "san", "fens"))
            or candidate["uci"][:1] != [uci] or candidate["san"][:1] != [san]
            or candidate["fens"][:2] != [before, after]
            or candidate.get("score_is_exact_for_search") is not True
            or type(candidate.get("depth")) is not int or candidate["depth"] != depth):
        return None
    score = candidate.get("score_cp")
    if type(score) not in (int, float) or "mate_in_plies" not in candidate:
        return None
    try:
        if not math.isfinite(score):
            return None
    except OverflowError:
        return None
    mate = candidate.get("mate_in_plies")
    if mate is not None and (type(mate) is not int or mate == 0):
        return None
    return {
        "score_pawns": score / 100 if mate is None else None,
        "mate_in_moves": (abs(mate) + 1) // 2 if mate is not None else None,
        "mate_for": ("astra" if mate > 0 else "opponent") if mate is not None else None,
        "ply": ply, "uci": uci, "san": san, "completed_depth": depth,
    }


def latest_astra_evaluation(state, data_dir):
    """Return the small public evaluation object, or None when unsubstantiated."""
    try:
        if state.get("termination") == "checkmate":
            return None
        game_id, side = state.get("id"), state.get("astra_side")
        if (not isinstance(game_id, str) or not re.fullmatch(r"[0-9a-f]{32}", game_id)
                or side not in ("white", "black")):
            return None
        moves = state.get("moves")
        if not isinstance(moves, list):
            return None
        ply = next((index for index in range(len(moves) - 1, -1, -1)
                    if isinstance(moves[index], dict) and moves[index].get("actor") == "astra"), None)
        if ply is None:
            return None
        move = moves[ply]
        before = START_FEN if ply == 0 else moves[ply - 1]["fen"]
        after, uci, san = move["fen"], move["uci"], move["san"]
        if (not all(isinstance(value, str) for value in (before, after, uci, san))
                or len(before.split()) != 6 or len(after.split()) != 6
                or before.split()[1] != side[0]
                or after.split()[1] != ("b" if side == "white" else "w")):
            return None
        queries = state.get("queries")
        if not isinstance(queries, list):
            return None
        for record in reversed(queries):
            if not isinstance(record, dict) or type(record.get("ply")) is not int or record["ply"] != ply:
                continue
            result = _read_result(data_dir, game_id, record.get("path"))
            evaluation = _qualifying(result, side=side, before=before, after=after, uci=uci, san=san, ply=ply)
            if evaluation is not None:
                return evaluation
    except (KeyError, IndexError, TypeError, AttributeError, ValueError, OverflowError, RuntimeError):
        # Optional presentation evidence must never turn a valid move into an error.
        return None
    return None
