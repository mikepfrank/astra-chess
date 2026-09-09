"""Validated public replay records and offline HTML; never start an engine or model."""
from copy import deepcopy
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import sqlite3
import tempfile
import time

from . import chess_game as game
from .evaluations import latest_astra_evaluation, _read_result, _qualifying, _qualifying_mate_proof


APP_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = APP_ROOT.parent
SCHEMA_VERSION = 1
MAX_RECORD_BYTES = 12_000_000
GAME_FIELDS = {'id', 'name', 'human_side', 'astra_side', 'model', 'reasoning', 'result',
               'termination', 'created_at', 'updated_at', 'exported_at', 'initial_fen',
               'status', 'engine_fingerprint'}
MOVE_FIELDS = {'uci', 'san', 'fen', 'captured', 'actor', 'at'}
MESSAGE_FIELDS = {'author', 'name', 'ply', 'text', 'created_at'}
EVALUATION_FIELDS = {'score_pawns', 'mate_in_moves', 'mate_for', 'ply', 'uci', 'san', 'completed_depth'}
PROVENANCE_FIELDS = {'query_index', 'hash_format', 'result_sha256', 'request_sha256',
                     'path_sha256', 'engine_source_sha256', 'selection_sha256'}


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)


def _hash(value):
    return hashlib.sha256(_json(value).encode('utf-8')).hexdigest()


def _timestamp(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError('Archive timestamps must be finite nonnegative Unix seconds.')
    try:
        datetime.fromtimestamp(value, timezone.utc)
    except (OverflowError, OSError, ValueError) as error:
        raise ValueError('Archive timestamp is outside the supported range.') from error
    return value


def _text(value, maximum, label):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or '\x00' in value:
        raise ValueError(f'Invalid archive {label}.')
    return value


def _sha(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def read_game(data_dir, game_id):
    """Read one consistent SQLite snapshot without constructing a writing Store."""
    if not isinstance(game_id, str) or not re.fullmatch(r'[0-9a-f]{32}', game_id):
        raise ValueError('Invalid hosted game identifier.')
    path = Path(data_dir).resolve() / 'astra.sqlite3'
    try:
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=15)) as db:
            db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN')
            row = db.execute('SELECT state FROM games WHERE id=?', (game_id,)).fetchone()
            if row is None:
                raise ValueError('Hosted game not found.')
            if len(row[0]) > MAX_RECORD_BYTES:
                raise ValueError('Hosted game record exceeds the archive size limit.')
            state = json.loads(row[0])
            if not isinstance(state, dict) or state.get('id') != game_id or state.get('status') != 'finished':
                raise ValueError('Only an identified, finished hosted game can be archived.')
            return state
    except sqlite3.Error as error:
        raise ValueError('Unable to read the hosted-game database snapshot.') from error


