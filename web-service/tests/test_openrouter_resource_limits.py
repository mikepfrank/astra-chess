"""Repeated-context admission and settlement without network or model requests."""
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from astra_web import chess_game as game
from astra_web.config import Config
from astra_web.store import Store
from astra_web.supervisor import Supervisor


class OpenRouterConfigLimitsTests(unittest.TestCase):
    def test_profile_ceiling_preserves_lower_operator_overrides(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(Config(model_profile='openrouter-glm').max_turn_tokens, 2_000_000)
            self.assertEqual(Config(model_profile='openrouter-glm').max_daily_tokens, 20_000_000)
            self.assertEqual(Config(model_profile='astra').max_turn_tokens, 3_000_000)
            for configured, expected in ((125_000, 125_000), (1_000_000, 1_000_000),
                                         (2_000_000, 2_000_000), (3_000_000, 2_000_000)):
                with self.subTest(configured=configured), patch.dict(
                        os.environ, {'ASTRA_MAX_TURN_TOKENS': str(configured)}):
                    self.assertEqual(Config(model_profile='openrouter-glm').max_turn_tokens, expected)


class RepeatedContextActionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)

    async def exercise(self, *, limit=3_000_000):
        config = Config(data_dir=self.folder, model_profile='openrouter-glm', persona='arcturus',
                        max_turn_tokens=limit, max_daily_tokens=20_000_000, max_workers=1)
        config.validate()
        store = Store(config)
        state = game.new_game({'id': 'resource-fixture', 'name': 'Resource fixture'}, 'black', config)
        store.create(state)
        totals, stages = [], []

        class Player:
            def __init__(self, unused_config):
                pass

            async def run(self, game_id, snapshot, tool, emit, thread_id=None):
                async def response(stage):
                    stages.append(stage)
                    # Conservatively keep every input at the compaction threshold
                    # and use the full output allowance, even after summarization.
                    totals.append((totals[-1] if totals else 0) + 250_000 + 8192)
                    await tool('_usage', {'tokens': totals[-1]})

                await tool('_compaction', {'phase': 'started', 'item_id': 'fixture-compaction'})
                await response('compaction')
                await tool('_compaction', {'phase': 'completed', 'item_id': 'fixture-compaction'})
                await response('status')
                await tool('chess_status', {})
                await response('candidate')
                await tool('chess_candidate', {'move': 'e2e4', 'concern': 'Repeated-context fixture'})
                await response('query')
                await tool('chess_query', {'seconds': 15})
                await response('choose')
                await tool('chess_choose', {'action': 'move', 'move': 'e2e4',
                                            'note': 'Complete legal fixture action'})
                await response('acknowledgement')
                return {'usage_tokens': totals[-1]}

            async def close(self):
                pass

        supervisor = Supervisor(config, store, SimpleNamespace(memory_for_user=lambda _: ''), Player)
        async def query(game_id, current, args, available):
            return {'fallback': False}, 'fixture.json'
        supervisor._query = query
        failure = None
        try:
            await supervisor._active_run(state['id'])
        except ValueError as error:
            failure = error
        with store.connection() as db:
            budget = tuple(db.execute('SELECT tokens,reserved FROM budget').fetchone())
        return store.get(state['id']), budget, stages, totals, failure

    async def test_250k_context_and_compaction_allow_complete_mandatory_action(self):
        state, budget, stages, totals, failure = await self.exercise()
        self.assertIsNone(failure)
        self.assertEqual(stages, ['compaction', 'status', 'candidate', 'query', 'choose', 'acknowledgement'])
        self.assertEqual(totals[-1], 1_549_152)
        self.assertEqual(state['moves'][0]['uci'], 'e2e4')
        self.assertEqual(state['worker']['state'], 'idle')
        self.assertIsNone(state['active_started'])
        self.assertEqual(budget, (totals[-1], 0))

    async def test_lower_operator_limit_still_interrupts_and_conservatively_settles(self):
        state, budget, stages, totals, failure = await self.exercise(limit=1_000_000)
        self.assertIsNotNone(failure)
        self.assertIn('token allowance', str(failure))
        self.assertEqual(stages[-1], 'query')
        self.assertEqual(state['moves'], [])
        self.assertEqual(state['worker']['state'], 'error')
        self.assertIsNone(state['active_started'])
        self.assertEqual(budget, (totals[-1], 0))


if __name__ == '__main__':
    unittest.main()
