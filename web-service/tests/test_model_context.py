import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from astra_web import chess_game as game
from astra_web.config import Config
from astra_web.store import Store
from astra_web.supervisor import Supervisor


class ModelContextTests(unittest.TestCase):
    def test_snapshot_bounds_repeated_context_without_changing_game_evidence(self):
        state = game.new_game({'id':'context','name':'Context'}, 'white', Config())
        game.apply_move(state, 'e2e4', 'human')
        for i in range(20):
            game.message(state, 'human', 'Message ' + str(i))
        view = game.model_snapshot(state)
        self.assertEqual(len(view['messages']), 12)
        self.assertEqual(view['earlier_message_count'], 8)
        self.assertNotIn('history_fens', view)
        self.assertNotIn('fen', view['moves'][0])
        self.assertEqual(view['fen'], state['fen'])
        self.assertEqual(view['moves'][0]['uci'], 'e2e4')
        self.assertEqual(len(state['messages']), 20)
        self.assertIn('fen', state['moves'][0])


class QueryEvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_details_are_lossless_and_confined_to_this_game(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Config(data_dir=Path(folder))
            config.validate()
            store = Store(config)
            state = game.new_game({'id':'detail-test','name':'Detail test'}, 'black', config)
            store.create(state)
            errors = []
            result = {'kind':'analysis', 'start_fen':state['fen'], 'fallback':False,
                      'candidates':[{'rank':1, 'root_move':'e2e4', 'score_cp':12,
                          'san':['e4'], 'uci':['e2e4'], 'fens':[state['fen']],
                          'position_diagnostics':[{'kind':'position_diagnostics',
                              'warnings':['Inspect the opponent reply.'], 'limitations':['Bounded evidence.']}]}]}
            class Player:
                def __init__(self, config):
                    pass
                async def run(self, game_id, snapshot, tool, emit, thread_id=None):
                    await tool('chess_candidate', {'move':'e2e4','concern':'Check details'})
                    view = await tool('chess_query', {})
                    complete = await tool('chess_query_details', {'query_index':view['query_index']})
                    self_test.assertEqual(complete, result)
                    selected = await tool('chess_query_details', {'query_index':0,'candidate_rank':1})
                    self_test.assertEqual(selected['candidate'], result['candidates'][0])
                    for arguments in ({'query_index':-1}, {'query_index':0,'candidate_rank':2},
                                      {'query_index':0,'path':'ignored'}):
                        with self_test.assertRaises(ValueError):
                            await tool('chess_query_details', arguments)
                    store.mutate(game_id, lambda s:s['queries'].append({'ply':0,'path':'../outside.json'}))
                    with self_test.assertRaises(ValueError):
                        await tool('chess_query_details', {'query_index':1})
                    await tool('chess_choose', {'action':'move','move':'e2e4','note':'Evidence checked'})
                    return {'usage_tokens':1}
                async def close(self):
                    pass
            self_test = self
            supervisor = Supervisor(config, store, SimpleNamespace(memory_for_user=lambda uid:''), Player)
            async def query(game_id, current, args, available):
                path = Path('games') / game_id / 'queries' / 'fixture.result.json'
                target = config.data_dir / path
                target.parent.mkdir(parents=True)
                target.write_text(json.dumps(result), encoding='utf-8')
                return result, str(path)
            supervisor._query = query
            await supervisor._active_run(state['id'])
            self.assertEqual(store.get(state['id'])['moves'][0]['uci'], 'e2e4')


if __name__ == '__main__':
    unittest.main()
