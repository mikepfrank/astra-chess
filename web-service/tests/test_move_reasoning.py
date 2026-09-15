"""Owner-selected next-move effort: persistence, boundaries and no worker effects."""
from contextlib import ExitStack, closing
import copy
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid

from fastapi.testclient import TestClient

from astra_web.app import create_app
from astra_web import chess_game as game
from astra_web.config import Config
from astra_web.player_profiles import game_player_binding, runtime_profile_for_binding
from astra_web.store import Store


class MoveReasoningTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        folder = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.config = Config(data_dir=Path(folder), origin='http://testserver',
            model_profile='openrouter-glm', persona='arcturus', player_mode='disabled',
            secure_cookies=False, smtp_host='', smtp_from='')
        self.app = create_app(self.config)
        self.client = self.stack.enter_context(TestClient(self.app))
        self.register(self.client, 'Preference owner')
        response = self.client.post('/api/games', json={'side': 'white'})
        self.assertEqual(response.status_code, 201)
        self.game_id = response.json()['id']
        self.store = self.app.state.store
        self.url = f'/api/games/{self.game_id}/actions'

    def register(self, client, name):
        response = client.post('/api/auth/register', json={'name': name},
                               headers={'Origin': self.config.origin})
        self.assertEqual(response.status_code, 200)
        client.headers.update({'Origin': self.config.origin,
                               'X-CSRF-Token': response.json()['csrf_token']})

    def payload(self, reasoning='high', **extra):
        return {'action': 'set_move_reasoning', 'reasoning': reasoning,
            'version': self.store.get(self.game_id)['version'], 'request_id': uuid.uuid4().hex, **extra}

    def test_default_and_selection_persist_without_changing_game_identity_or_scheduling(self):
        snapshot = self.client.get(f'/api/games/{self.game_id}').json()
        self.assertEqual(snapshot['move_reasoning'], 'max')
        self.assertEqual(snapshot['move_reasoning_options'], ['high', 'max'])
        baseline = self.store.get(self.game_id)
        with patch.object(self.app.state.supervisor, 'schedule') as schedule:
            response = self.client.post(self.url, json=self.payload())
        self.assertEqual(response.status_code, 200, response.text)
        schedule.assert_not_called()
        self.assertEqual(response.json()['move_reasoning'], 'high')
        state = Store(self.config).get(self.game_id)
        self.assertEqual(state['move_reasoning'], 'high')
        for key in ('reasoning', 'model', 'player_profile', 'player_persona', 'player_prompt',
                    'thread_id', 'moves', 'messages', 'fen', 'own_moves', 'clock_used',
                    'active_started', 'clock_events', 'worker', 'status'):
            self.assertEqual(state[key], baseline[key], key)
        self.assertEqual(self.app.state.supervisor.tasks, {})
        self.assertEqual(self.app.state.supervisor.rerun, set())
        binding = game_player_binding(state, self.config)
        self.assertEqual(runtime_profile_for_binding(binding, self.config,
            response_kind='move', move_reasoning=state['move_reasoning']).reasoning, 'high')
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM budget').fetchone()[0], 0)

    def test_version_conflict_and_duplicate_request_do_not_override_newer_selection(self):
        request = self.payload('high')
        first = self.client.post(self.url, json=request)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(self.client.post(self.url, json={**request, 'request_id': uuid.uuid4().hex}).status_code, 409)
        self.assertEqual(self.client.post(self.url, json={**request, 'reasoning': 'max'}).status_code, 409)
        self.assertEqual(self.client.post(self.url, json=self.payload('max')).status_code, 200)
        current = self.store.get(self.game_id)
        retried = self.client.post(self.url, json=request)
        self.assertEqual(retried.status_code, 200)
        self.assertEqual(retried.json()['move_reasoning'], 'max')
        self.assertEqual(self.store.get(self.game_id), current)

    def test_owner_csrf_origin_and_unrecognized_values_are_rejected(self):
        baseline = self.store.get(self.game_id)
        for reasoning in ('ultra', 'HIGH', '', True, 1, [], {}, None):
            response = self.client.post(self.url, json=self.payload(reasoning))
            self.assertEqual(response.status_code, 400, response.text)
        for changes in ({'text': 'Extra text'}, {'move': 'e2e4'}, {'model': 'other'},
                        {'version': True}, {'action': 'move', 'move': 'e2e4'}):
            self.assertEqual(self.client.post(self.url, json=self.payload(**changes)).status_code, 400)
        self.assertEqual(self.client.post(self.url, json=self.payload(),
            headers={'X-CSRF-Token': 'incorrect'}).status_code, 403)
        self.assertEqual(self.client.post(self.url, json=self.payload(),
            headers={'Origin': 'https://outsider.invalid'}).status_code, 403)
        with closing(TestClient(self.app)) as outsider:
            self.assertEqual(outsider.post(self.url, json=self.payload(),
                headers={'Origin': self.config.origin}).status_code, 403)
            self.register(outsider, 'Different player')
            self.assertEqual(outsider.post(self.url, json=self.payload()).status_code, 404)
        self.assertEqual(self.store.get(self.game_id), baseline)

    def test_running_and_suspended_selection_do_not_change_clocks_or_start_work(self):
        self.store.mutate(self.game_id, lambda s: s.update(active_started=time.time() - 7,
            active_deadline=time.time() + 100, clock_used=22,
            worker={'state': 'thinking', 'message': 'Existing response'}))
        baseline = self.store.get(self.game_id)
        with patch.object(self.app.state.supervisor, 'schedule') as schedule:
            self.assertEqual(self.client.post(self.url, json=self.payload()).status_code, 200)
            current = self.store.get(self.game_id)
            for key in ('clock_used', 'active_started', 'active_deadline', 'clock_events', 'worker'):
                self.assertEqual(current[key], baseline[key])
            self.store.mutate(self.game_id, lambda s: s.update(status='suspended', active_started=None))
            response = self.client.post(self.url, json=self.payload('max'))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['status'], 'suspended')
        schedule.assert_not_called()
        self.store.mutate(self.game_id, lambda s: game.finish(s, '1/2-1/2', 'agreement'))
        self.assertEqual(self.client.post(self.url, json=self.payload('high')).status_code, 400)

    def test_historical_high_profile_and_astra_keep_their_original_policy(self):
        original = self.store.get(self.game_id)
        for version in (2, 3):
            legacy = copy.deepcopy(original)
            legacy['reasoning'] = 'high'
            legacy['player_profile'].update(version=version, reasoning='high', max_output_tokens=8192)
            if version == 2:
                legacy['player_profile'].update(context_window=128000, compact_limit=80000)
            self.store.mutate(self.game_id, lambda s: s.update(legacy))
            response = self.client.get(f'/api/games/{self.game_id}').json()
            self.assertEqual(response['move_reasoning_options'], [])
            self.assertEqual(response['move_reasoning'], 'high')
            baseline = self.store.get(self.game_id)
            self.assertEqual(self.client.post(self.url, json=self.payload('max')).status_code, 400)
            self.assertEqual(self.store.get(self.game_id), baseline)
        astra = game.new_game({'id': 'fixture', 'name': 'Astra fixture'}, 'white', Config())
        self.assertEqual(game.snapshot(astra)['move_reasoning_options'], [])
        self.assertEqual(game.snapshot(astra)['move_reasoning'], 'ultra')
        with self.assertRaises(ValueError):
            runtime_profile_for_binding(game_player_binding(astra, Config()), Config(),
                                         response_kind='move', move_reasoning='high')


if __name__ == '__main__':
    unittest.main()
