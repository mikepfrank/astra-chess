"""Deterministic own-clock tests; no CLI, model, engine search or live data."""
import asyncio
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from astra_web import chess_game as game
from astra_web.config import Config
from astra_web.store import Store
from astra_web.supervisor import Supervisor


class FakeTime:
    def __init__(self):
        self.wall, self.monotonic_value = 1_800_000_000.0, 1000.0

    def time(self):
        return self.wall

    def monotonic(self):
        return self.monotonic_value

    def advance(self, seconds):
        self.wall += seconds
        self.monotonic_value += seconds


class CompactionClockTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.config = Config(data_dir=Path(folder.name), player_mode='disabled')
        self.config.validate()
        self.time = FakeTime()
        for module in ('supervisor', 'chess_game', 'store'):
            clock_patch = patch(f'astra_web.{module}.time', self.time)
            clock_patch.start()
            self.addCleanup(clock_patch.stop)
        self.store = Store(self.config)
        self.state = game.new_game({'id': 'fixture', 'name': 'Fixture'}, 'black', self.config)
        self.state['clock_used'] = 200.0
        self.store.create(self.state)
        self.game_id = self.state['id']
        self.closed = 0
        self.query_available = []

    def current(self):
        return self.store.get(self.game_id)

    def player(self, script):
        owner = self

        class Player:
            def __init__(self, config):
                pass

            async def run(self, game_id, snapshot, tool, emit, thread_id=None):
                return await script(tool, emit)

            async def close(self):
                owner.closed += 1

        supervisor = Supervisor(self.config, self.store,
            SimpleNamespace(memory_for_user=lambda _: ''), Player)

        async def query(game_id, state, args, available):
            self.query_available.append(available)
            return {'fallback': False}, 'fixture.result.json'

        supervisor._query = query
        return supervisor

    async def move(self, tool):
        await tool('chess_candidate', {'move': 'e2e4', 'concern': 'Fixture candidate'})
        await tool('chess_query', {'seconds': 1})
        await tool('chess_choose', {'action': 'move', 'move': 'e2e4', 'note': 'Fixture move'})

    async def test_multiple_pauses_freeze_clock_and_deadline_and_keep_one_move_charge(self):
        async def script(tool, emit):
            self.time.advance(10)
            before = await tool('chess_status', {})
            for item, seconds in (('first', 50), ('second', 30)):
                await tool('_compaction', {'phase': 'started', 'item_id': item})
                await tool('_compaction', {'phase': 'started', 'item_id': item})
                self.time.advance(seconds)
                during = await tool('chess_status', {})
                self.assertEqual(during['clock']['used_seconds'], 210)
                self.assertTrue(during['clock']['paused'])
                self.assertEqual(during['clock']['pause_reason'], 'compaction')
                self.assertEqual(during['worker']['state'], 'compacting')
                self.assertEqual(during['remaining_turn_seconds'], before['remaining_turn_seconds'])
                await tool('_compaction', {'phase': 'completed', 'item_id': item})
                await tool('_compaction', {'phase': 'completed', 'item_id': item})
                await tool('_compaction', {'phase': 'started', 'item_id': item})
            self.assertEqual(self.current()['worker']['state'], 'thinking')
            self.time.advance(5)
            await self.move(tool)
            return {'usage_tokens': 123}

        supervisor = self.player(script)
        await supervisor._active_run(self.game_id)
        state = self.current()
        self.assertEqual(state['clock_used'], 215)
        self.assertEqual(game.clock(state)['remaining_seconds'], 5215)
        self.assertFalse(game.clock(state)['paused'])
        self.assertEqual(len(state['clock_events']), 1)
        event = state['clock_events'][0]
        self.assertEqual((event['charged_seconds'], event['paused_seconds']), (15, 80))
        self.assertEqual(event['outcome'], 'accepted_action')
        self.assertEqual([e['paused_seconds'] for e in state['compaction_events']], [50, 30])
        self.assertTrue(all(e['outcome'] == 'completed' for e in state['compaction_events']))
        self.assertAlmostEqual(self.query_available[0], 65)
        self.assertIsNone(state['active_started'])
        self.assertIsNone(state['compaction_pause'])
        self.assertEqual(self.closed, 1)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT tokens FROM budget').fetchone()[0], 123)

    async def test_critical_allocation_and_search_reserve_exclude_prior_pause(self):
        # With this balance, ordinary/critical allocations are 120/240 seconds.
        self.store.mutate(self.game_id, lambda s: s.update(own_moves=20, clock_used=0.0))

        async def script(tool, emit):
            self.time.advance(10)
            await tool('_compaction', {'phase': 'started', 'item_id': 'summary'})
            self.time.advance(100)
            await tool('_compaction', {'phase': 'completed', 'item_id': 'summary'})
            critical = await tool('chess_critical', {'reason': 'Fixture critical position'})
            self.assertEqual(critical['remaining_turn_seconds'], 230)
            self.assertEqual(self.current()['active_deadline'], self.state['created_at'] + 340)
            # Repeated promotion must not add another allocation or pause credit.
            again = await tool('chess_critical', {'reason': 'Same critical position'})
            self.assertEqual(again['remaining_turn_seconds'], 230)
            await self.move(tool)
            return {'usage_tokens': 0}

        await self.player(script)._active_run(self.game_id)
        self.assertEqual(self.query_available, [190])
        self.assertEqual(self.current()['clock_used'], 10)

    async def test_search_reserve_uses_short_allocation_after_long_compaction(self):
        self.store.mutate(self.game_id, lambda s: s.update(own_moves=60, clock_used=8640.0))

        async def script(tool, emit):
            self.time.advance(2)
            await tool('_compaction', {'phase': 'started', 'item_id': 'short-clock'})
            self.time.advance(100)
            await tool('_compaction', {'phase': 'completed', 'item_id': 'short-clock'})
            await self.move(tool)
            return {'usage_tokens': 0}

        await self.player(script)._active_run(self.game_id)
        self.assertEqual(self.query_available, [18])  # 30 allocation - 2 work - 10 reserve
        self.assertEqual(self.current()['clock_used'], 8642)

    async def test_interrupted_pause_is_finalized_and_retry_refunds_only_work(self):
        async def script(tool, emit):
            self.time.advance(8)
            await tool('_compaction', {'phase': 'started', 'item_id': 'failed-summary'})
            self.time.advance(50)
            raise ConnectionError('Fixture interruption')

        supervisor = self.player(script)
        with self.assertRaises(ConnectionError):
            await supervisor._active_run(self.game_id)
        state = self.current()
        self.assertEqual(state['clock_used'], 208)
        self.assertEqual(state['worker']['state'], 'error')
        self.assertIsNone(state['compaction_pause'])
        self.assertEqual(state['compaction_events'][0]['outcome'], 'interrupted')
        self.assertEqual(len(state['clock_events']), 1)
        self.assertEqual(state['clock_events'][0]['paused_seconds'], 50)
        self.assertEqual(state['clock_events'][0]['charged_seconds'], 8)
        refunded = self.store.mutate(self.game_id, lambda s: None, transaction_hook=lambda s, db:
            supervisor.refund_retry_clock(s, db, 'retry-fixture'))
        self.assertEqual(refunded['clock_used'], 200)
        self.assertEqual(refunded['clock_refunds'][0]['seconds'], 8)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT tokens FROM budget').fetchone()[0], self.config.max_turn_tokens)

    async def test_cancellation_closes_open_pause_without_charging_it(self):
        entered = asyncio.Event()

        async def script(tool, emit):
            self.time.advance(7)
            await tool('_compaction', {'phase': 'started', 'item_id': 'cancel-summary'})
            self.time.advance(50)
            entered.set()
            await asyncio.Event().wait()

        supervisor = self.player(script)
        run = asyncio.create_task(supervisor._active_run(self.game_id))
        await asyncio.wait_for(entered.wait(), timeout=2)
        run.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await run
        state = self.current()
        self.assertEqual(state['clock_used'], 207)
        self.assertEqual(state['clock_events'][0]['error_kind'], 'service_interrupted')
        self.assertEqual(state['compaction_events'][0]['outcome'], 'interrupted')
        self.assertIsNone(state['compaction_pause'])
        self.assertEqual(self.closed, 1)

    async def test_supervisor_deadline_stays_frozen_until_compaction_ends(self):
        entered, release = asyncio.Event(), asyncio.Event()

        async def script(tool, emit):
            self.time.advance(10)
            await tool('_compaction', {'phase': 'started', 'item_id': 'long-summary'})
            self.time.advance(200)
            entered.set()
            await release.wait()
            await tool('_compaction', {'phase': 'completed', 'item_id': 'long-summary'})
            self.time.advance(111)
            await tool('chess_status', {})

        supervisor = self.player(script)
        run = asyncio.create_task(supervisor._active_run(self.game_id))
        await asyncio.wait_for(entered.wait(), timeout=2)
        # Allow the supervisor's independent monitoring loop to run at least once.
        await asyncio.sleep(.3)
        self.assertFalse(run.done())
        release.set()
        with self.assertRaises((ValueError, TimeoutError)):
            await run
        self.assertEqual(self.current()['clock_used'], 321)

    async def test_invalid_lifecycle_cannot_create_retroactive_or_overlapping_credit(self):
        async def script(tool, emit):
            await tool('_compaction', {'phase': 'completed', 'item_id': 'out-of-order'})
            await tool('_compaction', {'phase': 'started', 'item_id': 'out-of-order'})
            self.assertIsNone(self.current()['compaction_pause'])
            self.time.advance(10)
            await tool('_compaction', {'phase': 'started', 'item_id': 'actual'})
            with self.assertRaisesRegex(ValueError, 'Overlapping'):
                await tool('_compaction', {'phase': 'started', 'item_id': 'overlap'})
            with self.assertRaisesRegex(ValueError, 'during context compaction'):
                await tool('chess_candidate', {'move': 'e2e4', 'concern': 'Not allowed during pause'})
            self.time.advance(20)
            await tool('_compaction', {'phase': 'completed', 'item_id': 'unrelated'})
            self.assertTrue(game.clock(self.current())['paused'])
            await tool('_compaction', {'phase': 'completed', 'item_id': 'actual'})
            await self.move(tool)
            return {'usage_tokens': 0}

        await self.player(script)._active_run(self.game_id)
        self.assertEqual(self.current()['clock_used'], 210)
        self.assertEqual(len(self.current()['compaction_events']), 1)

    async def test_human_turn_and_post_move_compaction_never_charge_chess_clock(self):
        self.store.mutate(self.game_id, lambda s: s.update(human_side='white', astra_side='black'))

        async def chat(tool, emit):
            self.time.advance(4)
            await tool('_compaction', {'phase': 'started', 'item_id': 'human-turn'})
            self.time.advance(50)
            status = await tool('chess_status', {})
            self.assertEqual(status['worker']['state'], 'compacting')
            self.assertFalse(status['clock']['paused'])
            self.assertIsNone(status['clock']['pause_reason'])
            await tool('_compaction', {'phase': 'completed', 'item_id': 'human-turn'})
            await emit('Fixture answer')
            return {'usage_tokens': 0}

        await self.player(chat)._active_run(self.game_id)
        self.assertEqual(self.current()['clock_events'], [])
        self.assertEqual(self.current()['clock_used'], 200)
        self.store.mutate(self.game_id, lambda s: s.update(human_side='black', astra_side='white'))

        async def after_move(tool, emit):
            self.time.advance(3)
            await self.move(tool)
            await tool('_compaction', {'phase': 'started', 'item_id': 'after-move'})
            self.time.advance(50)
            self.assertFalse(game.clock(self.current())['paused'])
            raise ConnectionError('Fixture post-move interruption')

        with self.assertRaises(ConnectionError):
            await self.player(after_move)._active_run(self.game_id)
        state = self.current()
        self.assertEqual(state['clock_used'], 203)
        self.assertEqual(len(state['clock_events']), 1)
        self.assertEqual(state['clock_events'][0]['paused_seconds'], 0)
        self.assertEqual(state['clock_events'][0]['outcome'], 'accepted_action')
        self.assertEqual(state['compaction_events'][-1]['outcome'], 'interrupted')
        self.assertFalse(state['compaction_events'][-1]['clock_paused'])

    async def test_restart_after_multiple_completed_pauses_freezes_open_pause_and_keeps_refund_evidence(self):
        supervisor = self.player(lambda *_: None)
        started = self.time.time()
        def start(s):
            s.update(active_started=started, active_deadline=started + 120,
                     active_paused_seconds=0.0, worker={'state': 'thinking', 'message': ''})
        self.store.mutate(self.game_id, start, kind='worker_started', body={'ply': 0})
        def begin_pause(item):
            self.store.mutate(self.game_id, lambda s: s.update(compaction_pause={
                'item_id': item, 'attempt_id': 'fixture', 'started_at': self.time.time(),
                'clock_paused': True}, worker={'state': 'compacting', 'message': ''}),
                kind='compaction_started')

        for item, pause_seconds in (('first', 10), ('second', 20)):
            self.time.advance(3)
            begin_pause(item)
            self.time.advance(pause_seconds)
            def complete(s):
                game.finish_compaction(s, self.time.time(), 'completed')
                s['active_deadline'] += pause_seconds
                s['worker'] = {'state': 'thinking', 'message': ''}
            self.store.mutate(self.game_id, complete, kind='compaction_completed')
        self.time.advance(4)
        begin_pause('crashed')
        self.time.advance(500)
        supervisor.recover()
        state = self.current()
        self.assertEqual(state['clock_used'], 210)
        self.assertIsNone(state['compaction_pause'])
        self.assertFalse(game.clock(state)['paused'])
        self.assertEqual([e['outcome'] for e in state['compaction_events']],
                         ['completed', 'completed', 'service_restart'])
        self.assertEqual(state['compaction_events'][-1]['paused_seconds'], 500)
        self.assertEqual(state['clock_events'][0]['charged_seconds'], 10)
        self.assertEqual(state['clock_events'][0]['paused_seconds'], 530)
        self.assertEqual(supervisor.tasks, {})
        supervisor.recover()
        self.assertEqual(len(self.current()['clock_events']), 1)
        refunded = self.store.mutate(self.game_id, lambda s: None, transaction_hook=lambda s, db:
            supervisor.refund_retry_clock(s, db, 'restart-retry'))
        self.assertEqual(refunded['clock_used'], 200)

    async def test_restart_bounds_completed_pause_charge_by_original_allocation(self):
        started = self.time.time()
        self.store.mutate(self.game_id, lambda s: s.update(active_started=started,
            active_deadline=started + 220, active_paused_seconds=100.0,
            worker={'state': 'thinking', 'message': ''}))
        self.time.advance(500)
        self.player(lambda *_: None).recover()
        state = self.current()
        self.assertEqual(state['clock_used'], 320)
        self.assertEqual(state['clock_events'][0]['charged_seconds'], 120)
        self.assertEqual(state['clock_events'][0]['paused_seconds'], 100)


if __name__ == '__main__':
    unittest.main()
