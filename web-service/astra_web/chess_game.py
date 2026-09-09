"""Authoritative rules adapter. No external chess resources or engine changes."""
from collections import Counter
import hashlib
import secrets
import sys
import time
from .config import REPO_ROOT

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from astra_engine.rules import Position, START_FEN, WHITE, BLACK


def fingerprint():
    digest = hashlib.sha256()
    for name in ('rules.py', 'search.py', 'diagnostics.py'):
        digest.update(name.encode('ascii') + b'\0' + (REPO_ROOT / 'astra_engine' / name).read_bytes())
    return digest.hexdigest()


def new_game(user, side, config):
    now = time.time()
    return dict(id=secrets.token_hex(16), user_id=user['id'], name=user['name'], human_side=side,
                astra_side='black' if side == 'white' else 'white', fen=START_FEN,
                moves=[], messages=[], status='active', result='*', termination='', draw_offer=None,
                version=0, created_at=now, updated_at=now, last_human_activity=now,
                engine_fingerprint=fingerprint(), model=config.model, reasoning=config.reasoning,
                thread_id=None, own_moves=0, clock_used=0.0, active_started=None,
                worker={'state': 'idle', 'message': ''}, candidates=[], queries=[], decisions=[], clock_events=[])


def position(state):
    return Position.from_fen(state['fen'])


def side_to_move(state):
    return 'white' if position(state).turn == WHITE else 'black'


def history(state):
    return [START_FEN] + [m['fen'] for m in state['moves'][:-1]] if state['moves'] else []


def counts(state):
    return Counter(Position.from_fen(f).repetition_key() for f in history(state) + [state['fen']])


def claimable(state, move=None):
    board = position(state)
    tally = counts(state)
    if move:
        board = board.play(board.parse_uci(move))
        return board.halfmove >= 100 or tally[board.repetition_key()] >= 2
    return board.halfmove >= 100 or tally[board.repetition_key()] >= 3


def check_ending(state):
    board = position(state)
    legal = board.legal_moves()
    if not legal:
        if board.in_check():
            finish(state, '0-1' if board.turn == WHITE else '1-0', 'checkmate')
        else:
            finish(state, '1/2-1/2', 'stalemate')
    elif board.insufficient_material():
        finish(state, '1/2-1/2', 'insufficient_material')
    elif board.halfmove >= 150:
        finish(state, '1/2-1/2', 'seventy_five_moves')
    elif counts(state)[board.repetition_key()] >= 5:
        finish(state, '1/2-1/2', 'fivefold_repetition')


def message(state, author, text):
    text = str(text).strip()
    if not text or len(text) > 4000:
        raise ValueError('Messages must contain 1 to 4000 characters.')
    if len(state['messages']) >= 1000:
        raise ValueError('This game has reached its message limit.')
    state['messages'].append(dict(id=secrets.token_hex(8), author=author, text=text,
                                  ply=len(state['moves']), created_at=time.time()))


def finish(state, result, reason):
    state.update(status='finished', result=result, termination=reason, draw_offer=None)


def apply_move(state, uci, actor):
    if state['status'] != 'active':
        raise ValueError('This game is not active.')
    if side_to_move(state) != state['human_side' if actor == 'human' else 'astra_side']:
        raise ValueError('It is not your turn.')
    board = position(state)
    move = board.parse_uci(uci)
    uci = move.uci()
    captured = board.board[move.to_sq]
    if board.board[move.from_sq].lower() == 'p' and move.to_sq == board.ep_square and captured == '.':
        captured = 'p' if board.turn == WHITE else 'P'
    child = board.play(move)
    state['moves'].append(dict(uci=uci, san=board.san(move), fen=child.fen(), captured=captured,
                               actor=actor, at=time.time()))
    state['fen'] = child.fen()
    # An offer remains through its author's move, until the other side responds.
    if state['draw_offer'] and state['draw_offer'] != actor:
        state['draw_offer'] = None
    if actor == 'astra':
        state['own_moves'] += 1
    check_ending(state)