def _validate_record(record):
    if (not isinstance(record, dict) or set(record) != {'schema_version', 'game', 'moves', 'messages', 'evaluations'}
            or type(record['schema_version']) is not int or record['schema_version'] != SCHEMA_VERSION):
        raise ValueError('Unsupported or unexpected archive record fields.')
    meta = record['game']
    if not isinstance(meta, dict) or set(meta) != GAME_FIELDS:
        raise ValueError('Invalid archive game metadata fields.')
    if (meta['status'] != 'finished' or not isinstance(meta['id'], str) or not re.fullmatch(r'[0-9a-f]{32}', meta['id'])
            or meta['human_side'] not in ('white', 'black') or meta['astra_side'] not in ('white', 'black')
            or meta['human_side'] == meta['astra_side'] or meta['initial_fen'] != game.START_FEN
            or not _sha(meta['engine_fingerprint'])):
        raise ValueError('Invalid hosted game identity, sides, initial position or engine fingerprint.')
    for key, maximum in (('name', 128), ('model', 100), ('reasoning', 40)):
        _text(meta[key], maximum, key)
    created, updated, exported = (_timestamp(meta[key]) for key in ('created_at', 'updated_at', 'exported_at'))
    if not created <= updated <= exported:
        raise ValueError('Archive game timestamps are out of order.')
    moves, messages, evaluations = (record[key] for key in ('moves', 'messages', 'evaluations'))
    if not isinstance(moves, list) or len(moves) > 2000:
        raise ValueError('Invalid archive move list.')
    checked = {'fen': game.START_FEN, 'moves': [], 'status': 'active', 'draw_offer': None,
               'human_side': meta['human_side'], 'astra_side': meta['astra_side'], 'own_moves': 0}
    previous = created
    for index, move in enumerate(moves):
        if not isinstance(move, dict) or set(move) != MOVE_FIELDS:
            raise ValueError('Invalid archive move fields.')
        stamp = _timestamp(move['at'])
        if not previous <= stamp <= updated or move['actor'] not in ('human', 'astra'):
            raise ValueError(f'Invalid move timestamp or author at ply {index + 1}.')
        for key, maximum in (('uci', 5), ('san', 20), ('fen', 120)):
            _text(move[key], maximum, key)
        try:
            game.apply_move(checked, move['uci'], move['actor'])
        except (ValueError, KeyError, IndexError) as error:
            raise ValueError(f'Illegal archived move at ply {index + 1}.') from error
        actual = checked['moves'][-1]
        if any(move[key] != actual[key] for key in ('uci', 'san', 'fen', 'captured', 'actor')):
            raise ValueError(f'Archived move, capture or FEN disagrees at ply {index + 1}.')
        previous = stamp
    result, termination = meta['result'], meta['termination']
    if result not in ('1-0', '0-1', '1/2-1/2'):
        raise ValueError('A completed game result is required.')
    if checked['status'] == 'finished':
        if (result, termination) != (checked['result'], checked['termination']):
            raise ValueError('Recorded result disagrees with the final board.')
    elif termination == 'resignation':
        if result not in ('1-0', '0-1'):
            raise ValueError('A resignation must have a decisive result.')
    elif termination == 'agreement':
        if result != '1/2-1/2':
            raise ValueError('An agreed draw must have a drawn result.')
    elif termination == 'draw_claim':
        if result != '1/2-1/2' or not game.claimable(checked):
            raise ValueError('The displayed position does not establish the recorded draw claim; intended-move claims are not supported by this archive format.')
    else:
        raise ValueError('Unsupported or unsubstantiated recorded game ending.')
    if not isinstance(messages, list) or len(messages) > 1000:
        raise ValueError('Invalid archive message list.')
    prior_ply, prior_stamp = 0, created
    for message in messages:
        if not isinstance(message, dict) or set(message) != MESSAGE_FIELDS:
            raise ValueError('Invalid public message fields.')
        author, ply, stamp = message['author'], message['ply'], _timestamp(message['created_at'])
        if author not in ('human', 'astra') or type(ply) is not int or not prior_ply <= ply <= len(moves):
            raise ValueError('Invalid public message author or committed-position order.')
        expected_name = 'Astra' if author == 'astra' else meta['name']
        if message['name'] != expected_name:
            raise ValueError('Public message name disagrees with its author.')
        _text(message['text'], 4000, 'message text')
        lower = moves[ply - 1]['at'] if ply else created
        upper = moves[ply]['at'] if ply < len(moves) else updated
        # The recorded ply determines synchronization. Timestamps only check
        # consistency with that committed-position interval; never remap it.
        if not prior_stamp <= stamp <= updated or stamp + 0.000001 < lower or stamp - 0.000001 > upper:
            raise ValueError('Public message timestamp disagrees with its committed-position interval.')
        prior_ply, prior_stamp = ply, stamp
    own_plies = [i for i, move in enumerate(moves) if move['actor'] == 'astra']
    if not isinstance(evaluations, list) or len(evaluations) != len(own_plies):
        raise ValueError('Archive must explicitly account for each Astra move evaluation.')
    for row, ply in zip(evaluations, own_plies):
        if not isinstance(row, dict) or set(row) != {'ply', 'evaluation', 'provenance'} or type(row['ply']) is not int or row['ply'] != ply:
            raise ValueError('Invalid archive evaluation position.')
        evaluation, provenance = row['evaluation'], row['provenance']
        if evaluation is None:
            if provenance is not None:
                raise ValueError('Missing evaluation cannot claim source evidence.')
            continue
        if (not isinstance(evaluation, dict) or set(evaluation) - EVALUATION_FIELDS - {'source'}
                or not EVALUATION_FIELDS <= set(evaluation)
                or any(evaluation[key] != value for key, value in (('ply', ply), ('uci', moves[ply]['uci']), ('san', moves[ply]['san'])))
                or type(evaluation['completed_depth']) is not int or not 1 <= evaluation['completed_depth'] <= 32):
            raise ValueError('Invalid or misaligned historical evaluation.')
        score, mate, winner = evaluation['score_pawns'], evaluation['mate_in_moves'], evaluation['mate_for']
        if mate is None:
            if type(score) not in (int, float) or not math.isfinite(score) or abs(score) >= 290 or winner is not None or 'source' in evaluation:
                raise ValueError('Invalid historical numeric evaluation.')
        elif type(mate) is not int or not 1 <= mate <= 1000 or score is not None or winner not in ('astra', 'opponent'):
            raise ValueError('Invalid historical mate evaluation.')
        if 'source' in evaluation and evaluation['source'] != 'goal_probe':
            raise ValueError('Unknown historical evaluation source.')
        if provenance is not None:
            if (not isinstance(provenance, dict) or set(provenance) != PROVENANCE_FIELDS
                    or type(provenance['query_index']) is not int or provenance['query_index'] < 0
                    or provenance['hash_format'] != 'canonical-json-v1'
                    or any(not _sha(provenance[key]) for key in ('result_sha256', 'request_sha256', 'path_sha256', 'selection_sha256'))
                    or provenance['engine_source_sha256'] is not None and not _sha(provenance['engine_source_sha256'])
                    or provenance['selection_sha256'] != _hash(evaluation)):
                raise ValueError('Invalid archive evaluation provenance.')
    return record


