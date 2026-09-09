import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from astra_web.config import Config
from astra_web.store import Store
from astra_web.supervisor import Supervisor
from astra_web import chess_game as game


class EngineAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_engine_request_and_hypothetical_history_are_isolated(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = Config(data_dir=Path(folder))
            cfg.validate()
            store = Store(cfg)
            state = game.new_game({'id': 'test', 'name': 'Tester'}, 'white', cfg)
            store.create(state)
            supervisor = Supervisor(cfg, store, None)
            result, relative = await supervisor._query(state['id'], state,
                {'seconds': .2, 'depth': 2, 'candidates': 2, 'after': ['e2e4']}, 1)
            self.assertEqual(result['engine']['source_sha256'], state['engine_fingerprint'])
            self.assertTrue((Path(folder) / relative).is_file())
            self.assertEqual(store.get(state['id'])['fen'], game.START_FEN)
            self.assertEqual(result['position_history_fens'], [game.START_FEN])
            self.assertEqual(result['query']['after'], ['e2e4'])
            self.assertFalse('OPENAI_API_KEY' in json.dumps(result))
            for bad in ({'fen': 'startpos'}, {'seconds': float('nan')}, {'depth': 40}, {'after': ['e2e5']}):
                with self.assertRaises(ValueError):
                    await supervisor._query(state['id'], state, bad, 1)


if __name__ == '__main__':
    unittest.main()
