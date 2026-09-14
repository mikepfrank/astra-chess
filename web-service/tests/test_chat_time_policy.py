"""Slow chat and chat-to-move transitions without model or engine processes."""
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


class FakeClock:
    def __init__(self):
        self.now = 1_800_000_000.0

    def time(self):
        return self.now

    def monotonic(self):
        return self.now - 1_799_000_000.0

    def advance(self, seconds):
        self.now += seconds


class ChatTimePolicyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.clock = FakeClock()
        for module in ('supervisor', 'chess_game', 'store'):
            clock_patch = patch(f'astra_web.{module}.time', self.clock)
            clock_patch.start()
            self.addCleanup(clock_patch.stop)

    def fixture(self, *, profile='openrouter-glm', finished=False):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        config = Config(data_dir=Path(folder.name), player_mode='test', model_profile=profile,
            persona='arcturus' if profile == 'openrouter-glm' else 'astra',
            max_workers=2, max_turn_tokens=1000, max_daily_tokens=10_000)
        config.validate()
        store = Store(config)
        state = game.new_game({'id': 'chat-fixture', 'name': 'Chat fixture'}, 'white', config)
        state.update(clock_used=200.0, thread_id='saved-chat-thread')
        if finished:
            game.finish(state, '1/2-1/2', 'agreement')
            state['clock_used'] = 5400.0
        store.create(state)
        return SimpleNamespace(config=config, store=store, baseline=state, game_id=state['id'], closed=0)

    def supervisor(self, fixture, behavior):
        class Player:
            def __init__(self, config):
                pass

            async def run(self, game_id, snapshot, tool, emit, thread_id=None):
                return await behavior(snapshot, tool, emit, thread_id)

            async def close(self):
                fixture.closed += 1

        supervisor = Supervisor(fixture.config, fixture.store,
            SimpleNamespace(memory_for_user=lambda _: ''), Player)
        self.addAsyncCleanup(supervisor.close)
        return supervisor

    def assert_clock_and_board_preserved(self, fixture):
        state = fixture.store.get(fixture.game_id)
        for key in ('status', 'result', 'termination', 'fen', 'moves', 'own_moves',
                    'clock_used', 'active_started', 'clock_events', 'draw_offer'):
            self.assertEqual(state[key], fixture.baseline[key], key)
        self.assertEqual(state.get('active_deadline'), fixture.baseline.get('active_deadline'))
        self.assertEqual(state.get('active_paused_seconds', 0),
                         fixture.baseline.get('active_paused_seconds', 0))
        self.assertNotIn('clock_refunds', state)
        self.assertEqual(state['thread_id'], fixture.baseline['thread_id'])
        return state

    def budget(self, fixture):
        with fixture.store.connection() as db:
            return tuple(db.execute('SELECT turns,tokens,reserved FROM budget').fetchone())

    def event_count(self, fixture, kind):
        with fixture.store.connection() as db:
            return db.execute('SELECT count(*) FROM events WHERE game_id=? AND kind=?',
                (fixture.game_id, kind)).fetchone()[0]

    async def test_human_turn_chat_can_finish_after_three_minutes_without_charging_clock(self):
        fixture = self.fixture()

        async def behavior(snapshot, tool, emit, thread_id):
            self.assertEqual(thread_id, 'saved-chat-thread')
            self.assertEqual(snapshot['hard_response_seconds'], 600)
            self.assertEqual(snapshot['remaining_turn_seconds'], 600)
            self.assertEqual(snapshot['response_timing'], dict(kind='chat', limit_seconds=600,
                remaining_seconds=600, charges_chess_clock=False))
            self.assertNotIn('turn_timing', snapshot)
            self.assertEqual(snapshot['reasoning'], 'max')
            self.clock.advance(180)
            status = await tool('chess_status', {})
            self.assertEqual(status['remaining_turn_seconds'], 420)
            self.assertEqual(status['response_timing']['remaining_seconds'], 420)
            self.assertFalse(status['response_timing']['charges_chess_clock'])
            with self.assertRaisesRegex(ValueError, 'requires your turn'):
                await tool('chess_choose', {'action': 'move', 'move': 'e2e4', 'note': 'Still human turn'})
            await emit('A completed three-minute chat answer.')
            return {'usage_tokens': 123}

        await self.supervisor(fixture, behavior)._active_run(fixture.game_id)
        state = self.assert_clock_and_board_preserved(fixture)
        self.assertEqual(state['worker']['state'], 'idle')
        self.assertEqual([m['text'] for m in state['messages']], ['A completed three-minute chat answer.'])
        self.assertEqual(self.budget(fixture), (1, 123, 0))

    async def test_finished_chat_can_finish_after_seven_minutes_with_zero_earned_clock(self):
        fixture = self.fixture(finished=True)

        async def behavior(snapshot, tool, emit, thread_id):
            self.assertEqual(snapshot['hard_response_seconds'], 600)
            self.assertEqual(snapshot['clock']['remaining_seconds'], 0)
            self.clock.advance(420)
            status = await tool('chess_status', {})
            self.assertEqual(status['remaining_turn_seconds'], 180)
            self.assertEqual(status['legal_moves'], [])
            with self.assertRaisesRegex(ValueError, 'game is finished'):
                await tool('chess_candidate', {'move': 'e2e4', 'concern': 'Cannot reopen the game'})
            await tool('chess_comment', {'text': 'A completed seven-minute post-game answer.'})
            return {'usage_tokens': 234}

        await self.supervisor(fixture, behavior)._active_run(fixture.game_id)
        self.assertEqual(self.assert_clock_and_board_preserved(fixture)['worker']['state'], 'idle')
        self.assertEqual(self.budget(fixture), (1, 234, 0))

    async def test_chat_compaction_extends_response_allowance_without_chess_clock_charge(self):
        for finished in (False, True):
            with self.subTest(finished=finished):
                fixture = self.fixture(finished=finished)

                async def behavior(snapshot, tool, emit, thread_id):
                    self.clock.advance(20)
                    await tool('_compaction', {'phase': 'started', 'item_id': 'chat-summary'})
                    self.clock.advance(90)
                    paused = await tool('chess_status', {})
                    self.assertEqual(paused['remaining_turn_seconds'], 580)
                    self.assertFalse(paused['clock']['paused'])
                    await tool('_compaction', {'phase': 'completed', 'item_id': 'chat-summary'})
                    self.clock.advance(120)
                    status = await tool('chess_status', {})
                    self.assertEqual(status['response_timing']['remaining_seconds'], 460)
                    await emit('Completed after context preparation.')
                    return {'usage_tokens': 123}

                await self.supervisor(fixture, behavior)._active_run(fixture.game_id)
                state = self.assert_clock_and_board_preserved(fixture)
                self.assertEqual(state['compaction_events'][0]['paused_seconds'], 90)
                self.assertFalse(state['compaction_events'][0]['clock_paused'])
                self.assertEqual(state['worker']['state'], 'idle')

    async def test_chat_hard_limit_still_cancels_and_intermediate_text_is_not_completion(self):
        fixture = self.fixture()
        stopped = asyncio.Event()

        async def behavior(snapshot, tool, emit, thread_id):
            await tool('_usage', {'tokens': 7})
            await emit('Still thinking about your question.')
            self.clock.advance(600)
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

        with self.assertRaisesRegex(TimeoutError, 'response deadline'):
            await self.supervisor(fixture, behavior)._active_run(fixture.game_id)
        self.assertTrue(stopped.is_set())
        state = self.assert_clock_and_board_preserved(fixture)
        self.assertEqual(state['worker']['state'], 'error')
        self.assertEqual(len(state['messages']), 1)
        self.assertEqual(self.budget(fixture), (1, 1000, 0))
        self.assertEqual(fixture.closed, 1)

    async def test_slow_chat_connection_and_token_errors_still_fail_and_settle(self):
        for token_error in (False, True):
            with self.subTest(token_error=token_error):
                fixture = self.fixture()

                async def behavior(snapshot, tool, emit, thread_id):
                    self.clock.advance(130)
                    await tool('_usage', {'tokens': 1001 if token_error else 7})
                    raise ConnectionError('Synthetic provider connection failure')

                with self.assertRaises(ValueError if token_error else ConnectionError):
                    await self.supervisor(fixture, behavior)._active_run(fixture.game_id)
                self.assertEqual(self.assert_clock_and_board_preserved(fixture)['worker']['state'], 'error')
                self.assertEqual(self.budget(fixture), (1, 1001 if token_error else 1000, 0))

    async def test_cancelling_slow_chat_preserves_clock_and_conservatively_settles(self):
        fixture = self.fixture()
        entered = asyncio.Event()
        stopped = asyncio.Event()

        async def behavior(snapshot, tool, emit, thread_id):
            await tool('_usage', {'tokens': 7})
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

        supervisor = self.supervisor(fixture, behavior)
        supervisor.schedule(fixture.game_id)
        await asyncio.wait_for(entered.wait(), 5)
        self.clock.advance(200)
        await supervisor.cancel(fixture.game_id)
        self.assertTrue(stopped.is_set())
        self.assertEqual(self.assert_clock_and_board_preserved(fixture)['worker']['state'], 'error')
        self.assertEqual(self.budget(fixture), (1, 1000, 0))
        self.assertEqual(supervisor.tasks, {})

    async def test_astra_human_and_finished_chat_keep_the_original_deadlines(self):
        for finished, limit in ((False, 60), (True, 120)):
            with self.subTest(finished=finished):
                fixture = self.fixture(profile='astra', finished=finished)

                async def behavior(snapshot, tool, emit, thread_id):
                    self.assertEqual(snapshot['remaining_turn_seconds'], limit)
                    self.assertNotIn('hard_response_seconds', snapshot)
                    self.assertNotIn('response_timing', snapshot)
                    self.clock.advance(limit)
                    await asyncio.Event().wait()

                with self.assertRaisesRegex(TimeoutError, 'response deadline'):
                    await self.supervisor(fixture, behavior)._active_run(fixture.game_id)
                self.assertEqual(self.assert_clock_and_board_preserved(fixture)['worker']['state'], 'error')

    async def test_human_move_supersedes_waiting_or_racing_chat_then_starts_one_chess_turn(self):
        for race in ('waiting', 'compaction', 'emit', 'tool', 'query'):
            with self.subTest(race=race):
                fixture = self.fixture()
                chat_entered, own_entered, release_own = (asyncio.Event() for _ in range(3))
                calls, active, peak = [], 0, 0
                cancelled = []

                def human_move():
                    fixture.store.mutate(fixture.game_id, lambda s: game.apply_move(s, 'e2e4', 'human'))
                    supervisor.schedule(fixture.game_id)

                async def behavior(snapshot, tool, emit, thread_id):
                    nonlocal active, peak
                    calls.append(snapshot)
                    active += 1
                    peak = max(peak, active)
                    try:
                        self.assertEqual(thread_id, 'saved-chat-thread')
                        if len(calls) == 1:
                            await emit('Comment completed before the human move.')
                            await tool('_usage', {'tokens': 7})
                            if race == 'compaction':
                                await tool('_compaction', {'phase': 'started', 'item_id': 'superseded-summary'})
                            chat_entered.set()
                            if race == 'waiting':
                                try:
                                    await asyncio.Event().wait()
                                finally:
                                    # Usage can still arrive during cleanup.
                                    await tool('_usage', {'tokens': 17})
                                    cancelled.append(True)
                                    await emit('Late cancellation text must not reach the new ply.')
                            elif race == 'compaction':
                                await asyncio.Event().wait()
                            elif race == 'query':
                                await tool('chess_candidate', {'move': 'e2e4', 'concern': 'Old position'})
                                await tool('chess_query', {'seconds': 1})
                            else:
                                self.clock.advance(200)
                                human_move()
                                if race == 'emit':
                                    await emit('Stale text must not reach the new ply.')
                                else:
                                    await tool('chess_comment', {'text': 'Stale tool text must not reach the new ply.'})
                            self.fail('Superseded chat must not continue')
                        else:
                            self.assertEqual(len(calls), 2)
                            self.assertEqual(snapshot['ply'], 1)
                            self.assertNotIn('response_timing', snapshot)
                            self.assertEqual(snapshot['hard_response_seconds'], 5200)
                            self.assertEqual(snapshot['reasoning'], 'max')
                            own_entered.set()
                            await release_own.wait()
                            await tool('chess_candidate', {'move': 'e7e5', 'concern': 'New authoritative position'})
                            await tool('chess_query', {'seconds': 1})
                            await tool('chess_choose', {'action': 'move', 'move': 'e7e5', 'note': 'Fresh chess turn'})
                            return {'usage_tokens': 123}
                    finally:
                        active -= 1

                supervisor = self.supervisor(fixture, behavior)

                async def query(game_id, state, args, available):
                    if not state['moves']:
                        self.clock.advance(200)
                        human_move()
                        return {'fallback': False}, 'old-chat-query.json'
                    return {'fallback': False}, 'new-turn-query.json'

                supervisor._query = query
                supervisor.schedule(fixture.game_id)
                await asyncio.wait_for(chat_entered.wait(), 5)
                if race in ('waiting', 'compaction'):
                    self.clock.advance(200)
                    human_move()
                await asyncio.wait_for(own_entered.wait(), 5)
                current = fixture.store.get(fixture.game_id)
                self.assertEqual(current['clock_used'], 200)
                self.assertEqual(current['clock_events'], [])
                self.assertEqual(current['active_started'], self.clock.time())
                self.assertEqual(current['worker']['state'], 'thinking')
                self.assertEqual([m['text'] for m in current['messages']],
                    ['Comment completed before the human move.'])
                self.assertEqual(current['queries'], [])
                if race == 'compaction':
                    self.assertIsNone(current['compaction_pause'])
                    self.assertEqual(current['compaction_events'][-1]['paused_seconds'], 200)
                    self.assertFalse(current['compaction_events'][-1]['clock_paused'])
                    self.assertEqual(current['compaction_events'][-1]['outcome'], 'interrupted')
                self.assertEqual(self.budget(fixture), (2, 1000, 1000))
                task = supervisor.tasks[fixture.game_id]
                self.clock.advance(10)
                release_own.set()
                await asyncio.wait_for(task, 5)
                final = fixture.store.get(fixture.game_id)
                self.assertEqual([m['uci'] for m in final['moves']], ['e2e4', 'e7e5'])
                self.assertEqual(final['clock_used'], 210)
                self.assertEqual(final['worker']['state'], 'idle')
                self.assertEqual([q['path'] for q in final['queries']], ['new-turn-query.json'])
                self.assertEqual(len(final['clock_events']), 1)
                self.assertEqual(self.budget(fixture), (2, 1123, 0))
                self.assertEqual(self.event_count(fixture, 'chat_superseded'), 1)
                self.assertEqual(self.event_count(fixture, 'worker_error'), 0)
                self.assertEqual(supervisor.tasks, {})
                self.assertEqual(supervisor.rerun, set())
                self.assertEqual(peak, 1)
                self.assertEqual(fixture.closed, 2)
                if race == 'waiting':
                    self.assertEqual(cancelled, [True])


if __name__ == '__main__':
    unittest.main()