def _provenance(state, data_dir, evaluation, ply):
    if evaluation is None:
        return None
    move = state['moves'][ply]
    before = game.START_FEN if ply == 0 else state['moves'][ply - 1]['fen']
    history = [game.START_FEN] + [m['fen'] for m in state['moves'][:ply - 1]] if ply else []
    arguments = dict(side=state['astra_side'], before=before, after=move['fen'],
                     uci=move['uci'], san=move['san'], ply=ply)
    for index in range(len(state.get('queries', [])) - 1, -1, -1):
        entry = state['queries'][index]
        if not isinstance(entry, dict) or type(entry.get('ply')) is not int or entry['ply'] != ply:
            continue
        result = _read_result(data_dir, state['id'], entry.get('path'))
        selected = (_qualifying_mate_proof(result, **arguments, history=history)
                    if evaluation.get('source') == 'goal_probe' else _qualifying(result, **arguments))
        if selected == evaluation:
            fingerprint = result.get('engine', {}).get('source_sha256') if isinstance(result.get('engine'), dict) else None
            return {'query_index': index, 'hash_format': 'canonical-json-v1',
                    'result_sha256': _hash(result), 'request_sha256': _hash(result.get('query')),
                    'path_sha256': _hash(entry['path'].replace('\\', '/')),
                    'engine_source_sha256': fingerprint if _sha(fingerprint) else None,
                    'selection_sha256': _hash(evaluation)}
    return None


