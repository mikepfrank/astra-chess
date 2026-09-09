"""Compact model view of archived engine evidence; the source result is untouched.

Only the known normal-analysis PV diagnostic sequence is projected. Every other
result/candidate field, including root diagnostics, scores, draw claims, proof
qualifiers, settings and history, is copied without alteration.

Projected candidates omit ``position_diagnostics`` and add:
* ``diagnostics_available: True``: the original sequence is available from the
  host's read-only query-details tool; this does not imply complete inspection.
* ``diagnostic_summary``: ``kind``, a pool of verbatim ``limitations``, and a
  ``frames`` list aligned with the unchanged candidate ``fens``. Null frames
  remain null. Other frames retain their zero-based index, side, turn context,
  every warning, limitation indices (including duplicates), and all current/new
  king lines. The pool reconstructs each original limitations list exactly.

The bulky minor-piece geometry arrays remain in the original evidence. Their
restricted-mobility/capture/pawn-push warnings remain verbatim in every frame.
No absent warning is interpreted as proof of safety. Unknown schema additions,
including additions inside minor-piece records, cause safe passthrough.
"""
from copy import deepcopy


_FRAME_FIELDS = {"kind", "fen", "side", "turn_context", "minor_pieces", "king_lines",
                 "new_king_lines", "warnings", "limitations"}
_MINOR_FIELDS = {"square", "piece", "own_blockers", "geometric_destinations",
                 "pawn_safe_destinations", "pawn_controlled_destinations",
                 "restricted_mobility", "legal_capture_threats", "pawn_push_threats"}
_MINOR_LISTS = _MINOR_FIELDS - {"square", "piece", "restricted_mobility"}


def _strings(value):
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _known_frame(frame, fen):
    if frame is None:
        return True
    if (not isinstance(frame, dict) or set(frame) != _FRAME_FIELDS
            or frame["kind"] != "heuristic_threat_diagnostics" or frame["fen"] != fen
            or frame["side"] not in ("white", "black")
            or frame["turn_context"] not in ("enemy_to_move", "enemy_next_turn_hypothesis")
            or not _strings(frame["warnings"]) or not _strings(frame["limitations"])
            or not isinstance(frame["minor_pieces"], list)
            or not isinstance(frame["king_lines"], list) or not isinstance(frame["new_king_lines"], list)):
        return False
    for piece in frame["minor_pieces"]:
        if (not isinstance(piece, dict) or set(piece) != _MINOR_FIELDS
                or not isinstance(piece["square"], str) or not isinstance(piece["piece"], str)
                or type(piece["restricted_mobility"]) is not bool
                or any(not _strings(piece[field]) for field in _MINOR_LISTS)):
            return False
    return True


def _known_candidate(candidate):
    if (not isinstance(candidate, dict)
            or "diagnostics_available" in candidate or "diagnostic_summary" in candidate
            or not all(_strings(candidate.get(key)) for key in ("uci", "san", "fens"))
            or len(candidate["san"]) != len(candidate["uci"])
            or len(candidate["fens"]) != len(candidate["uci"]) + 1):
        return False
    frames = candidate.get("position_diagnostics")
    return (isinstance(frames, list) and len(frames) == len(candidate["fens"])
            and all(_known_frame(frame, candidate["fens"][i]) for i, frame in enumerate(frames)))


def compact_result(result):
    """Return an independent model-facing copy; never rewrite archived evidence."""
    view = deepcopy(result)
    if not isinstance(view, dict) or view.get("kind") != "analysis" or not isinstance(view.get("candidates"), list):
        return view
    for candidate in view["candidates"]:
        if not _known_candidate(candidate):
            continue
        summary = {"kind": "heuristic_threat_diagnostics", "limitations": [], "frames": []}
        indices = {}
        for index, frame in enumerate(candidate.pop("position_diagnostics")):
            if frame is None:
                summary["frames"].append(None)
                continue
            limitation_indices = []
            for text in frame["limitations"]:
                if text not in indices:
                    indices[text] = len(summary["limitations"])
                    summary["limitations"].append(text)
                limitation_indices.append(indices[text])
            summary["frames"].append({
                "frame": index, "side": frame["side"], "turn_context": frame["turn_context"],
                "warnings": frame["warnings"], "limitation_indices": limitation_indices,
                "king_lines": frame["king_lines"], "new_king_lines": frame["new_king_lines"],
            })
        candidate["diagnostics_available"] = True
        candidate["diagnostic_summary"] = summary
    return view
