"""Private account/opponent scores derived from game results, never transcript memory."""
from contextlib import ExitStack, closing
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import uuid

from fastapi.testclient import TestClient

from astra_web.app import create_app
from astra_web import chess_game as game
from astra_web.config import Config
from astra_web.store import Store
from astra_web.supervisor import Supervisor


def expected(human=0, ai=0, draws=0, *, current=False):
    return dict(completed_games=human + ai + draws, human_wins=human,
        ai_wins=ai, draws=draws, human_points=human + draws / 2,
        ai_points=ai + draws / 2, includes_current_game=current)


class Fixture:
    def configure(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        folder = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.config = Config(data_dir=Path(folder), origin='http://testserver',
            model_profile='openrouter-glm', persona='arcturus', player_mode='disabled',
            max_games_per_user=30, secure_cookies=False, smtp_host='', smtp_from='')
        self.config.validate()
        self.store = Store(self.config)

    def new(self, side='white', *, user_id='owner', result=None, config=None):
        state = game.new_game({'id': user_id, 'name': 'Same display name'}, side,
                              config or self.config)
        if result:
            game.finish(state, result, 'fixture')
        return state

    def save(self, *args, **kwargs):
        state = self.new(*args, **kwargs)
        self.store.create(state)
        return state


class MatchupStoreTests(Fixture, unittest.TestCase):
    def setUp(self):
        self.configure()

    def test_both_colors_results_points_and_readonly_historical_initialization(self):
        for side in ('white', 'black'):
            for result in ('1-0', '0-1', '1/2-1/2'):
                self.save(side, result=result)
        current = self.save()
        before = self.store.list()
        with self.store.connection() as db:
            events_before = db.execute('SELECT count(*) FROM events').fetchone()[0]
        self.assertEqual(self.store.matchup_record(current), expected(2, 2, 2))
        self.assertEqual(Store(self.config).matchup_record(current), expected(2, 2, 2))
        self.assertEqual(self.store.list(), before)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM events').fetchone()[0], events_before)

    def test_identity_uses_account_persona_and_model_not_names_versions_or_effort(self):
        current = self.save()
        for version in (2, 3, 4):
            state = self.new(result='0-1')
            state['player_profile'].update(version=version, reasoning='high' if version < 4 else 'max')
            state['player_persona'].update(version=version, display_name='Renamed same persona')
            state['name'] = 'Earlier human display name'
            state['player_prompt'] = 'Historical prompt does not affect opponent identity.'
            self.store.create(state)
        routed = self.new(result='1/2-1/2')
        routed['player_profile'].pop('canonical_model')
        routed['player_profile']['model'] = 'z-ai/glm-5.3-flash:floor'
        self.store.create(routed)
        self.save(user_id='different owner', result='1-0')
        other_persona = self.new(result='1-0')
        other_persona['player_persona']['name'] = 'another-persona'
        self.store.create(other_persona)
        other_model = self.new(result='1-0')
        other_model['player_profile']['canonical_model'] = 'z-ai/different-model'
        self.store.create(other_model)
        self.assertEqual(self.store.matchup_record(current), expected(ai=3, draws=1))

    def test_unfinished_invalid_results_and_invalid_sides_are_not_counted(self):
        current = self.save()
        variants = [dict(status='active', result='1-0'),
                    dict(status='suspended', result='0-1'),
                    dict(status='finished', result='*'),
                    dict(status='finished', result='abandoned'),
                    dict(status='finished', result='1-0', human_side='unknown'),
                    dict(status='finished', result='1-0', astra_side='white')]
        for changes in variants:
            state = self.new()
            state.update(changes)
            self.store.create(state)
        self.assertEqual(self.store.matchup_record(current), expected())

    def test_completion_retry_and_public_share_do_not_duplicate_counts(self):
        current = self.save()
        self.assertEqual(self.store.matchup_record(current), expected())
        for _ in range(2):
            current = self.store.mutate(current['id'], lambda s: game.finish(s, '0-1', 'resignation'),
                request_id='same-resignation', body={'action': 'resign'})
        self.store.audit(current['id'], 'worker_error', {'reason': 'fixture'})
        self.store.audit(current['id'], 'worker_completed', {})
        self.store.share(current['id'], {'result': current['result']})
        self.assertEqual(self.store.matchup_record(current), expected(ai=1, current=True))
        self.assertEqual(self.store.matchup_record(current), expected(ai=1, current=True))

    def test_current_snapshot_consistency_and_other_game_finishing_are_fresh(self):
        current = self.save()
        other = self.save('black')
        self.store.mutate(other['id'], lambda s: game.finish(s, '0-1', 'resignation'))
        self.assertEqual(self.store.matchup_record(current), expected(human=1))
        finished = self.store.mutate(current['id'], lambda s: game.finish(s, '0-1', 'resignation'))
        # An already-read active board must not suddenly include its own result.
        self.assertEqual(self.store.matchup_record(current), expected(human=1))
        self.assertEqual(self.store.matchup_record(finished), expected(human=1, ai=1, current=True))

    def test_legacy_glm_stays_separate_and_bare_astra_uses_recorded_model(self):
        current = self.save()
        legacy_glm = self.new(result='0-1')
        legacy_glm.pop('player_persona')
        legacy_glm.pop('player_prompt')
        legacy_glm['player_profile'].pop('persona')
        self.store.create(legacy_glm)
        self.assertEqual(self.store.matchup_record(current), expected())
        self.assertEqual(self.store.matchup_record(legacy_glm), expected(ai=1, current=True))
        astra_config = Config(data_dir=self.config.data_dir)
        legacy_astra = self.new(result='1-0', config=astra_config)
        for key in ('player_persona', 'player_prompt', 'player_profile'):
            legacy_astra.pop(key)
        self.store.create(legacy_astra)
        modern_astra = self.save(config=astra_config)
        self.assertEqual(self.store.matchup_record(modern_astra), expected(human=1))
        self.assertEqual(self.store.matchup_record(current), expected())

    def test_unidentifiable_or_unsaved_games_do_not_create_totals(self):
        self.save(result='1-0')
        current = self.new(user_id='missing')
        self.assertEqual(self.store.matchup_record(current), expected())
        current['user_id'] = 'owner'
        for key, value in (('user_id', None), ('player_profile', []),
                           ('player_persona', {'display_name': 'Arcturus'})):
            invalid = copy.deepcopy(current)
            invalid[key] = value
            self.assertEqual(self.store.matchup_record(invalid), expected())


class MatchupApiTests(Fixture, unittest.TestCase):
    def setUp(self):
        self.configure()
        self.app = create_app(self.config)
        self.client = self.stack.enter_context(TestClient(self.app))
        self.register(self.client, 'Score owner')
        created = self.client.post('/api/games', json={'side': 'white'})
        self.assertEqual(created.status_code, 201)
        self.game_id = created.json()['id']
        self.assertEqual(created.json()['matchup_record'], expected())
        self.store = self.app.state.store

    def register(self, client, name):
        response = client.post('/api/auth/register', json={'name': name},
                               headers={'Origin': self.config.origin})
        self.assertEqual(response.status_code, 200)
        client.headers.update({'Origin': self.config.origin,
                               'X-CSRF-Token': response.json()['csrf_token']})

    def test_owned_snapshot_includes_history_and_current_completion_once(self):
        current = self.store.get(self.game_id)
        self.save('black', user_id=current['user_id'], result='0-1')
        url = f'/api/games/{self.game_id}'
        self.assertEqual(self.client.get(url).json()['matchup_record'], expected(human=1))
        payload = dict(action='resign', version=current['version'], request_id=uuid.uuid4().hex)
        for _ in range(2):
            response = self.client.post(url + '/actions', json=payload)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['matchup_record'], expected(human=1, ai=1, current=True))
        shared = self.client.post(url + '/share', json={'include_commentary': False})
        token = shared.json()['url'].rsplit('/', 1)[1]
        public = self.client.get('/api/replays/' + token).json()
        self.assertNotIn('matchup_record', public)
        self.assertNotIn('user_id', public)

    def test_other_account_and_unauthenticated_cannot_access_score(self):
        url = f'/api/games/{self.game_id}'
        with closing(TestClient(self.app)) as other:
            self.assertEqual(other.get(url).status_code, 401)
            self.register(other, 'Another owner')
            response = other.get(url)
            self.assertEqual(response.status_code, 404)
            self.assertNotIn('matchup_record', response.json())
            created = other.post('/api/games', json={'side': 'white'})
            self.assertEqual(created.json()['matchup_record'], expected())