def make_record(state, data_dir, *, exported_at=None):
    """Whitelist public records; derive scores only from saved historical queries."""
    try:
        if not isinstance(state, dict) or state.get('status') != 'finished':
            raise ValueError('Only finished games can be archived.')
        meta = {key: state[key] for key in GAME_FIELDS - {'exported_at', 'initial_fen'}}
        meta.update(exported_at=time.time() if exported_at is None else exported_at, initial_fen=game.START_FEN)
        moves = [{key: move[key] for key in MOVE_FIELDS} for move in state['moves']]
        if state.get('fen') != (moves[-1]['fen'] if moves else game.START_FEN):
            raise ValueError('Recorded final FEN disagrees with the archived move sequence.')
        messages = [{key: message[key] for key in MESSAGE_FIELDS - {'name'}} |
                    {'name': 'Astra' if message['author'] == 'astra' else state['name']}
                    for message in state['messages']]
        record = {'schema_version': SCHEMA_VERSION, 'game': meta, 'moves': moves, 'messages': messages,
                  'evaluations': [{'ply': i, 'evaluation': None, 'provenance': None}
                                  for i, move in enumerate(moves) if move['actor'] == 'astra']}
        _validate_record(record)
        for row in record['evaluations']:
            ply = row['ply']
            historical = dict(state, moves=state['moves'][:ply + 1], fen=moves[ply]['fen'],
                              termination=state['termination'] if ply + 1 == len(moves) else '')
            value = latest_astra_evaluation(historical, data_dir)
            row['evaluation'] = deepcopy(value)
            row['provenance'] = _provenance(state, data_dir, value, ply)
        return deepcopy(_validate_record(record))
    except (KeyError, TypeError, AttributeError, IndexError, OverflowError) as error:
        raise ValueError('Malformed finished-game archive source.') from error


def load_record(path):
    try:
        with Path(path).open('rb') as file:
            raw = file.read(MAX_RECORD_BYTES + 1)
        if len(raw) > MAX_RECORD_BYTES:
            raise ValueError('Archive record exceeds the size limit.')
        return _validate_record(json.loads(raw))
    except (KeyError, TypeError, AttributeError, IndexError, OverflowError, RecursionError) as error:
        raise ValueError('Malformed replay archive record.') from error


def record_pgn(record):
    _validate_record(record)
    meta = record['game']
    stamp = datetime.fromtimestamp(meta['created_at'], timezone.utc)
    pgn = game.pgn(dict(meta, moves=record['moves']))
    headers = {'Date': stamp.strftime('%Y.%m.%d'), 'UTCDate': stamp.strftime('%Y.%m.%d'),
               'UTCTime': stamp.strftime('%H:%M:%S'), 'Round': 'hosted-' + meta['id']}
    return '\n'.join(f'[{key} "{value}"]' for key, value in headers.items()) + '\n' + pgn


def _ending(record):
    reason = record['game']['termination']
    mapped = {'insufficient_material': 'insufficient material', 'fivefold_repetition': 'fivefold repetition',
              'seventy_five_moves': 'seventy-five-move rule'}
    if reason == 'draw_claim':
        return 'fifty-move rule' if int(record['moves'][-1]['fen'].split()[4]) >= 100 else 'threefold repetition'
    return mapped.get(reason, reason)


def _frame_evaluation(row, move, *, astra_side, mate):
    label = f"{move['number']}{'.' if astra_side == 'white' else '…'} {move['san']}"
    value = row['evaluation']
    common = {'forMove': label, 'scoreCp': None, 'depth': None, 'mateMovesRemaining': None,
              'source': 'Recorded hosted-game evidence'}
    if mate:
        return dict(common, kind='actual_checkmate', label='Checkmate', detail=f'{label} · {astra_side.title()} wins',
                    note='The recorded board establishes checkmate; no search score is needed.')
    if value is None:
        return dict(common, kind='not_recorded', label='No recorded evaluation', detail=f'For {label} · No qualifying saved evidence',
                    note='No evaluation has been filled in or recalculated.')
    common['depth'] = value['completed_depth']
    if value['mate_in_moves'] is None:
        return dict(common, kind='search_estimate', scoreCp=value['score_pawns'] * 100,
                    label=f"{value['score_pawns']:+.2f} pawns",
                    detail=f"For {label} · Pre-move search · Depth {value['completed_depth']} plies · Positive favors {astra_side.title()}",
                    note='Historical evaluation of the selected move, calculated before it was played. No new search was run.')
    winner = astra_side if value['mate_for'] == 'astra' else ('white' if astra_side == 'black' else 'black')
    proof = value.get('source') == 'goal_probe'
    return dict(common, kind='forced_mate_proof' if proof else 'search_mate', mateMovesRemaining=value['mate_in_moves'],
                label=f"{winner.title()} mates in {value['mate_in_moves']}",
                detail=f"For {label} · {'Completed goal proof' if proof else 'Recorded mate search'} · {winner.title()} turns remaining",
                note='Count starts after this displayed move, with the human to move. It assumes the mating side follows its forcing play against best defense. A proof representative is not a complete strategy tree.')


