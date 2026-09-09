"""Hosted archive records are validated public snapshots, never live game edits."""
from copy import deepcopy
from contextlib import closing
from html.parser import HTMLParser
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from astra_web import chess_game as game
from astra_web import replay_archive as archive
from astra_web.config import Config
from astra_web.store import Store


class EmbeddedReplay(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.collecting, self.chunks = False, []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == 'script' and dict(attrs).get('id') == 'replay-data':
            self.collecting = True

    def handle_endtag(self, tag):
        if tag == 'script':
            self.collecting = False

    def handle_data(self, data):
        if self.collecting:
            self.chunks.append(data)

    def value(self):
        return json.loads(''.join(self.chunks))


class ReplayArchiveTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.directory = Path(self.folder.name)
        self.config = Config(data_dir=self.directory / 'service', player_mode='disabled')
        self.config.validate()
        self.state = game.new_game({'id': 'private-user-id', 'name': 'Fixture player'}, 'white', self.config)
        for index, uci in enumerate(('f2f3', 'e7e5', 'g2g4', 'd8h4')):
            game.apply_move(self.state, uci, 'astra' if game.side_to_move(self.state) == 'black' else 'human')
            self.state['moves'][index]['at'] = 1001.0 + index
        self.state.update(created_at=1000.0, updated_at=1006.0, last_human_activity=1006.0)
        self.state['messages'] = [
            {'id': 'private-message-0', 'author': 'human', 'ply': 0, 'text': 'Ready to play.', 'created_at': 1000.5},
            {'id': 'private-message-1', 'author': 'astra', 'ply': 1, 'text': 'Let me consider that move.', 'created_at': 1001.5},
            {'id': 'private-message-2', 'author': 'astra', 'ply': 4, 'text': 'That is checkmate.', 'created_at': 1004.5},
            {'id': 'private-message-3', 'author': 'human', 'ply': 4, 'text': 'How did the engine help?', 'created_at': 1005.0},
        ]

    def record(self, state=None):
        return archive.make_record(self.state if state is None else state,
                                   self.config.data_dir, exported_at=2000.0)

    def write_record(self, record, name='record.json'):
        path = self.directory / name
        path.write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')
        return path

    def build(self, record, name='archive.html'):
        path = self.directory / name
        self.assertEqual(archive.build_archive(record, path), path)
        return path.read_text(encoding='utf-8')

    def test_short_checkmate_archive_whitelists_public_fields_and_preserves_message_order(self):
        secret = 'DO-NOT-ARCHIVE-INTERNAL-ONLY'
        self.state.update(thread_id=secret, email=secret, memory=secret, api_key=secret,
                          worker={'state': 'error', 'message': secret})
        self.state['moves'][0]['private_note'] = secret
        self.state['messages'][0]['private_note'] = secret
        before = deepcopy(self.state)
        record = self.record()
        self.assertEqual(self.state, before)
        self.assertEqual(set(record), {'schema_version', 'game', 'moves', 'messages', 'evaluations'})
        self.assertEqual(record['game']['result'], '0-1')
        self.assertEqual(record['game']['termination'], 'checkmate')
        self.assertEqual(record['game']['initial_fen'], game.START_FEN)
        self.assertEqual([m['uci'] for m in record['moves']], ['f2f3', 'e7e5', 'g2g4', 'd8h4'])
        self.assertEqual(record['moves'][-1]['san'], 'Qh4#')
        self.assertEqual([m['text'] for m in record['messages']], [m['text'] for m in before['messages']])
        self.assertTrue(all(set(m) == {'author', 'name', 'ply', 'text', 'created_at'} for m in record['messages']))
        self.assertEqual([m['name'] for m in record['messages']], ['Fixture player', 'Astra', 'Astra', 'Fixture player'])
        encoded = json.dumps(record)
        for private in (secret, 'private-user-id', 'private-message-0'):
            self.assertNotIn(private, encoded)

    def test_invalid_move_and_result_evidence_is_rejected(self):
        changes = {
            'unfinished': lambda s: s.update(status='active'),
            'unfinished result': lambda s: s.update(result='*'),
            'wrong winner': lambda s: s.update(result='1-0'),
            'wrong ending': lambda s: s.update(termination='agreement'),
            'illegal UCI': lambda s: s['moves'][0].update(uci='f2f5'),
            'wrong SAN': lambda s: s['moves'][1].update(san='e6'),
            'wrong recorded FEN': lambda s: s['moves'][1].update(fen=game.START_FEN),
            'wrong final FEN': lambda s: s.update(fen=game.START_FEN),
            'wrong actor': lambda s: s['moves'][1].update(actor='human'),
            'wrong capture': lambda s: s['moves'][0].update(captured='p'),
        }
        for label, change in changes.items():
            with self.subTest(case=label):
                state = deepcopy(self.state)
                change(state)
                with self.assertRaises(ValueError):
                    self.record(state)

    def test_message_author_ply_and_chronological_mismatches_are_rejected(self):
        changes = {
            'internal author': lambda s: s['messages'][0].update(author='system'),
            'negative ply': lambda s: s['messages'][0].update(ply=-1),
            'future ply': lambda s: s['messages'][0].update(ply=5),
            'boolean ply': lambda s: s['messages'][0].update(ply=True),
            'ply moves backward': lambda s: s['messages'][-1].update(ply=1),
            'timestamp moves backward': lambda s: s['messages'][-1].update(created_at=1000.0),
            'timestamp exceeds committed ply interval': lambda s: s['messages'][1].update(created_at=1002.5),
            'nontext message': lambda s: s['messages'][0].update(text={'private': 'object'}),
            'nonfinite timestamp': lambda s: s['messages'][0].update(created_at=float('nan')),
        }
        for label, change in changes.items():
            with self.subTest(case=label):
                state = deepcopy(self.state)
                change(state)
                with self.assertRaises(ValueError):
                    self.record(state)

    def test_saved_record_roundtrip_rebuilds_identical_embedded_data_and_escapes_script_text(self):
        payload = '</script><script>window.ARCHIVE_INJECTED=true</script>\n<& exact text \u2028'
        self.state['messages'][-1]['text'] = payload
        record = self.record()
        loaded = archive.load_record(self.write_record(record))
        self.assertEqual(loaded, record)
        original = self.build(record, 'original.html')
        rebuilt = self.build(loaded, 'rebuilt.html')
        first_data = EmbeddedReplay(original).value()
        self.assertEqual(first_data, EmbeddedReplay(rebuilt).value())
        self.assertNotIn('</script><script>window.ARCHIVE_INJECTED', original)
        self.assertIn(payload, [message['text'] for message in first_data['messages']])
        self.assertEqual(len(first_data['frames']), 5)

    def test_saved_record_cannot_introduce_private_or_unvalidated_fields(self):
        for label, change in {
            'private game field': lambda r: r['game'].update(email='private@example.invalid'),
            'private message field': lambda r: r['messages'][0].update(session_token='private-token'),
            'unknown top field': lambda r: r.update(memory='private-memory'),
            'tampered move': lambda r: r['moves'][0].update(uci='f2f5'),
            'tampered result': lambda r: r['game'].update(result='1-0'),
        }.items():
            with self.subTest(case=label):
                record = self.record()
                change(record)
                with self.assertRaises(ValueError):
                    archive.load_record(self.write_record(record))
                with self.assertRaises(ValueError):
                    archive.build_archive(record, self.directory / 'invalid.html')

    def test_evaluations_use_each_historical_astra_slice_without_carrying_onto_opponent_frame(self):
        seen = []

        def evaluate(state, data_dir):
            seen.append(deepcopy(state))
            if len(state['moves']) == 2:
                chosen = state['moves'][-1]
                return {'score_pawns': 0.25, 'mate_in_moves': None, 'mate_for': None,
                        'ply': 1, 'uci': chosen['uci'], 'san': chosen['san'], 'completed_depth': 4}
            return None

        with patch.object(archive, 'latest_astra_evaluation', side_effect=evaluate):
            record = self.record()
        self.assertEqual([len(s['moves']) for s in seen], [2, 4])
        self.assertEqual(seen[0]['fen'], self.state['moves'][1]['fen'])
        self.assertNotEqual(seen[0]['termination'], 'checkmate')
        self.assertEqual(seen[1]['termination'], 'checkmate')
        self.assertEqual([row['ply'] for row in record['evaluations']], [1, 3])
        self.assertEqual(record['evaluations'][0]['evaluation']['score_pawns'], 0.25)
        self.assertIsNone(record['evaluations'][1]['evaluation'])
        data = EmbeddedReplay(self.build(record)).value()
        self.assertIsNone(data['frames'][1].get('evaluation'))
        self.assertIsNone(data['frames'][3].get('evaluation'))
        self.assertIsNotNone(data['frames'][2].get('evaluation'))

    def test_saved_forced_goal_proof_keeps_its_source_and_post_move_distance(self):
        before, chosen = self.state['moves'][0]['fen'], self.state['moves'][1]
        goal = {'type': 'checkmate', 'side': 'black'}
        result = {
            'kind': 'goal_probe', 'start_fen': chosen['fen'], 'goal': goal,
            'status': 'forced', 'proof_status': 'forced', 'proof_completed_depth': 6,
            'horizon_plies': 8, 'history_supplied': True,
            'position_history_fens': [game.START_FEN, before],
            'diagnostics': {'proof_budget_exhausted': False}, 'lines': [],
            'engine': {'source_sha256': self.state['engine_fingerprint']},
            'query': {'mode': 'probe', 'fen': before, 'after': [chosen['uci']], 'depth': 8,
                      'history_fens': [game.START_FEN], 'goal': goal},
        }
        relative = Path('games') / self.state['id'] / 'queries' / 'fixture.result.json'
        path = self.config.data_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result), encoding='utf-8')
        self.state['queries'] = [{'ply': 1, 'path': str(relative)}]
        record = self.record()
        evaluation = record['evaluations'][0]['evaluation']
        self.assertEqual(evaluation['source'], 'goal_probe')
        self.assertEqual(evaluation['mate_in_moves'], 3)
        self.assertEqual(evaluation['mate_for'], 'astra')
        self.assertIsNone(evaluation['score_pawns'])
        self.assertEqual(evaluation['completed_depth'], 6)
        self.assertIsNotNone(record['evaluations'][0]['provenance'])
        self.assertIsNone(record['evaluations'][1]['evaluation'])
        self.assertNotIn(str(self.config.data_dir), json.dumps(record))
        self.assertNotIn(str(relative), json.dumps(record))
        saved = self.write_record(record, 'goal-proof.record.json')
        tampered = deepcopy(record)
        tampered['evaluations'][0]['evaluation']['mate_in_moves'] = 4
        with self.assertRaises(ValueError):
            archive.load_record(self.write_record(tampered, 'tampered-proof.record.json'))
        path.write_text('malformed evidence', encoding='utf-8')
        self.assertIsNone(self.record()['evaluations'][0]['evaluation'])
        self.assertEqual(record['evaluations'][0]['evaluation'], evaluation)
        self.assertEqual(archive.load_record(saved), record)
        self.build(archive.load_record(saved), 'proof-after-evidence-unavailable.html')

    def test_readonly_snapshot_and_frozen_archive_ignore_later_postgame_chat(self):
        store = Store(self.config)
        store.create(self.state)

        def dump():
            with closing(sqlite3.connect(self.config.db_path)) as db:
                return list(db.iterdump())

        before = dump()
        snapshot = archive.read_game(self.config.data_dir, self.state['id'])
        record = self.record(snapshot)
        self.assertEqual(dump(), before)
        saved = json.dumps(record, sort_keys=True)
        store.mutate(self.state['id'], lambda s: game.message(s, 'human', 'A later private conversation message'))
        self.assertEqual(len(snapshot['messages']), 4)
        self.assertEqual(json.dumps(record, sort_keys=True), saved)
        snapshot['messages'].append({'author': 'human', 'text': 'Mutated caller copy', 'ply': 4, 'created_at': 2001.0})
        self.assertEqual(json.dumps(record, sort_keys=True), saved)
        loaded = archive.load_record(self.write_record(record))
        html = self.build(loaded)
        self.assertNotIn('A later private conversation message', html)
        self.assertNotIn('Mutated caller copy', html)


if __name__ == '__main__':
    unittest.main()
