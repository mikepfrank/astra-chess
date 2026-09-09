import asyncio
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
import uuid

from fastapi.testclient import TestClient

from astra_web.app import create_app
from astra_web.config import Config
from astra_web.store import Store, Conflict
from astra_web.supervisor import Supervisor
from astra_web import chess_game as game


class RefundFixture:
    def prepare(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.config = Config(data_dir=Path(self.directory.name), origin='http://testserver',
                             player_mode='disabled', secure_cookies=False, smtp_host='', smtp_from='')
        self.config.validate()
        self.store = Store(self.config)
        self.supervisor = Supervisor(self.config, self.store, SimpleNamespace(memory_for_user=lambda _: ''))
        state = game.new_game({'id': 'fixture-user', 'name': 'Fixture'}, 'white', self.config)
        for move in ('e2e4', 'e7e5', 'g1f3', 'b8c6', 'c2c3'):
            game.apply_move(state, move, 'astra' if game.side_to_move(state) == 'black' else 'human')
        state.update(clock_used=200.0, worker={'state': 'error', 'message': 'Interrupted'})
        self.store.create(state)
        self.game_id = state['id']
        self.sequence = 0

    def legacy_attempt(self, seconds, *, ply=None, own_moves=None, failed=True, completed=False, accepted=False, evidence=True):
        state = self.store.get(self.game_id)
        ply = len(state['moves']) if ply is None else ply
        own_moves = state['own_moves'] if own_moves is None else own_moves
        start = 1000.0 + self.sequence * 1000
        self.sequence += 1
        event = {'started_at': start, 'ended_at': start + seconds, 'charged_seconds': seconds,
                 'own_moves_before_credit': own_moves, 'remaining_before_credit': 5000.0}
        self.store.mutate(self.game_id, lambda s: (s['clock_events'].append(event),
            s.update(clock_used=s['clock_used'] + seconds)), kind='fixture_charge')
        if evidence:
            records = [('worker_started', start + .001, {'ply': ply, 'request': None})]
            if accepted:
                records.append(('astra_action', start + seconds - .001, {'ply': ply + 1, 'request': {'action': 'move'}}))
            if completed:
                records.append(('worker_completed', start + seconds - .0005, {'ply': ply, 'request': None}))
            records.append(('clock_settled', start + seconds + .001, {'ply': ply + int(accepted), 'request': {'elapsed': seconds}}))
            if failed:
                records.append(('worker_error', start + seconds + .002, {'type': 'ValueError', 'message': 'Turn token allowance reached'}))
            with self.store.connection() as db:
                db.executemany('INSERT INTO events(game_id,at,kind,data) VALUES(?,?,?,?)',
                               [(self.game_id, at, kind, json.dumps(data)) for kind, at, data in records])

    def retry(self, request_id=None, version=None):
        request_id = request_id or uuid.uuid4().hex
        return self.store.mutate(self.game_id, lambda s: None, version=version, request_id=request_id,
            body={'action': 'retry'}, kind='human_action', transaction_hook=lambda s, db:
                self.supervisor.refund_retry_clock(s, db, request_id))


class RetryRefundTests(RefundFixture, unittest.TestCase):
    def setUp(self):
        self.prepare()

    def test_all_three_legacy_failed_attempts_restore_original_current_ply_start(self):
        for seconds in (31.25, 48.5, 22.75):
            self.legacy_attempt(seconds)
        reservation = self.store.reserve()
        self.store.settle(reservation, 1234)
        with self.store.connection() as db:
            budget_before = tuple(db.execute('SELECT turns,tokens,reserved FROM budget').fetchone())
        self.assertEqual(self.store.get(self.game_id)['clock_used'], 302.5)
        refunded = self.retry('accepted-retry-request')
        self.assertEqual(refunded['clock_used'], 200.0)
        self.assertEqual(len(refunded['clock_refunds']), 1)
        record = refunded['clock_refunds'][0]
        self.assertEqual(record['seconds'], 102.5)
        self.assertEqual(record['ply'], 5)
        self.assertEqual(record['reason'], 'human_requested_retry_after_interruption')
        self.assertEqual(len(record['attempts']), 3)
        self.assertTrue(all(event['refund_id'] == record['id'] for event in refunded['clock_events']))
        with self.store.connection() as db:
            self.assertEqual(tuple(db.execute('SELECT turns,tokens,reserved FROM budget').fetchone()), budget_before)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM events WHERE kind='retry_clock_refund'").fetchone()[0], 1)

    def test_duplicate_and_later_retry_cannot_refund_the_same_charge_again(self):
        self.legacy_attempt(20)
        once = self.retry('same-request-id')
        duplicate = self.retry('same-request-id', version=0)
        self.assertEqual(duplicate, once)
        again = self.retry('different-request-id')
        self.assertEqual(again['clock_used'], 200)
        self.assertEqual(len(again['clock_refunds']), 1)
        self.legacy_attempt(7)
        third = self.retry()
        self.assertEqual(third['clock_used'], 200)
        self.assertEqual([record['seconds'] for record in third['clock_refunds']], [20, 7])

    def test_old_accepted_normal_or_unsubstantiated_charges_are_never_refunded(self):
        self.legacy_attempt(40, ply=3, own_moves=1, accepted=True)
        self.legacy_attempt(20, completed=True)
        self.legacy_attempt(15, failed=False)
        self.legacy_attempt(10, evidence=False)
        self.legacy_attempt(5)
        final = self.retry()
        self.assertEqual(final['clock_used'], 285)
        self.assertEqual(final['clock_refunds'][0]['seconds'], 5)
        self.assertEqual(len(final['clock_refunds'][0]['attempts']), 1)

    def test_no_refund_during_active_attempt_or_human_turn_and_no_overrefund(self):
        self.legacy_attempt(20)
        self.store.mutate(self.game_id, lambda s: s.update(active_started=123.0))
        self.assertEqual(self.retry()['clock_used'], 220)
        self.store.mutate(self.game_id, lambda s: s.update(active_started=None, clock_used=10.0))
        self.assertEqual(self.retry()['clock_used'], 10, 'Inconsistent totals must not produce a guessed refund')
        self.store.mutate(self.game_id, lambda s: (s.update(clock_used=220.0), game.apply_move(s, 'g8f6', 'astra')))
        self.assertEqual(self.retry()['clock_used'], 220)
        self.assertNotIn('clock_refunds', self.store.get(self.game_id))

    def test_stale_retries_and_rolled_back_mutations_have_no_refund_effect(self):
        self.legacy_attempt(20)
        with self.assertRaises(Conflict):
            self.retry(version=-1)
        self.assertEqual(self.store.get(self.game_id)['clock_used'], 220)

        def refund_then_fail(state, db):
            self.supervisor.refund_retry_clock(state, db, 'rolled-back-request')
            raise ValueError('Fixture rejection')

        with self.assertRaises(ValueError):
            self.store.mutate(self.game_id, lambda s: None, transaction_hook=refund_then_fail)
        state = self.store.get(self.game_id)
        self.assertEqual(state['clock_used'], 220)
        self.assertNotIn('clock_refunds', state)
        with self.store.connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM events WHERE kind='retry_clock_refund'").fetchone()[0], 0)

    def test_restart_charge_is_bounded_and_only_refunded_on_explicit_retry(self):
        started = time.time() - 100
        self.store.mutate(self.game_id, lambda s: s.update(active_started=started,
            active_deadline=started + 25, worker={'state': 'thinking', 'message': 'Before crash'}))
        with self.store.connection() as db:
            db.execute('INSERT INTO events(game_id,at,kind,data) VALUES(?,?,?,?)',
                (self.game_id, started + .001, 'worker_started', json.dumps({'ply': 5, 'request': None})))
        self.supervisor.recover()
        recovered = self.store.get(self.game_id)
        self.assertEqual(recovered['clock_used'], 225)
        self.assertIsNone(recovered['active_started'])
        self.assertEqual(recovered['clock_events'][-1]['error_kind'], 'service_restart')
        self.assertNotIn('clock_refunds', recovered)
        self.assertEqual(self.supervisor.tasks, {})
        final = self.retry()
        self.assertEqual(final['clock_used'], 200)
        self.assertEqual(final['clock_refunds'][0]['seconds'], 25)

    def test_operator_clock_baseline_supersedes_old_failures_but_not_future_failures(self):
        self.legacy_attempt(30)
        self.legacy_attempt(40)
        self.store.mutate(self.game_id, lambda s: s.update(clock_used=240.0),
            kind='operator_clock_set', body={'remaining_seconds': 5220,
                'reason': 'User requested an exact clock baseline'})
        baseline = self.retry()
        self.assertEqual(baseline['clock_used'], 240)
        self.assertNotIn('clock_refunds', baseline)
        self.assertTrue(all('refund_id' not in event for event in baseline['clock_events']))
        self.legacy_attempt(15)
        restored = self.retry()
        self.assertEqual(restored['clock_used'], 240)
        self.assertEqual(restored['clock_refunds'][0]['seconds'], 15)
        self.assertEqual(len(restored['clock_refunds'][0]['attempts']), 1)
        self.assertTrue(all('refund_id' not in event for event in restored['clock_events'][:2]))
        self.assertEqual(restored['clock_events'][2]['refunded_seconds'], 15)

    def test_api_retry_refunds_once_and_resume_alone_does_not(self):
        app = create_app(self.config)
        with TestClient(app) as client:
            identity = client.post('/api/auth/register', json={'name': 'Refund fixture'}, headers={'Origin': self.config.origin}).json()
            headers = {'Origin': self.config.origin, 'X-CSRF-Token': identity['csrf_token']}
            created = client.post('/api/games', json={'side': 'white'}, headers=headers).json()
            self.game_id = created['id']
            self.store, self.supervisor = app.state.store, app.state.supervisor
            self.store.mutate(self.game_id, lambda s: (game.apply_move(s, 'e2e4', 'human'),
                s.update(clock_used=12.0, worker={'state': 'error', 'message': 'Interrupted'})))
            self.legacy_attempt(19)
            scheduled = []
            self.supervisor.schedule = scheduled.append

            def send(action, request_id):
                body = {'action': action, 'version': self.store.get(self.game_id)['version'], 'request_id': request_id}
                return client.post(f'/api/games/{self.game_id}/actions', json=body, headers=headers), body

            resumed, _ = send('resume', 'resume-without-refund')
            self.assertEqual(resumed.status_code, 200)
            self.assertEqual(resumed.json()['clock']['used_seconds'], 31)
            retried, body = send('retry', 'retry-refunds-once')
            self.assertEqual(retried.status_code, 200, retried.text)
            self.assertEqual(retried.json()['clock']['used_seconds'], 12)
            count = len(scheduled)
            duplicate = client.post(f'/api/games/{self.game_id}/actions', json=body, headers=headers)
            self.assertEqual(duplicate.status_code, 200)
            self.assertEqual(duplicate.json()['clock']['used_seconds'], 12)
            self.assertEqual(len(scheduled), count)


class ActualAttemptTests(RefundFixture, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.prepare()

    async def test_new_failed_attempts_record_classification_and_fresh_status_flags(self):
        statuses = []
        identity_ids = []
        self.store.mutate(self.game_id, lambda s: game.message(s, 'human', 'A new turn message.'))
        identity = SimpleNamespace(memory_for_user=lambda user_id: identity_ids.append(user_id) or 'Protected-account note')

        class Player:
            def __init__(self, config):
                pass

            async def run(self, game_id, snapshot, tool, emit, thread_id=None):
                statuses.append(await tool('chess_status', {}))
                await tool('chess_candidate', {'move': 'g8f6', 'concern': 'Test candidate'})
                await tool('chess_query', {'seconds': 1})
                statuses.append(await tool('chess_status', {}))
                await asyncio.sleep(.005)
                raise ValueError('Turn token allowance reached')

            async def close(self):
                pass

        self.supervisor = Supervisor(self.config, self.store, identity, Player)

        async def query(*args):
            return {'fallback': False}, 'fixture.result.json'

        self.supervisor._query = query
        for _ in range(2):
            with self.assertRaises(ValueError):
                await self.supervisor._active_run(self.game_id)
        before_retry = self.store.get(self.game_id)
        self.assertGreater(before_retry['clock_used'], 200)
        self.assertTrue(all(event['outcome'] == 'interrupted' and event['error_kind'] == 'token_limit'
                            and event['ply'] == 5 and event['attempt_id'] for event in before_retry['clock_events']))
        for index in (0, 2):
            self.assertEqual(statuses[index]['current_attempt'], {'candidate_recorded': False, 'root_query_completed': False, 'move_accepted': False})
            self.assertEqual(statuses[index]['memory'], 'Protected-account note')
            self.assertEqual(statuses[index]['fen'], before_retry['fen'])
            self.assertEqual(statuses[index]['ply'], 5)
            self.assertIn('g8f6', statuses[index]['legal_moves'])
            self.assertEqual(statuses[index]['messages'][-1]['text'], 'A new turn message.')
        for index in (1, 3):
            self.assertTrue(statuses[index]['current_attempt']['root_query_completed'])
        self.assertTrue(all(user_id == 'fixture-user' for user_id in identity_ids))
        final = self.retry()
        self.assertAlmostEqual(final['clock_used'], 200)
        self.assertEqual(len(final['clock_refunds'][0]['attempts']), 2)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT tokens FROM budget').fetchone()[0], 2 * self.config.max_turn_tokens)

    async def test_accepted_move_then_commentary_failure_is_not_refundable(self):
        class Player:
            def __init__(self, config):
                pass

            async def run(self, game_id, snapshot, tool, emit, thread_id=None):
                await tool('chess_candidate', {'move': 'g8f6', 'concern': 'Test candidate'})
                await tool('chess_query', {'seconds': 1})
                await asyncio.sleep(.005)
                await tool('chess_choose', {'action': 'move', 'move': 'g8f6', 'note': 'Accepted test move'})
                status = await tool('chess_status', {})
                assert status['current_attempt']['move_accepted'] is True
                raise ConnectionError('Post-move commentary connection failed')

            async def close(self):
                pass

        self.supervisor = Supervisor(self.config, self.store, SimpleNamespace(memory_for_user=lambda _: ''), Player)

        async def query(*args):
            return {'fallback': False}, 'fixture.result.json'

        self.supervisor._query = query
        with self.assertRaises(ConnectionError):
            await self.supervisor._active_run(self.game_id)
        accepted = self.store.get(self.game_id)
        self.assertEqual(accepted['clock_events'][-1]['outcome'], 'accepted_action')
        self.assertEqual(self.retry()['clock_used'], accepted['clock_used'])
        self.store.mutate(self.game_id, lambda s: game.apply_move(s, 'd2d4', 'human'))
        self.assertEqual(self.retry()['clock_used'], accepted['clock_used'])
        self.assertNotIn('clock_refunds', self.store.get(self.game_id))


if __name__ == '__main__':
    unittest.main()