def build_archive(record, output):
    """Rebuild from sanitized JSON alone, reusing the existing replay animations."""
    try:
        _validate_record(record)
    except (KeyError, TypeError, AttributeError, IndexError, OverflowError) as error:
        raise ValueError('Malformed replay archive record.') from error
    spec = importlib.util.spec_from_file_location('_astra_hosted_replay_builder', REPO_ROOT / 'build_replay.py')
    builder = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(builder)
    except ModuleNotFoundError as error:
        if error.name == 'chess':
            raise ValueError('Offline replay builds require the rules-only chess==1.11.2 dependency; install requirements-replay.txt or supply its existing directory on PYTHONPATH.') from error
        raise
    meta = record['game']
    with tempfile.TemporaryDirectory(prefix='astra-replay-') as directory:
        folder = Path(directory)
        pgn_path = folder / ('hosted-' + meta['id'] + '.pgn')
        pgn_path.write_text(record_pgn(record), encoding='utf-8')
        metadata_path = folder / 'metadata.json'
        metadata_path.write_text(_json({'hosted-' + meta['id']: {'model': 'Astra',
            'thinkingLevel': meta['reasoning'].title(), 'playerSide': meta['astra_side']}}), encoding='utf-8')
        builder.ROOT, builder.REPLAY_METADATA = APP_ROOT, metadata_path
        temporary_page = folder / 'replay.html'
        builder.build(pgn_path, temporary_page, subtitle='Hosted service game · ' + meta['model'], ending=_ending(record))
        page = temporary_page.read_text(encoding='utf-8')
    marker = '<script id="replay-data" type="application/json">'
    if page.count(marker) != 1:
        raise ValueError('Replay template must contain one replay-data JSON element.')
    start = page.index(marker) + len(marker)
    end = page.index('</script>', start)
    data = json.loads(page[start:end])
    frames = data['frames']
    if len(frames) != len(record['moves']) + 1:
        raise ValueError('Replay builder frame count disagrees with the archive.')
    for index, move in enumerate(record['moves']):
        if (frames[index + 1]['move']['uci'] != move['uci']
                or frames[index + 1]['move']['san'] != move['san']
                or builder.normalized_fen(frames[index + 1]['fen']) != builder.normalized_fen(move['fen'])):
            raise ValueError('Replay builder position disagrees with the archive.')
    for frame in frames:
        frame['evaluation'] = None
    for row in record['evaluations']:
        frame = frames[row['ply'] + 1]
        frame['evaluation'] = _frame_evaluation(row, frame['move'], astra_side=meta['astra_side'], mate=frame['mate'])
    data['evaluations'] = {'perspective': meta['astra_side'], 'recordedChoices': len(record['evaluations']),
        'description': f"Saved evidence for Astra's actual moves. Positive pawn scores favor {meta['astra_side'].title()}. Human-move frames have no new evaluation; missing evidence stays missing."}
    data['messages'] = deepcopy(record['messages'])
    data['archive'] = {'gameId': meta['id'], 'createdAt': meta['created_at'], 'exportedAt': meta['exported_at'],
        'model': meta['model'], 'reasoning': meta['reasoning'], 'source': 'hosted_service', 'messageCount': len(record['messages'])}
    page = page[:start] + _json(data).replace('<', '\\u003c') + page[end:]
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(page, encoding='utf-8')
    return output