class MatchupModelTests(Fixture, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.configure()

    async def test_accepted_ai_ending_updates_result_in_returned_snapshot(self):
        self.save(result='0-1')
        current = self.save('black')
        owner = self
        observed = []

        class Player:
            def __init__(self, config):
                pass

            async def run(self, game_id, snapshot, tool, emit, thread_id=None):
                owner.assertEqual(snapshot['matchup_record'], expected(ai=1))
                chosen = await tool('chess_choose', {'action': 'resign', 'note': 'Fixture ending.'})
                owner.assertTrue(chosen['accepted'])
                owner.assertEqual(chosen['game']['matchup_record'], expected(human=1, ai=1, current=True))
                observed.append(chosen)
                return {'usage_tokens': 1}

            async def close(self):
                pass

        supervisor = Supervisor(self.config, self.store,
            SimpleNamespace(memory_for_user=lambda _: ''), Player)
        self.addAsyncCleanup(supervisor.close)
        await supervisor._active_run(current['id'])
        self.assertEqual(len(observed), 1)
        self.assertEqual(self.store.get(current['id'])['result'], '0-1')

    async def test_postgame_initial_context_and_fresh_status_include_scores_not_other_history(self):
        previous = self.save(result='0-1')
        self.store.mutate(previous['id'], lambda s: game.message(s, 'human', 'SECRET OTHER GAME TEXT'))
        current = self.save('black', result='1/2-1/2')
        current['thread_id'] = 'saved-private-thread'
        self.store.mutate(current['id'], lambda s: s.update(thread_id=current['thread_id']))
        owner = self
        observed = []

        class Player:
            def __init__(self, config):
                pass

            async def run(self, game_id, snapshot, tool, emit, thread_id=None):
                owner.assertEqual(thread_id, 'saved-private-thread')
                owner.assertEqual(snapshot['matchup_record'], expected(ai=1, draws=1, current=True))
                owner.assertEqual(snapshot['memory'], '')
                owner.assertNotIn('SECRET OTHER GAME TEXT', json.dumps(snapshot))
                owner.assertIn('aggregate totals', snapshot['matchup_record_scope'])
                first = await tool('chess_status', {})
                owner.assertEqual(first['matchup_record'], snapshot['matchup_record'])
                owner.save(result='1-0')
                second = await tool('chess_status', {})
                owner.assertEqual(second['matchup_record'], expected(human=1, ai=1, draws=1, current=True))
                owner.assertNotIn('SECRET OTHER GAME TEXT', json.dumps(second))
                observed.append(second)
                return {'usage_tokens': 1}

            async def close(self):
                pass

        supervisor = Supervisor(self.config, self.store,
            SimpleNamespace(memory_for_user=lambda _: ''), Player)
        self.addAsyncCleanup(supervisor.close)
        await supervisor._active_run(current['id'])
        self.assertEqual(len(observed), 1)
        self.assertNotIn('matchup_record', self.store.get(current['id']))
        self.assertEqual(self.store.get(current['id'])['clock_used'], 0)


if __name__ == '__main__':
    unittest.main()
