"""Offline multi-game scheduling with real storage and synthetic model workers.

No Codex, provider, engine search, or wall-clock performance assertion is used.
Gates establish actual coroutine overlap; a fake chess clock makes queue charges
and independent clock settlement deterministic.
"""
import asyncio
from collections import Counter, defaultdict
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


class ParallelWorkerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.clock = FakeClock()
        for module in ('supervisor', 'store', 'chess_game'):
            clock_patch = patch(f'astra_web.{module}.time', self.clock)
            clock_patch.start()
            self.addCleanup(clock_patch.stop)
        self.config = Config(data_dir=Path(folder.name), model_profile='openrouter-glm',
            persona='arcturus', player_mode='test', max_workers=2,
            max_turn_tokens=1000, max_daily_tokens=10_000, max_daily_turns=20)
        self.config.validate()
        self.assertEqual(self.config.reasoning, 'max')
        self.store = Store(self.config)
        self.starts = Counter()
        self.active = Counter()
        self.max_active = 0
        self.max_per_game = Counter()
        self.calls = defaultdict(list)
        self.started = defaultdict(asyncio.Event)
        self.release = defaultdict(asyncio.Event)
        self.query_started = defaultdict(asyncio.Event)
        self.query_release = defaultdict(asyncio.Event)
        self.closed = Counter()
        self.outcomes = {}
        self.moves = {}
        self.usage = {}
        self.query_inputs = {}
        self.initial = {}
        owner = self

        class Player:
            def __init__(self, config):
                self.game_id = None

            async def run(self, game_id, snapshot, tool, emit, thread_id=None):
                self.game_id = game_id
                owner.starts[game_id] += 1
                number = owner.starts[game_id]
                owner.active[game_id] += 1
                owner.max_active = max(owner.max_active, sum(owner.active.values()))
                owner.max_per_game[game_id] = max(owner.max_per_game[game_id], owner.active[game_id])
                owner.calls[game_id].append((snapshot, tool, thread_id))
                owner.started[game_id].set()
                try:
                    if number > 1:
                        # A schedule burst represents coalesced newer context;
                        # after the move its follow-up is on the human's turn.
                        await emit('Follow-up for ' + game_id)
                        return {'usage_tokens': 0}
                    await owner.release[game_id].wait()
                    await tool('_thread', {'thread_id': 'thread-' + game_id})
                    await tool('_usage', {'tokens': 7})
                    if owner.outcomes.get(game_id) == 'error':
                        raise ConnectionError('Synthetic provider failure for ' + game_id)
                    await tool('chess_candidate', {'move': owner.moves[game_id],
                        'concern': 'Independent candidate for ' + game_id})
                    await tool('chess_query', {'seconds': 1})
                    await tool('chess_choose', {'action': 'move', 'move': owner.moves[game_id],
                        'note': 'Validated synthetic move for ' + game_id})
                    await emit('Comment for ' + game_id)
                    return {'usage_tokens': owner.usage[game_id]}
                finally:
                    owner.active[game_id] -= 1

            async def close(self):
                owner.closed[self.game_id] += 1

        self.supervisor = Supervisor(self.config, self.store,
            SimpleNamespace(memory_for_user=lambda user_id: 'Memory for ' + user_id), Player)
        self.addAsyncCleanup(self.supervisor.close)

        async def query(game_id, state, args, available):
            self.query_inputs[game_id] = (state, args, available)
            self.query_started[game_id].set()
            await self.query_release[game_id].wait()
            return {'fallback': False}, f'games/{game_id}/queries/synthetic.result.json'

        self.supervisor._query = query

    def add_game(self, label, *, human_side='black', usage=100):
        state = game.new_game({'id': 'user-' + label, 'name': 'Player ' + label},
            human_side, self.config)
        if human_side == 'white':
            game.apply_move(state, 'e2e4', 'human')
        state['thread_id'] = 'previous-' + state['id']
        state['clock_used'] = 200.0
        self.store.create(state)
        game_id = state['id']
        self.initial[game_id] = state
        self.moves[game_id] = 'e7e5' if human_side == 'white' else 'e2e4'
        self.usage[game_id] = usage
        self.query_release[game_id].set()
        return game_id

    async def wait_started(self, *game_ids):
        await asyncio.wait_for(asyncio.gather(*(self.started[key].wait() for key in game_ids)), 5)

    async def finish(self, *game_ids):
        tasks = [self.supervisor.tasks[key] for key in game_ids]
        for key in game_ids:
            self.release[key].set()
        await asyncio.wait_for(asyncio.gather(*tasks), 5)

    def budget(self):
        with self.store.connection() as db:
            row = db.execute('SELECT turns,tokens,reserved FROM budget').fetchone()
            return tuple(row) if row else (0, 0, 0)

    def assert_completed(self, game_id, seconds):
        state = self.store.get(game_id)
        self.assertEqual([m['uci'] for m in state['moves']],
            [m['uci'] for m in self.initial[game_id]['moves']] + [self.moves[game_id]])
        self.assertEqual(state['worker']['state'], 'idle')
        self.assertEqual(state['own_moves'], 1)
        self.assertEqual(state['clock_used'], 200 + seconds)
        self.assertEqual([e['charged_seconds'] for e in state['clock_events']], [seconds])
        self.assertIsNone(state['active_started'])
        self.assertEqual(state['thread_id'], 'thread-' + game_id)
        self.assertEqual([m['text'] for m in state['messages']], ['Comment for ' + game_id])
        self.assertEqual([q['path'] for q in state['queries']],
            [f'games/{game_id}/queries/synthetic.result.json'])
        self.assertEqual(self.closed[game_id], 1)
        self.assertEqual(self.max_per_game[game_id], 1)
        return state

    async def test_two_games_overlap_third_waits_without_spending_clock_or_reservation(self):
        first = self.add_game('first', usage=101)
        second = self.add_game('second', human_side='white', usage=202)
        third = self.add_game('third', usage=303)
        self.moves[third] = 'c2c4'
        for key in (first, second, third):
            self.supervisor.schedule(key)
        await self.wait_started(first, second)
        self.assertEqual(self.max_active, 2)
        self.assertEqual(self.budget(), (2, 0, 2000))
        self.clock.advance(70)
        waiting = self.store.get(third)
        self.assertEqual(waiting['worker']['state'], 'queued')
        self.assertIsNone(waiting['active_started'])
        self.assertEqual(game.clock(waiting)['used_seconds'], 200)
        self.assertFalse(self.started[third].is_set())
        for key in (first, second):
            self.assertEqual(game.clock(self.store.get(key))['used_seconds'], 270)
        await self.finish(first)
        await self.wait_started(third)
        self.assertEqual(self.active, Counter({second: 1, third: 1}))
        self.assertEqual(self.budget(), (3, 101, 2000))
        self.assertEqual(self.store.get(third)['active_started'], self.clock.time())
        self.clock.advance(20)
        await self.finish(second, third)
        self.assert_completed(first, 70)
        self.assert_completed(second, 90)
        self.assert_completed(third, 20)
        self.assertEqual(self.budget(), (3, 606, 0))
        self.assertEqual(self.supervisor.tasks, {})
        self.assertEqual(self.max_active, 2)

    async def test_tool_proofs_thread_context_and_simultaneous_queries_stay_per_game(self):
        first = self.add_game('white', usage=101)
        second = self.add_game('black', human_side='white', usage=202)
        for key in (first, second):
            self.query_release[key].clear()
            self.supervisor.schedule(key)
        await self.wait_started(first, second)
        self.release[first].set()
        await asyncio.wait_for(self.query_started[first].wait(), 5)
        for key in (first, second):
            snapshot, tool, thread_id = self.calls[key][0]
            self.assertEqual(snapshot['id'], key)
            self.assertEqual(snapshot['fen'], self.initial[key]['fen'])
            self.assertEqual(snapshot['memory'], 'Memory for ' + self.initial[key]['user_id'])
            self.assertEqual(thread_id, 'previous-' + key)
        second_tool = self.calls[second][0][1]
        status = await second_tool('chess_status', {})
        self.assertFalse(status['current_attempt']['candidate_recorded'])
        self.assertFalse(status['current_attempt']['root_query_completed'])
        with self.assertRaisesRegex(ValueError, 'independent candidate'):
            await second_tool('chess_choose', {'action': 'move', 'move': self.moves[second],
                'note': 'Other game evidence must not authorize this move'})
        self.release[second].set()
        await asyncio.wait_for(self.query_started[second].wait(), 5)
        for key in (first, second):
            self.assertEqual(self.store.get(key)['worker']['state'], 'calculating')
            query_state, _, available = self.query_inputs[key]
            self.assertEqual(query_state['id'], key)
            self.assertEqual(query_state['fen'], self.initial[key]['fen'])
            self.assertGreater(available, 0)
        self.clock.advance(12)
        tasks = [self.supervisor.tasks[key] for key in (first, second)]
        for key in (first, second):
            self.query_release[key].set()
        await asyncio.wait_for(asyncio.gather(*tasks), 5)
        white = self.assert_completed(first, 12)
        black = self.assert_completed(second, 12)
        self.assertNotEqual(white['fen'], black['fen'])
        for key, state in ((first, white), (second, black)):
            self.assertEqual([c['concern'] for c in state['candidates']],
                ['Independent candidate for ' + key])
            self.assertEqual([d['note'] for d in state['decisions']],
                ['Validated synthetic move for ' + key])
        self.assertEqual(self.budget(), (2, 303, 0))

    async def test_same_game_schedule_burst_has_one_active_worker_and_one_coalesced_followup(self):
        key = self.add_game('coalesced', usage=123)
        self.supervisor.schedule(key)
        task = self.supervisor.tasks[key]
        await self.wait_started(key)
        for _ in range(12):
            self.supervisor.schedule(key)
            self.assertIs(self.supervisor.tasks[key], task)
        self.assertEqual(self.starts[key], 1)
        self.assertEqual(self.budget(), (1, 0, 1000))
        self.assertEqual(self.supervisor.rerun, {key})
        self.clock.advance(9)
        await self.finish(key)
        # _run schedules at most one follow-up in its finally block. It may
        # already have finished by the time its predecessor is observed done.
        if key in self.supervisor.tasks:
            await asyncio.wait_for(self.supervisor.tasks[key], 5)
        state = self.store.get(key)
        self.assertEqual(self.starts[key], 2)
        self.assertEqual(self.max_per_game[key], 1)
        self.assertEqual([m['uci'] for m in state['moves']], ['e2e4'])
        self.assertEqual(state['clock_used'], 209)
        self.assertEqual(len(state['clock_events']), 1)
        self.assertEqual(state['worker']['state'], 'idle')
        self.assertEqual([m['text'] for m in state['messages']],
            ['Comment for ' + key, 'Follow-up for ' + key])
        self.assertEqual(self.closed[key], 2)
        self.assertEqual(self.budget(), (2, 123, 0))
        self.assertEqual(self.supervisor.tasks, {})
        self.assertEqual(self.supervisor.rerun, set())

    async def exercise_interruption(self, *, cancel):
        failed = self.add_game('interrupted')
        healthy = self.add_game('healthy', usage=222)
        queued = self.add_game('queued', usage=333)
        for key in (failed, healthy, queued):
            self.supervisor.schedule(key)
        await self.wait_started(failed, healthy)
        healthy_task = self.supervisor.tasks[healthy]
        self.assertEqual(self.budget(), (2, 0, 2000))
        self.clock.advance(30)
        if cancel:
            await self.supervisor.cancel(failed)
        else:
            self.outcomes[failed] = 'error'
            await self.finish(failed)
        await self.wait_started(queued)
        self.assertIs(self.supervisor.tasks[healthy], healthy_task)
        self.assertFalse(healthy_task.done())
        broken = self.store.get(failed)
        self.assertEqual(broken['worker']['state'], 'error')
        self.assertEqual(broken['moves'], [])
        self.assertEqual(broken['clock_used'], 230)
        self.assertIsNone(broken['active_started'])
        self.assertEqual(broken['clock_events'][0]['error_kind'],
            'service_interrupted' if cancel else 'connection_error')
        self.assertEqual(self.closed[failed], 1)
        self.assertEqual(self.budget(), (3, 1000, 2000))
        self.clock.advance(15)
        await self.finish(healthy, queued)
        self.assert_completed(healthy, 45)
        self.assert_completed(queued, 15)
        self.assertEqual(self.budget(), (3, 1555, 0))
        self.assertEqual(self.max_active, 2)
        self.assertEqual(self.supervisor.tasks, {})

    async def test_provider_failure_settles_only_its_reservation_and_other_games_continue(self):
        await self.exercise_interruption(cancel=False)

    async def test_cancelling_one_game_releases_its_slot_without_cancelling_other_game(self):
        await self.exercise_interruption(cancel=True)

    async def test_queued_admission_respects_other_games_reservation_without_starting_clock(self):
        self.config.max_daily_tokens = 2000
        first = self.add_game('first', usage=900)
        healthy = self.add_game('healthy', usage=100)
        denied = self.add_game('denied')
        for key in (first, healthy, denied):
            self.supervisor.schedule(key)
        denied_task = self.supervisor.tasks[denied]
        await self.wait_started(first, healthy)
        self.assertEqual(self.budget(), (2, 0, 2000))
        self.clock.advance(20)
        await self.finish(first)
        await asyncio.wait_for(denied_task, 5)
        # The first action used 900 tokens and the healthy action still holds
        # 1000. A fresh 1000-token reservation cannot fit, even in a free slot.
        self.assertEqual(self.budget(), (2, 900, 1000))
        self.assertFalse(self.started[denied].is_set())
        state = self.store.get(denied)
        self.assertEqual(state['worker']['state'], 'error')
        self.assertEqual(state['worker']['error_code'], 'daily_resource_limit')
        self.assertIsNone(state['active_started'])
        self.assertEqual(state['clock_used'], 200)
        self.assertEqual(state['clock_events'], [])
        self.assertEqual(state['moves'], [])
        self.assertEqual(state['thread_id'], self.initial[denied]['thread_id'])
        self.assertEqual(self.closed[denied], 0)
        self.assertFalse(self.supervisor.tasks[healthy].done())
        self.clock.advance(10)
        await self.finish(healthy)
        self.assert_completed(first, 20)
        self.assert_completed(healthy, 30)
        self.assertEqual(self.budget(), (2, 1000, 0))
        self.assertEqual(self.supervisor.tasks, {})


if __name__ == '__main__':
    unittest.main()