def active_clock_elapsed(state, now=None):
    """Charge only active own-turn work, excluding context compaction."""
    if state['active_started'] is None:
        return 0.0
    end = time.time() if now is None else now
    pause = state.get('compaction_pause')
    if pause and pause['clock_paused']:
        end = min(end, pause['started_at'])
    return max(0.0, end - state['active_started'] - state.get('active_paused_seconds', 0.0))


def finish_compaction(state, now, outcome):
    """Close durable pause evidence, including an interrupted worker's pause."""
    pause = state.get('compaction_pause')
    if not pause:
        return
    seconds = max(0.0, now - pause['started_at'])
    state.setdefault('compaction_events', []).append(dict(pause, ended_at=now,
        paused_seconds=seconds, outcome=outcome))
    if pause['clock_paused'] and state['active_started'] is not None:
        state['active_paused_seconds'] = state.get('active_paused_seconds', 0.0) + seconds
    state['compaction_pause'] = None


def clock(state):
    earned = 5400 + 30 * state['own_moves'] + (1800 if state['own_moves'] >= 40 else 0)
    live = active_clock_elapsed(state)
    used = state['clock_used'] + live
    pause = state.get('compaction_pause')
    paused = bool(state['active_started'] is not None and pause and pause['clock_paused'])
    return {'remaining_seconds': max(0, earned - used), 'used_seconds': used,
            'earned_seconds': earned, 'paused': paused,
            'pause_reason': 'compaction' if paused else None}


def snapshot(state, internal=False):
    board = position(state)
    result = {k: state[k] for k in ('id', 'name', 'human_side', 'astra_side', 'fen', 'moves', 'messages',
                                  'status', 'result', 'termination', 'draw_offer', 'version', 'created_at',
                                  'updated_at', 'worker', 'engine_fingerprint', 'model', 'reasoning')}
    result.update(board=list(board.board), legal_moves=[m.uci() for m in board.legal_moves()] if state['status'] == 'active' else [],
                  ply=len(state['moves']), clock=clock(state), claimable=claimable(state) if state['status'] == 'active' else False)
    if internal:
        result.update(history_fens=history(state), candidates=state['candidates'][-3:], decisions=state['decisions'][-3:])
    return result


def pgn(state):
    def escape(value):
        return str(value).replace('\\', '\\\\').replace('"', '\\"').replace('\n', ' ').replace('\r', ' ')
    names = {state['human_side']: state['name'], state['astra_side']: 'Astra'}
    headers = {'Event': 'Astra Chess Public Beta', 'Site': 'Astra Chess', 'White': names['white'],
               'Black': names['black'], 'Result': state['result'], 'Termination': state['termination'],
               'AstraModel': state['model'], 'AstraReasoning': state['reasoning'],
               'EngineSHA256': state['engine_fingerprint']}
    tokens = []
    for i, move in enumerate(state['moves']):
        if i % 2 == 0:
            tokens.append(f'{i // 2 + 1}.')
        tokens.append(move['san'])
    tokens.append(state['result'])
    return '\n'.join(f'[{k} "{escape(v)}"]' for k, v in headers.items()) + '\n\n' + ' '.join(tokens) + '\n'


def model_snapshot(state):
    """Fresh authoritative context; the full transcript/evidence stays durable.

    Previous messages already belong to the resumed Codex conversation. Avoid
    reinserting its entire transcript and a FEN for every historical ply each turn.
    """
    result = snapshot(state, internal=True)
    result.pop('history_fens', None)
    result['history_plies'] = len(state['moves'])
    result['moves'] = [{k: m[k] for k in ('uci', 'san', 'actor')} for m in state['moves']]
    result['messages'] = state['messages'][-12:]
    result['earlier_message_count'] = max(0, len(state['messages']) - 12)
    result['query_records'] = [{'index': i, 'ply': q.get('ply')} for i, q in enumerate(state['queries'])][-8:]
    return result
