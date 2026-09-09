"""Finished-game conversation boundaries; temporary storage and fake players only."""
import asyncio
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit
import uuid

from fastapi.testclient import TestClient

from astra_web.app import create_app
from astra_web import chess_game as game
from astra_web.config import Config
from astra_web.store import Store
from astra_web.supervisor import Supervisor


class ChatPlayers:
    def __init__(self, behavior=None):
        self.behavior = behavior
        self.calls, self.closed = [], []
        self.started = threading.Event()
        self.active, self.max_active = 0, 0

    def __call__(self, config):
        owner = self

        class Player:
            async def run(self, game_id, snapshot, tool, emit, thread_id=None):
                owner.calls.append((game_id, snapshot, thread_id))
                owner.active += 1
                owner.max_active = max(owner.max_active, owner.active)
                owner.started.set()
                try:
                    if owner.behavior:
                        return await owner.behavior(snapshot, tool, emit)
                    await emit('Fixture post-game answer.')
                    return {'usage_tokens': 11}
                finally:
                    owner.active -= 1

            async def close(self):
                owner.closed.append(True)

        return Player()


class PostgameChatTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        folder = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.config = Config(data_dir=Path(folder), origin='http://testserver',
            player_mode='disabled', secure_cookies=False, smtp_host='', smtp_from='')

    def start(self, players=None):
        self.players = players or ChatPlayers()
        self.app = create_app(self.config, player_factory=self.players)
        self.client = self.stack.enter_context(TestClient(self.app))
        self.register(self.client, 'Fixture owner')
        created = self.client.post('/api/games', json={'side': 'white'})
        self.assertEqual(created.status_code, 201, created.text)
        self.game_id = created.json()['id']

        def finish(s):
            for uci, actor in (('e2e4', 'human'), ('e7e5', 'astra'), ('g1f3', 'human')):
                game.apply_move(s, uci, actor)
            game.finish(s, '0-1', 'resignation')
            s.update(thread_id='fixture-existing-thread', clock_used=5430.0,
                     engine_fingerprint='fixture-recorded-engine-revision')
            s['clock_events'].append({'started_at': 1000.0, 'ended_at': 1005.0,
                'charged_seconds': 5.0, 'outcome': 'interrupted', 'own_moves_before_credit': 1})
        self.app.state.store.mutate(self.game_id, finish)
        self.baseline = self.record()
        self.baseline_pgn = game.pgn(self.baseline)

    def register(self, client, name):
        result = client.post('/api/auth/register', json={'name': name}, headers={'Origin': self.config.origin})
        self.assertEqual(result.status_code, 200, result.text)
        client.headers.update({'Origin': self.config.origin, 'X-CSRF-Token': result.json()['csrf_token']})

    def record(self):
        return self.app.state.store.get(self.game_id)

    def send(self, action, *, client=None, **fields):
        body = {'action': action, 'version': self.record()['version'], 'request_id': uuid.uuid4().hex, **fields}
        response = (client or self.client).post(f'/api/games/{self.game_id}/actions', json=body)
        return response, body

    def wait_idle(self, expected_calls=0):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            if self.game_id not in self.app.state.supervisor.tasks and len(self.players.calls) >= expected_calls:
                return self.record()
            time.sleep(.005)
        self.fail('Fixture worker did not become idle')

    def assert_game_preserved(self):
        state = self.record()
        for key in ('status', 'result', 'termination', 'fen', 'moves', 'own_moves', 'clock_used',
                    'active_started', 'clock_events', 'draw_offer'):
            self.assertEqual(state[key], self.baseline[key], key)
        self.assertEqual(game.pgn(state), self.baseline_pgn)
        self.assertEqual(game.clock(state)['remaining_seconds'], 0)
        self.assertEqual(state.get('active_deadline'), self.baseline.get('active_deadline'))
        self.assertEqual(state.get('active_paused_seconds'), self.baseline.get('active_paused_seconds'))
        self.assertNotIn('clock_refunds', state)

    def test_finished_chat_reuses_thread_allows_readonly_tools_and_never_charges_clock_even_during_compaction(self):
        observations = []
        tick = [1000.0]
        wall = [time.time()]

        async def behavior(snapshot, tool, emit):
            self.assertEqual(snapshot['status'], 'finished')
            self.assertEqual(snapshot['remaining_turn_seconds'], self.config.ordinary_seconds)
            status = await tool('chess_status', {})
            self.assertEqual(status['legal_moves'], [])
            self.assertEqual(status['clock']['remaining_seconds'], 0)
            details = await tool('chess_query_details', {'query_index': 0, 'candidate_rank': 1})
            self.assertEqual(details['candidate']['root_move'], 'e7e5')
            for name, args in (
                ('chess_candidate', {'move': 'g8f6', 'concern': 'Must remain finished'}),
                ('chess_query', {'seconds': 1}),
                ('chess_critical', {'reason': 'Must remain finished'}),
                ('chess_choose', {'action': 'move', 'move': 'g8f6', 'note': 'Must remain finished'}),
                ('chess_choose', {'action': 'resign', 'note': 'Must remain finished'}),
                ('chess_choose', {'action': 'offer_draw', 'note': 'Must remain finished'})):
                with self.assertRaises(ValueError, msg=name):
                    await tool(name, args)
            await tool('_compaction', {'phase': 'started', 'item_id': 'postgame-summary'})
            tick[0] += 25
            wall[0] += 25
            paused = await tool('chess_status', {})
            observations.append(paused)
            await tool('_compaction', {'phase': 'completed', 'item_id': 'postgame-summary'})
            await tool('chess_comment', {'text': 'Fixture tool commentary.'})
            await emit('Fixture emitted commentary.')
            return {'usage_tokens': 11}

        self.start(ChatPlayers(behavior))
        relative = Path('games') / self.game_id / 'queries' / 'fixture.result.json'
        path = self.config.data_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'start_fen': self.baseline['fen'],
                                   'candidates': [{'root_move': 'e7e5'}]}), encoding='utf-8')
        self.app.state.store.mutate(self.game_id, lambda s: s['queries'].append({'ply': 1, 'path': str(relative)}))
        clock = SimpleNamespace(time=lambda: wall[0], monotonic=lambda: tick[0])
        with patch('astra_web.supervisor.time', clock), patch('astra_web.chess_game.time', clock):
            response, _ = self.send('message', text='How did your tactical engine help?')
            self.assertEqual(response.status_code, 200, response.text)
            state = self.wait_idle()
        self.assertEqual(state['worker']['state'], 'idle', state['worker'])
        self.assertEqual(len(self.players.calls), 1)
        self.assertEqual(self.players.calls[0][2], 'fixture-existing-thread')
        self.assertEqual(observations[0]['worker']['state'], 'compacting')
        self.assertFalse(observations[0]['clock']['paused'])
        self.assertEqual(observations[0]['clock']['used_seconds'], 5430)
        self.assertEqual(state['compaction_events'][-1]['paused_seconds'], 25)
        self.assertFalse(state['compaction_events'][-1]['clock_paused'])
        self.assertEqual([m['author'] for m in state['messages']], ['human', 'astra', 'astra'])
        self.assert_game_preserved()

    def test_followup_messages_are_serialized_and_duplicate_requests_do_not_start_extra_responses(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        async def behavior(snapshot, tool, emit):
            if len(self.players.calls) == 1:
                entered.set()
                self.assertTrue(await asyncio.to_thread(release.wait, 3))
            await emit('Fixture response ' + str(len(self.players.calls)))
            return {'usage_tokens': 11}

        self.start(ChatPlayers(behavior))
        first, first_body = self.send('message', text='First finished-game question')
        self.assertEqual(first.status_code, 200, first.text)
        self.assertTrue(entered.wait(2))
        second, second_body = self.send('message', text='Follow-up while you answer')
        self.assertEqual(second.status_code, 200, second.text)
        for body in (first_body, second_body):
            duplicate = self.client.post(f'/api/games/{self.game_id}/actions', json=body)
            self.assertEqual(duplicate.status_code, 200, duplicate.text)
        release.set()
        state = self.wait_idle(expected_calls=2)
        self.assertEqual(len(self.players.calls), 2)
        self.assertEqual(self.players.max_active, 1)
        self.assertEqual(len(self.players.closed), 2)
        self.assertTrue(all(call[2] == 'fixture-existing-thread' for call in self.players.calls))
        self.assertIn('Follow-up while you answer', [m['text'] for m in self.players.calls[1][1]['messages']])
        self.assertEqual(len([m for m in state['messages'] if m['author'] == 'human']), 2)
        self.assertEqual(len([m for m in state['messages'] if m['author'] == 'astra']), 2)
        self.assertEqual(self.app.state.supervisor.rerun, set())
        self.assert_game_preserved()

    def test_finished_retry_requires_error_or_disabled_preserves_result_and_never_refunds(self):
        async def behavior(snapshot, tool, emit):
            if len(self.players.calls) == 1:
                raise ConnectionError('Fixture post-game interruption')
            await emit('Recovered fixture conversation')
            return {'usage_tokens': 11}

        self.start(ChatPlayers(behavior))
        self.assertEqual(self.send('retry')[0].status_code, 400)
        self.assertEqual(self.send('message', text='A question after the game')[0].status_code, 200)
        self.assertEqual(self.wait_idle()['worker']['state'], 'error')
        self.assertEqual(len(self.players.calls), 1)
        retried, body = self.send('retry')
        self.assertEqual(retried.status_code, 200, retried.text)
        self.assertEqual(self.wait_idle()['worker']['state'], 'idle')
        duplicate = self.client.post(f'/api/games/{self.game_id}/actions', json=body)
        self.assertEqual(duplicate.status_code, 200, duplicate.text)
        self.assertEqual(len(self.players.calls), 2)
        self.assertEqual(self.send('retry')[0].status_code, 400)
        self.app.state.store.mutate(self.game_id, lambda s: s.update(worker={'state': 'disabled', 'message': 'Fixture disabled'}))
        response, _ = self.send('retry')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.wait_idle()['worker']['state'], 'idle')
        self.assertEqual(len(self.players.calls), 3)
        for action in ('move', 'resume', 'resign', 'offer_draw', 'claim_draw', 'accept_draw', 'decline_draw'):
            self.assertEqual(self.send(action, move='g8f6')[0].status_code, 400, action)
        self.assert_game_preserved()

    def test_other_user_cannot_chat_retry_or_share_finished_game(self):
        self.start()
        outsider = TestClient(self.app)
        self.stack.callback(outsider.close)
        self.register(outsider, 'Fixture outsider')
        for action, fields in (('message', {'text': 'Not my game'}), ('retry', {})):
            self.assertEqual(self.send(action, client=outsider, **fields)[0].status_code, 404)
        self.assertEqual(outsider.post(f'/api/games/{self.game_id}/share',
            json={'include_commentary': True}).status_code, 404)
        self.assertEqual(outsider.get(f'/api/games/{self.game_id}/pgn').status_code, 404)
        self.assertEqual(self.players.calls, [])
        self.assertEqual(self.record(), self.baseline)

    def test_public_replay_stays_immutable_until_explicitly_shared_again_with_commentary_choice(self):
        self.start()

        def share(comments):
            response = self.client.post(f'/api/games/{self.game_id}/share', json={'include_commentary': comments})
            self.assertEqual(response.status_code, 200, response.text)
            token = urlsplit(response.json()['url']).path.rsplit('/', 1)[-1]
            return token, self.client.get('/api/replays/' + token).json()

        token, old = share(True)
        self.assertEqual(self.send('message', text='Include this only if I share again')[0].status_code, 200)
        state = self.wait_idle()
        self.assertEqual(self.client.get('/api/replays/' + token).json(), old)
        newer, comments = share(True)
        self.assertEqual(comments['messages'], state['messages'])
        self.assertEqual(self.client.get('/api/replays/' + token).status_code, 404)
        without, private = share(False)
        self.assertEqual(private['messages'], [])
        self.assertEqual(self.client.get('/api/replays/' + newer).status_code, 404)
        self.assertEqual(private['moves'], old['moves'])
        self.assertNotEqual(without, newer)
        self.assert_game_preserved()

    def test_finished_chat_keeps_input_size_rate_and_total_message_limits(self):
        self.start()
        self.assertEqual(self.send('message', text='x' * 4001)[0].status_code, 400)
        self.assertEqual(self.send('message', text='')[0].status_code, 400)
        def recent(s):
            for _ in range(self.config.max_messages_per_minute):
                game.message(s, 'human', 'Fixture recent message')
        self.app.state.store.mutate(self.game_id, recent)
        self.assertEqual(self.send('message', text='One too many this minute')[0].status_code, 400)
        def full(s):
            s['messages'] = [{'author': 'astra', 'text': 'Fixture archived message', 'created_at': 1.0}] * 1000
        self.app.state.store.mutate(self.game_id, full)
        self.assertEqual(self.send('message', text='One too many in this game')[0].status_code, 400)
        self.assertEqual(self.players.calls, [])
        self.assert_game_preserved()

    def test_finished_response_retains_existing_commentary_capacity(self):
        async def behavior(snapshot, tool, emit):
            for index in range(9):
                await emit('Fixture answer part ' + str(index))
            return {'usage_tokens': 11}

        self.start(ChatPlayers(behavior))
        self.assertEqual(self.send('message', text='Tell me about the game')[0].status_code, 200)
        state = self.wait_idle()
        self.assertEqual(state['worker']['state'], 'error')
        self.assertEqual(len([m for m in state['messages'] if m['author'] == 'astra']), 8)
        self.assertEqual(len(self.players.calls), 1)
        self.assert_game_preserved()


class FinishQueuedWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_ending_game_cleans_worker_before_start_and_while_waiting_for_slot(self):
        for blocked in (False, True):
            with self.subTest(blocked=blocked), tempfile.TemporaryDirectory() as folder:
                config = Config(data_dir=Path(folder), player_mode='disabled')
                config.validate()
                store = Store(config)
                state = game.new_game({'id': 'fixture', 'name': 'Fixture'}, 'black', config)
                store.create(state)
                players = ChatPlayers()
                supervisor = Supervisor(config, store, SimpleNamespace(memory_for_user=lambda _: ''), players)
                if blocked:
                    await supervisor.slots.acquire()
                supervisor.schedule(state['id'])
                if blocked:
                    await asyncio.sleep(0)  # The task waits for a slot without admitting work.
                store.mutate(state['id'], lambda s: game.finish(s, '1-0', 'resignation'))
                await supervisor.cancel(state['id'])
                if blocked:
                    supervisor.slots.release()
                final = store.get(state['id'])
                self.assertEqual(final['status'], 'finished')
                self.assertEqual(final['worker']['state'], 'idle')
                self.assertEqual(final['clock_used'], 0)
                self.assertEqual(final['clock_events'], [])
                self.assertIsNone(final['active_started'])
                self.assertEqual(players.calls, [])
                self.assertEqual(supervisor.tasks, {})
                with store.connection() as db:
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM budget').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
