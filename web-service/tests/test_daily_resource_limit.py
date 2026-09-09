"""Daily admission failures must be explicit and spend no additional resources."""
import asyncio
from datetime import datetime, timezone
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from astra_web import chess_game as game
from astra_web.config import Config
from astra_web.store import DailyResourceLimit, Store
from astra_web.supervisor import Supervisor


class DailyResourceLimitTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.config = Config(data_dir=Path(folder.name), player_mode='disabled',
            max_turn_tokens=3_000_000, max_daily_tokens=20_000_000, max_daily_turns=500)
        self.config.validate()
        self.store = Store(self.config)
        state = game.new_game({'id': 'fixture', 'name': 'Fixture'}, 'white', self.config)
        game.apply_move(state, 'e2e4', 'human')
        state['clock_used'] = 200.0
        self.store.create(state)
        self.game_id = state['id']
        self.day = datetime.now(timezone.utc).date().isoformat()

    def budget(self):
        with self.store.connection() as db:
            return [tuple(row) for row in db.execute('SELECT day,turns,tokens,reserved FROM budget ORDER BY day')]

    def seed_budget(self, turns=0, tokens=0, reserved=0):
        with self.store.connection() as db:
            db.execute('INSERT OR REPLACE INTO budget(day,turns,tokens,reserved) VALUES(?,?,?,?)',
                (self.day, turns, tokens, reserved))

    def event_count(self, kind):
        with self.store.connection() as db:
            return db.execute('SELECT COUNT(*) FROM events WHERE game_id=? AND kind=?',
                (self.game_id, kind)).fetchone()[0]

    def test_token_turn_and_reserved_denials_are_typed_and_leave_ledger_unchanged(self):
        state_before = self.store.get(self.game_id)
        for values in ({'tokens': 17_128_936}, {'turns': 500},
                       {'tokens': 16_000_000, 'reserved': 2_000_000}):
            with self.subTest(values=values):
                self.seed_budget(**values)
                before = self.budget()
                with self.assertRaises(DailyResourceLimit) as failure:
                    self.store.reserve()
                self.assertEqual(str(failure.exception), DailyResourceLimit.public_message)
                self.assertEqual(failure.exception.code, 'daily_resource_limit')
                self.assertEqual(self.budget(), before)
                self.assertEqual(self.store.get(self.game_id), state_before)

    def test_denied_first_reservation_rolls_back_new_budget_row(self):
        self.config.max_daily_tokens = self.config.max_turn_tokens - 1
        self.assertEqual(self.budget(), [])
        with self.assertRaises(DailyResourceLimit):
            self.store.reserve()
        self.assertEqual(self.budget(), [])

    def test_exact_budget_boundary_still_admits_one_reserved_turn(self):
        self.seed_budget(turns=499, tokens=17_000_000)
        self.assertEqual(self.store.reserve(), (self.day, 3_000_000))
        self.assertEqual(self.budget(), [(self.day, 500, 17_000_000, 3_000_000)])
        before = self.budget()
        with self.assertRaises(DailyResourceLimit):
            self.store.reserve()
        self.assertEqual(self.budget(), before)

    async def test_supervisor_explains_denial_without_player_clock_charge_or_automatic_retry(self):
        spawned = []

        def player_factory(config):
            spawned.append(True)
            raise AssertionError('Denied admission must not construct a player')

        supervisor = Supervisor(self.config, self.store,
            SimpleNamespace(memory_for_user=lambda _: ''), player_factory)
        for index, values in enumerate(({'tokens': 17_128_936}, {'turns': 500}), 1):
            with self.subTest(values=values):
                self.seed_budget(**values)
                before_budget = self.budget()
                before = self.store.get(self.game_id)
                supervisor.schedule(self.game_id)
                run = supervisor.tasks[self.game_id]
                supervisor.schedule(self.game_id)  # A queued rerun must not loop on this denial.
                self.assertIn(self.game_id, supervisor.rerun)
                await asyncio.wait_for(run, timeout=2)
                after = self.store.get(self.game_id)
                self.assertEqual(after['worker']['state'], 'error')
                self.assertEqual(after['worker']['error_code'], 'daily_resource_limit')
                self.assertIn('daily resource allowance', after['worker']['message'])
                self.assertIn('return later or ask the operator to increase the allowance', after['worker']['message'])
                for field in ('fen', 'moves', 'status', 'result', 'clock_used', 'active_started',
                              'own_moves', 'clock_events', 'queries', 'decisions', 'messages'):
                    self.assertEqual(after[field], before[field], field)
                self.assertEqual(game.clock(after), game.clock(before))
                self.assertEqual(self.budget(), before_budget)
                self.assertEqual(spawned, [])
                self.assertEqual(supervisor.tasks, {})
                self.assertEqual(supervisor.rerun, set())
                self.assertEqual(self.event_count('worker_started'), 0)
                self.assertEqual(self.event_count('clock_settled'), 0)
                self.assertEqual(self.event_count('queued'), index)
                self.assertEqual(self.event_count('worker_admission_denied'), index)

    async def test_ordinary_errors_keep_generic_text_even_when_their_text_mentions_daily_allowance(self):
        closed = []

        class Player:
            def __init__(self, config):
                pass

            async def run(self, *args, **kwargs):
                raise ValueError('daily resource allowance: internal fixture path C:/private/operator-file')

            async def close(self):
                closed.append(True)

        supervisor = Supervisor(self.config, self.store,
            SimpleNamespace(memory_for_user=lambda _: ''), Player)
        supervisor.schedule(self.game_id)
        await asyncio.wait_for(supervisor.tasks[self.game_id], timeout=2)
        worker = self.store.get(self.game_id)['worker']
        self.assertEqual(worker, {'state': 'error',
            'message': 'Astra’s response was interrupted. Your game and conversation are saved; you can retry.'})
        self.assertNotIn('operator-file', worker['message'])
        self.assertEqual(closed, [True])
        self.assertEqual(self.event_count('worker_admission_denied'), 0)
        self.assertEqual(self.event_count('worker_started'), 1)
        self.assertEqual(self.budget(), [(self.day, 1, self.config.max_turn_tokens, 0)])


if __name__ == '__main__':
    unittest.main()
