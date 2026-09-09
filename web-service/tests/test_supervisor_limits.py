from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import secrets
from fastapi.testclient import TestClient
from astra_web.app import create_app
from astra_web.config import Config
from astra_web.store import Store
from astra_web.supervisor import Supervisor
from astra_web import chess_game as game


class ClockAllocationTests(unittest.IsolatedAsyncioTestCase):
    async def test_shrunken_turn_still_allows_a_query_and_a_move(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Config(data_dir=Path(folder))
            config.validate()
            store = Store(config)
            state = game.new_game({'id':'clock-test','name':'Clock test'}, 'black', config)
            # Unit fixture representing six earned minutes after own move 60.
            state['own_moves'] = 60
            state['clock_used'] = 8640
            store.create(state)
            evidence = []
            class Player:
                def __init__(self, config):
                    pass
                async def run(self, game_id, snapshot, tool, emit, thread_id=None):
                    await tool('chess_candidate', {'move':'e2e4','concern':'Low-clock fixture'})
                    await tool('chess_query', {'seconds':15})
                    await tool('chess_choose', {'action':'move','move':'e2e4','note':'Validated fixture move'})
                    return {'usage_tokens':0}
                async def close(self):
                    pass
            supervisor = Supervisor(config, store, SimpleNamespace(memory_for_user=lambda user_id:''), Player)
            async def query(game_id, current, args, available):
                evidence.append(available)
                return {'fallback':False}, 'fixture.json'
            supervisor._query = query
            await supervisor._active_run(state['id'])
            self.assertEqual(len(evidence), 1)
            self.assertGreater(evidence[0], 10)
            final = store.get(state['id'])
            self.assertEqual(final['moves'][0]['uci'], 'e2e4')
            self.assertIsNone(final['active_started'])


class ChatRetryTests(unittest.TestCase):
    def test_failed_chat_can_retry_during_human_turn_but_idle_work_cannot(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Config(data_dir=Path(folder), origin='http://testserver')
            app = create_app(config)
            with TestClient(app) as client:
                identity = client.post('/api/auth/register', json={'name':'Retry fixture'}, headers={'Origin':config.origin}).json()
                headers = {'Origin':config.origin, 'X-CSRF-Token':identity['csrf_token']}
                state = client.post('/api/games', json={'side':'white'}, headers=headers).json()
                scheduled = []
                app.state.supervisor.schedule = scheduled.append
                def retry(current):
                    return client.post('/api/games/' + current['id'] + '/actions', headers=headers,
                        json={'action':'retry','version':current['version'],'request_id':secrets.token_hex(12)})
                self.assertEqual(retry(state).status_code, 400)
                self.assertEqual(scheduled, [])
                updated = app.state.store.mutate(state['id'], lambda s:s.update(worker={'state':'error','message':'Interrupted chat'}))
                response = retry(updated)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(scheduled, [state['id']])
                self.assertEqual(response.json()['ply'], 0)


if __name__ == '__main__':
    unittest.main()
