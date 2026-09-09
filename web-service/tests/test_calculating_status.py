"""Search status and clock behavior without an engine, CLI or model request."""
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


class FixtureTime:
    def __init__(self):
        self.wall, self.tick = 1_800_000_000.0, 1000.0

    def time(self):
        return self.wall

    def monotonic(self):
        return self.tick

    def advance(self, seconds):
        self.wall += seconds
        self.tick += seconds


class CalculatingStatusTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.config = Config(data_dir=Path(folder.name), player_mode='disabled')
        self.config.validate()
        self.time = FixtureTime()
        for module in ('supervisor', 'chess_game', 'store'):
            clock_patch = patch(f'astra_web.{module}.time', self.time)
            clock_patch.start()
            self.addCleanup(clock_patch.stop)
        self.store = Store(self.config)
        state = game.new_game({'id': 'fixture', 'name': 'Fixture'}, 'black', self.config)
        state['clock_used'] = 200.0
        self.store.create(state)
        self.game_id = state['id']
        self.closed = 0

    def current(self):
        return self.store.get(self.game_id)

    def supervisor(self, script, query):
        owner = self

        class Player:
            def __init__(self, config):
                pass

            async def run(self, game_id, snapshot, tool, emit, thread_id=None):
                return await script(tool)

            async def close(self):
                owner.closed += 1

        supervisor = Supervisor(self.config, self.store,
            SimpleNamespace(memory_for_user=lambda _: ''), Player)
        supervisor._query = query
        return supervisor

    async def query(self, tool):
        await tool('chess_candidate', {'move': 'e2e4', 'concern': 'Fixture candidate'})
        return await tool('chess_query', {'seconds': 1})

    async def start_gated(self, supervisor, entered):
        run = asyncio.create_task(supervisor._active_run(self.game_id))

        async def cleanup():
            if not run.done():
                run.cancel()
            await asyncio.gather(run, return_exceptions=True)

        self.addAsyncCleanup(cleanup)
        await asyncio.wait_for(entered.wait(), timeout=2)
        return run

    async def test_search_exposes_calculating_keeps_clock_running_and_restores_thinking(self):
        entered, release = asyncio.Event(), asyncio.Event()

        async def query(*args):
            entered.set()
            await release.wait()
            return {'fallback': False}, 'fixture.result.json'

        async def script(tool):
            await self.query(tool)
            status = await tool('chess_status', {})
            self.assertEqual(status['worker']['state'], 'thinking')
            self.assertEqual(status['clock']['used_seconds'], 217)
            await tool('chess_choose', {'action': 'move', 'move': 'e2e4', 'note': 'Fixture move'})
            return {'usage_tokens': 0}

        supervisor = self.supervisor(script, query)
        run = await self.start_gated(supervisor, entered)
        before = game.snapshot(self.current())
        self.assertEqual(before['worker']['state'], 'calculating')
        self.time.advance(17)
        during = game.snapshot(self.current())
        self.assertEqual(during['worker']['state'], 'calculating')
        self.assertFalse(during['clock']['paused'])
        self.assertEqual(during['clock']['remaining_seconds'], before['clock']['remaining_seconds'] - 17)
        release.set()
        await run
        state = self.current()
        self.assertEqual(state['worker']['state'], 'idle')
        self.assertEqual(state['clock_used'], 217)
        self.assertEqual(len(state['clock_events']), 1)
        self.assertEqual(state['clock_events'][0]['charged_seconds'], 17)
        self.assertEqual(state['clock_events'][0]['paused_seconds'], 0)
        self.assertEqual(self.closed, 1)

    async def test_query_error_restores_thinking_before_failure_settlement(self):
        observed = []

        async def query(*args):
            self.assertEqual(self.current()['worker']['state'], 'calculating')
            self.time.advance(11)
            raise ValueError('Fixture query failure')

        async def script(tool):
            try:
                await self.query(tool)
            except ValueError:
                observed.append(self.current()['worker']['state'])
                raise

        with self.assertRaisesRegex(ValueError, 'Fixture query failure'):
            await self.supervisor(script, query)._active_run(self.game_id)
        state = self.current()
        self.assertEqual(observed, ['thinking'])
        self.assertEqual(state['worker']['state'], 'error')
        self.assertEqual(state['clock_used'], 211)
        self.assertIsNone(state['active_started'])
        self.assertEqual(state['clock_events'][0]['outcome'], 'interrupted')
        self.assertEqual(self.closed, 1)

    async def test_query_cancellation_restores_thinking_and_settles_charge(self):
        entered = asyncio.Event()
        observed = []

        async def query(*args):
            entered.set()
            await asyncio.Event().wait()

        async def script(tool):
            try:
                await self.query(tool)
            except asyncio.CancelledError:
                observed.append(self.current()['worker']['state'])
                raise

        run = await self.start_gated(self.supervisor(script, query), entered)
        self.assertEqual(self.current()['worker']['state'], 'calculating')
        self.time.advance(7)
        run.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await run
        state = self.current()
        self.assertEqual(observed, ['thinking'])
        self.assertEqual(state['worker']['state'], 'error')
        self.assertEqual(state['clock_used'], 207)
        self.assertEqual(state['clock_events'][0]['error_kind'], 'service_interrupted')
        self.assertIsNone(state['active_started'])
        self.assertEqual(self.closed, 1)

    async def test_game_ending_during_search_restores_idle(self):
        entered, release = asyncio.Event(), asyncio.Event()
        observed = []

        async def query(*args):
            entered.set()
            await release.wait()
            return {'fallback': False}, 'fixture.result.json'

        async def script(tool):
            await self.query(tool)
            observed.append(self.current()['worker']['state'])
            return {'usage_tokens': 0}

        run = await self.start_gated(self.supervisor(script, query), entered)
        self.store.mutate(self.game_id, lambda s: game.finish(s, '1-0', 'fixture_end'))
        release.set()
        await run
        self.assertEqual(observed, ['idle'])
        self.assertEqual(self.current()['worker']['state'], 'idle')
        self.assertEqual(self.current()['status'], 'finished')

    async def test_query_cleanup_preserves_a_newer_worker_error(self):
        observed = []

        async def query(*args):
            self.store.mutate(self.game_id, lambda s: s.update(
                worker={'state': 'error', 'message': 'Separate fixture error'}))
            raise ValueError('Fixture query failure')

        async def script(tool):
            try:
                await self.query(tool)
            except ValueError:
                observed.append(self.current()['worker'])
                raise

        with self.assertRaises(ValueError):
            await self.supervisor(script, query)._active_run(self.game_id)
        self.assertEqual(observed, [{'state': 'error', 'message': 'Separate fixture error'}])
        self.assertEqual(self.current()['worker'], observed[0])

    async def test_restart_recovers_chat_only_calculating_without_charging_clock(self):
        self.store.mutate(self.game_id, lambda s: s.update(human_side='white', astra_side='black',
            worker={'state': 'calculating', 'message': 'Interrupted chat search'}))
        supervisor = self.supervisor(None, None)
        self.time.advance(100)
        supervisor.recover()
        state = self.current()
        self.assertEqual(state['worker']['state'], 'error')
        self.assertEqual(state['clock_used'], 200)
        self.assertEqual(state['clock_events'], [])
        self.assertIsNone(state['active_started'])
        self.assertEqual(supervisor.tasks, {})
        supervisor.recover()
        self.assertEqual(self.current(), state)


if __name__ == '__main__':
    unittest.main()
