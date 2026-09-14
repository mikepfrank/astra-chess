"""Saved public replay identity survives offline rebuilds without private context."""
from copy import deepcopy
from html import escape
import json
from pathlib import Path
import tempfile
import unittest

from astra_web import chess_game as game
from astra_web import replay_archive as archive
from astra_web.config import Config
from test_replay_archive import EmbeddedReplay


class ReplayIdentityTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)

    def state(self, human_side='white'):
        config = Config(data_dir=self.root, player_mode='disabled',
                        model_profile='openrouter-glm', persona='arcturus')
        state = game.new_game({'id': 'private-user-id', 'name': 'Snapshot opponent'}, human_side, config)
        for index, uci in enumerate(('e2e4', 'd7d5', 'e4d5', 'd8d5')):
            actor = 'human' if game.side_to_move(state) == human_side else 'astra'
            game.apply_move(state, uci, actor)
            state['moves'][index]['at'] = 1001.0 + index
        state.update(status='finished', result='0-1', termination='resignation',
                     created_at=1000.0, updated_at=1006.0)
        state['messages'] = [
            {'author': 'human', 'ply': 0, 'text': 'Astra was my previous opponent.', 'created_at': 1000.5},
            {'author': 'astra', 'ply': 4, 'text': 'Our saved conversation.', 'created_at': 1005.0},
        ]
        return state

    def record(self, state):
        return archive.make_record(state, self.root, exported_at=2000.0)

    def build(self, record):
        path = self.root / 'replay.html'
        archive.build_archive(record, path)
        html = path.read_text(encoding='utf-8')
        return html, EmbeddedReplay(html).value()

    def test_arcturus_identity_is_consistent_for_both_colors_and_preserves_saved_content(self):
        for human_side in ('white', 'black'):
            with self.subTest(human_side=human_side):
                state = self.state(human_side)
                before = deepcopy(state)
                record = self.record(state)
                self.assertEqual(state, before)
                self.assertEqual(record['schema_version'], 2)
                self.assertEqual(record['game']['player_name'], 'Arcturus')
                self.assertEqual(record['messages'][-1]['name'], 'Arcturus')
                html, data = self.build(record)
                self.assertIn('<h1>Arcturus (Max) vs. Snapshot opponent</h1>', html)
                self.assertIn('CHESS · HOSTED GAME REPLAY', html)
                self.assertNotIn('ASTRA CHESS · HOSTED GAME REPLAY', html)
                self.assertEqual(data['playerSide'], state['astra_side'])
                self.assertEqual(data['displayNames'][state['astra_side']], 'Arcturus')
                self.assertEqual(data['displayNames'][human_side], state['name'])
                self.assertEqual(data['playerName'], 'Arcturus')
                self.assertEqual(data['archive']['playerName'], 'Arcturus')
                self.assertEqual(data['headers'][state['astra_side'].title()], 'Arcturus')
                self.assertEqual(data['headers']['Event'], 'Arcturus Chess Public Beta')
                self.assertEqual(data['headers']['Site'], 'Arcturus Chess')
                self.assertEqual(data['headers']['Model'], state['model'])
                self.assertEqual(data['headers']['Reasoning'], 'max')
                self.assertNotIn('AstraModel', data['headers'])
                self.assertNotIn('AstraReasoning', data['headers'])
                self.assertEqual(data['pgn'], archive.record_pgn(record))
                self.assertTrue(data['evaluations']['description'].startswith("Saved evidence for Arcturus's actual moves."))
                self.assertEqual(data['messages'], record['messages'])
                self.assertIn('Astra was my previous opponent.', [m['text'] for m in data['messages']])
                self.assertEqual([f['move']['uci'] for f in data['frames'][1:]], [m['uci'] for m in state['moves']])
                self.assertEqual(len(data['frames'][-1]['pieces']), 30)
                self.assertEqual({p['id'] for p in data['frames'][-1]['pieces'] if p['square'] == 'd5'}, {'q-d8'})
                for private in ('player_prompt', 'player_persona', 'prompt_sha256', 'private-user-id'):
                    self.assertNotIn(private, json.dumps(record))

    def test_legacy_records_retain_strict_schema_and_astra_fallback(self):
        state = self.state()
        state.pop('player_persona')
        state.pop('player_profile')
        state.pop('player_prompt')
        record = self.record(state)
        self.assertEqual(record['game']['player_name'], 'Astra')
        record['schema_version'] = 1
        record['game'].pop('player_name')
        path = self.root / 'legacy.json'
        path.write_text(json.dumps(record), encoding='utf-8')
        loaded = archive.load_record(path)
        self.assertEqual(loaded, record)
        html, data = self.build(loaded)
        self.assertIn('<h1>Astra (Max) vs. Snapshot opponent</h1>', html)
        self.assertEqual(data['displayNames']['black'], 'Astra')
        self.assertEqual(data['headers']['Black'], 'Astra')
        self.assertEqual(data['messages'][-1]['name'], 'Astra')
        self.assertIn('AstraModel', data['headers'])
        loaded['game']['player_name'] = 'Arcturus'
        with self.assertRaisesRegex(ValueError, 'metadata fields'):
            archive.record_pgn(loaded)

    def test_profile_fallback_and_frozen_record_do_not_follow_later_persona_or_chat(self):
        state = self.state()
        state.pop('player_persona')
        self.assertEqual(self.record(state)['game']['player_name'], 'GLM 5.3 Flash')
        state = self.state()
        record = self.record(state)
        path = self.root / 'frozen.json'
        path.write_text(json.dumps(record), encoding='utf-8')
        first_html, first = self.build(record)
        state['player_persona']['display_name'] = 'Later persona'
        state['messages'].append({'author': 'human', 'ply': 4, 'text': 'Later private message', 'created_at': 1005.5})
        rebuilt_html, rebuilt = self.build(archive.load_record(path))
        self.assertEqual(rebuilt, first)
        self.assertEqual(rebuilt_html, first_html)
        self.assertNotIn('Later private message', rebuilt_html)
        self.assertNotIn('Later persona', rebuilt_html)

    def test_player_name_is_escaped_in_html_json_and_pgn(self):
        name = 'Arcturus "quoted" \\ </script><script>window.INJECTED=true</script> & 星'
        state = self.state()
        state['player_persona']['display_name'] = name
        record = self.record(state)
        html, data = self.build(record)
        self.assertIn('<h1>' + escape(name, quote=True) + ' (Max) vs. Snapshot opponent</h1>', html)
        self.assertNotIn('</script><script>window.INJECTED', html)
        self.assertEqual(data['displayNames']['black'], name)
        self.assertEqual(data['playerName'], name)
        self.assertEqual(data['messages'][-1]['name'], name)
        escaped_pgn = name.replace('\\', '\\\\').replace('"', '\\"')
        self.assertIn('[Black "' + escaped_pgn + '"]', data['pgn'])

    def test_invalid_or_disagreeing_public_identity_is_rejected_before_build(self):
        for name in (None, {}, '', ' ', 'x' * 201, 'Arcturus\nInjected', 'Arcturus\x7f', '\ud800'):
            with self.subTest(name=repr(name)):
                record = self.record(self.state())
                record['game']['player_name'] = name
                with self.assertRaises(ValueError):
                    archive.record_pgn(record)
        record = self.record(self.state())
        record['messages'][-1]['name'] = 'Astra'
        with self.assertRaisesRegex(ValueError, 'name disagrees'):
            archive.record_pgn(record)
        record = self.record(self.state())
        record['game'].pop('player_name')
        with self.assertRaisesRegex(ValueError, 'metadata fields'):
            archive.record_pgn(record)


if __name__ == '__main__':
    unittest.main()
