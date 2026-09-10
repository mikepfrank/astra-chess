"""Real offline archive/API tests: no model calls and no tactical searches."""
import asyncio
import base64
from contextlib import ExitStack
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from astra_web.app import create_app
from astra_web import chess_game as game
from astra_web.config import Config
from astra_web.replay_library import ReplayLibrary, standalone_csp
from astra_web.store import Store
from test_replay_archive import EmbeddedReplay


class ReplayLibraryTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.folder = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.config = Config(data_dir=self.folder, origin='http://testserver', player_mode='disabled',
                             secure_cookies=False, smtp_host='', smtp_from='')
        self.app = create_app(self.config)
        self.client = self.stack.enter_context(TestClient(self.app))
        response = self.client.post('/api/auth/register', json={'name': 'Replay owner'},
                                    headers={'Origin': self.config.origin})
        self.assertEqual(response.status_code, 200)
        self.user = response.json()['user']
        self.client.headers.update({'Origin': self.config.origin, 'X-CSRF-Token': response.json()['csrf_token']})
        self.state = self.fixture()
        self.game_id = self.state['id']
        self.endpoint = f'/api/games/{self.game_id}/archive'

    def fixture(self, name=None):
        state = game.new_game(self.user, 'white', self.config)
        if name is not None:
            state['name'] = name
        for index, uci in enumerate(('f2f3', 'e7e5', 'g2g4', 'd8h4')):
            game.apply_move(state, uci, 'human' if index % 2 == 0 else 'astra')
            state['moves'][index]['at'] = 1001.0 + index
        state.update(created_at=1000.0, updated_at=1006.0, last_human_activity=1006.0,
                     thread_id='PRIVATE CODEX THREAD', clock_used=172.25,
                     private_memory='PRIVATE USER MEMORY')
        state['messages'] = [
            {'id': 'PRIVATE-MESSAGE-ID', 'author': 'human', 'ply': 0, 'text': 'UNIQUE PRIVATE CHAT', 'created_at': 1000.5},
            {'id': 'PRIVATE-MESSAGE-ID-2', 'author': 'astra', 'ply': 4, 'text': 'Good game!', 'created_at': 1004.5},
        ]
        self.app.state.store.create(state)
        return state

    def wait_done(self, endpoint=None, timeout=10):
        endpoint = endpoint or self.endpoint
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            response = self.client.get(endpoint)
            self.assertEqual(response.status_code, 200, response.text)
            data = response.json()
            if data['state'] != 'building':
                return data
            time.sleep(.04)
        self.fail('Offline archive build did not finish')

    def generate(self, chat=False, endpoint=None):
        endpoint = endpoint or self.endpoint
        started = self.client.post(endpoint, json={'include_commentary': chat})
        self.assertEqual(started.status_code, 202, started.text)
        self.assertEqual(started.json()['state'], 'building')
        ready = self.wait_done(endpoint)
        self.assertEqual(ready['state'], 'ready', ready)
        self.assertEqual(ready['include_commentary'], chat)
        return ready

    def publish(self, ready):
        response = self.client.post(self.endpoint + '/publish', json={'archive_id': ready['archive_id']})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_moves_only_download_is_standalone_private_and_does_not_change_game_or_clock(self):
        before = deepcopy(self.app.state.store.get(self.game_id))
        with self.app.state.store.connection() as db:
            db.execute('INSERT INTO budget(day,turns,tokens,reserved) VALUES(?,?,?,?)', ('2026-09-10', 9, 123456, 0))
        self.assertEqual(self.client.get(self.endpoint).json()['state'], 'none')
        ready = self.generate()
        response = self.client.get(ready['download_url'])
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers['content-disposition'].startswith('attachment;'))
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertIn("script-src 'sha256-", response.headers['content-security-policy'])
        self.assertNotIn("script-src 'unsafe-inline'", response.headers['content-security-policy'])
        embedded = EmbeddedReplay(response.text).value()
        self.assertEqual(len(embedded['frames']), 5)
        self.assertEqual(embedded['messages'], [])
        self.assertEqual(embedded['archive']['gameId'], ready['archive_id'])
        for private in ('UNIQUE PRIVATE CHAT', 'PRIVATE CODEX THREAD', 'PRIVATE USER MEMORY',
                        'PRIVATE-MESSAGE-ID', self.user['id'], self.game_id):
            self.assertNotIn(private, response.text)
        self.assertFalse(ready['published'])
        self.assertEqual(self.client.get('/api/public-replays').json()['games'], [])
        self.assertEqual(self.app.state.store.get(self.game_id), before)
        with self.app.state.store.connection() as db:
            self.assertEqual(tuple(db.execute('SELECT day,turns,tokens,reserved FROM budget').fetchone()),
                             ('2026-09-10', 9, 123456, 0))

    def test_explicit_chat_choice_preserves_ply_alignment_and_escapes_text(self):
        payload = '</script><script>alert("not executable")</script>'
        self.app.state.store.mutate(self.game_id, lambda s: s['messages'][0].update(text=payload))
        ready = self.generate(True)
        page = self.client.get(ready['download_url']).text
        self.assertNotIn(payload, page)
        embedded = EmbeddedReplay(page).value()
        self.assertEqual([m['ply'] for m in embedded['messages']], [0, 4])
        self.assertEqual(embedded['messages'][0]['text'], payload)
        self.assertEqual(embedded['messages'][1]['text'], 'Good game!')

    def test_publication_requires_ready_revision_and_never_publishes_on_download(self):
        self.assertEqual(self.client.post(self.endpoint + '/publish', json={'archive_id': 'a' * 32}).status_code, 409)
        first = self.generate()
        self.client.get(first['download_url'])
        self.assertEqual(self.client.get('/api/public-replays').json()['total'], 0)
        second = self.generate(True)
        self.assertEqual(self.client.post(self.endpoint + '/publish', json={'archive_id': first['archive_id']}).status_code, 409)
        self.assertEqual(self.client.get(first['download_url']).status_code, 409)
        published = self.publish(second)
        again = self.publish(second)
        self.assertEqual(published['public_url'], again['public_url'])
        self.assertEqual(self.client.get('/api/public-replays').json()['total'], 1)

    def test_rebuilding_private_archive_preserves_existing_public_snapshot_and_chat_choice(self):
        original = self.generate(False)
        published = self.publish(original)
        public_url = published['public_url']
        public_page = self.client.get(public_url)
        self.assertEqual(public_page.status_code, 200)
        self.assertEqual(public_page.headers['cache-control'], 'no-store')
        newer = self.generate(True)
        self.assertEqual(newer['published_archive_id'], original['archive_id'])
        self.assertFalse(newer['public_include_commentary'])
        self.assertTrue(newer['include_commentary'])
        self.assertEqual(self.client.get(public_url).text, public_page.text)
        self.assertNotIn('UNIQUE PRIVATE CHAT', self.client.get(public_url).text)
        replacement = self.publish(newer)
        self.assertNotEqual(replacement['public_url'], public_url)
        self.assertEqual(self.client.get(public_url).status_code, 404)
        self.assertIn('UNIQUE PRIVATE CHAT', self.client.get(replacement['public_url']).text)

    def test_revoke_removes_listing_and_url_but_preserves_download_across_restart(self):
        ready = self.generate(True)
        published = self.publish(ready)
        expected_download = self.client.get(ready['download_url']).text
        url = published['public_url']
        revoked = self.client.delete(self.endpoint + '/publication')
        self.assertEqual(revoked.status_code, 200)
        self.assertFalse(revoked.json()['published'])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.delete(self.endpoint + '/publication').status_code, 200)
        self.assertEqual(self.client.get(ready['download_url']).text, expected_download)
        self.assertNotIn(url, (self.folder / 'public-replays/index.html').read_text(encoding='utf-8'))
        # A newly constructed manager uses only SQLite/files; revocation survives.
        restarted = ReplayLibrary(self.config, self.app.state.store)
        restarted.recover()
        self.assertFalse(restarted.status(self.game_id)['published'])
        self.assertEqual(restarted.download(self.game_id, ready['archive_id']), expected_download)
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as error:
            restarted.public_page(url.split('/')[-1][:-5])
        self.assertEqual(error.exception.status_code, 404)
        self.assertEqual(restarted.public_entries()['games'], [])

    def test_publication_persists_across_restart_and_public_metadata_contains_no_private_ids(self):
        ready = self.generate(True)
        published = self.publish(ready)
        restarted = ReplayLibrary(self.config, self.app.state.store)
        restarted.recover()
        self.assertTrue(restarted.status(self.game_id)['published'])
        self.assertTrue(restarted.status(self.game_id)['public_include_commentary'])
        self.assertIn('UNIQUE PRIVATE CHAT', restarted.public_page(published['public_url'].split('/')[-1][:-5]))
        listing = restarted.public_entries()
        self.assertEqual(listing['total'], 1)
        encoded = json.dumps(listing)
        for private in (self.game_id, self.user['id'], ready['archive_id'], 'PRIVATE USER MEMORY', 'UNIQUE PRIVATE CHAT'):
            self.assertNotIn(private, encoded)

    def test_owner_isolation_and_csrf_apply_to_all_private_archive_actions(self):
        ready = self.generate()
        other = TestClient(self.app)
        self.addCleanup(other.close)
        registration = other.post('/api/auth/register', json={'name': 'Other player'}, headers={'Origin': self.config.origin})
        other.headers.update({'Origin': self.config.origin, 'X-CSRF-Token': registration.json()['csrf_token']})
        for method, url, body in (
            ('get', self.endpoint, None), ('get', ready['download_url'], None),
            ('post', self.endpoint, {'include_commentary': False}),
            ('post', self.endpoint + '/publish', {'archive_id': ready['archive_id']}),
            ('delete', self.endpoint + '/publication', None),
        ):
            arguments = {} if body is None else {'json': body}
            self.assertEqual(getattr(other, method)(url, **arguments).status_code, 404, url)
        for url, body in ((self.endpoint, {'include_commentary': False}),
                          (self.endpoint + '/publish', {'archive_id': ready['archive_id']})):
            self.assertEqual(self.client.post(url, json=body, headers={'X-CSRF-Token': 'wrong'}).status_code, 403)
            self.assertEqual(self.client.post(url, json=body, headers={'Origin': 'https://evil.invalid'}).status_code, 403)
        self.assertEqual(self.client.delete(self.endpoint + '/publication', headers={'X-CSRF-Token': 'wrong'}).status_code, 403)
        self.assertEqual(self.client.get(self.endpoint + '/download?archive_id=../../other').status_code, 404)

    def test_only_finished_games_and_explicit_boolean_chat_option_are_accepted(self):
        for payload in ({}, {'include_commentary': 'false'}, {'include_commentary': 0},
                        {'include_commentary': False, 'publish': True}):
            self.assertEqual(self.client.post(self.endpoint, json=payload).status_code, 400)
        self.app.state.store.mutate(self.game_id, lambda s: s.update(status='active'))
        self.assertEqual(self.client.post(self.endpoint, json={'include_commentary': False}).status_code, 409)
        self.assertEqual(self.client.get(self.endpoint).json()['state'], 'none')

    def test_public_index_escapes_names_has_experiment_link_and_is_materialized(self):
        malicious = '<script>window.PWNED=true</script>'
        self.app.state.store.mutate(self.game_id, lambda s: s.update(name=malicious))
        ready = self.generate(False)
        replay = self.client.get(ready['download_url']).text
        self.assertNotIn(malicious, replay)
        self.assertEqual(replay.count('<script'), 2)
        published = self.publish(ready)
        index = self.client.get('/games/')
        self.assertEqual(index.status_code, 200)
        self.assertNotIn(malicious, index.text)
        self.assertIn('&lt;script&gt;', index.text)
        self.assertIn('Moves only', index.text)
        self.assertIn('href="/experiments/"', index.text)
        self.assertIn(published['public_url'], index.text)
        self.assertEqual((self.folder / 'public-replays/index.html').read_text(encoding='utf-8'), index.text)
        self.assertEqual(index.headers['cache-control'], 'no-store')
        self.assertIn("script-src 'none'", index.headers['content-security-policy'])
        self.assertEqual(self.client.get('/games/?page=0').status_code, 400)

    def test_build_failure_is_private_retryable_and_recovery_marks_interrupted_build(self):
        with patch('astra_web.replay_archive.build_archive', side_effect=RuntimeError('PRIVATE INTERNAL PATH')):
            response = self.client.post(self.endpoint, json={'include_commentary': False})
            self.assertEqual(response.status_code, 202)
            failed = self.wait_done()
            self.assertEqual(failed['state'], 'error')
            self.assertNotIn('PRIVATE INTERNAL PATH', json.dumps(failed))
            self.assertIsNone(failed['download_url'])
        ready = self.generate()
        with self.app.state.store.connection() as db:
            db.execute("UPDATE replay_archives SET state='building' WHERE game_id=?", (self.game_id,))
        self.app.state.replay_library.recover()
        recovered = self.client.get(self.endpoint).json()
        self.assertEqual(recovered['state'], 'error')
        self.assertIn('interrupted', recovered['error'])
        self.assertNotEqual(self.generate()['archive_id'], ready['archive_id'])

    def test_build_queue_is_bounded_and_duplicate_click_cannot_start_another_build(self):
        started, release = threading.Event(), threading.Event()
        actual = self.app.state.replay_library._construct
        concurrent, maximum = [0], [0]
        def slow(*args):
            concurrent[0] += 1
            maximum[0] = max(maximum[0], concurrent[0])
            started.set()
            release.wait(10)
            try:
                return actual(*args)
            finally:
                concurrent[0] -= 1
        second, third = self.fixture(), self.fixture()
        with patch('astra_web.replay_library.MAX_PENDING_BUILDS', 2), patch.object(self.app.state.replay_library, '_construct', slow):
            try:
                first = self.client.post(self.endpoint, json={'include_commentary': False})
                self.assertEqual(first.status_code, 202)
                self.assertTrue(started.wait(2))
                self.assertEqual(self.client.post(self.endpoint, json={'include_commentary': True}).status_code, 409)
                next_endpoint = f'/api/games/{second["id"]}/archive'
                self.assertEqual(self.client.post(next_endpoint, json={'include_commentary': False}).status_code, 202)
                self.assertEqual(self.client.post(f'/api/games/{third["id"]}/archive', json={'include_commentary': False}).status_code, 503)
                self.assertEqual(len(self.app.state.replay_library.tasks), 2)
            finally:
                release.set()
            self.assertEqual(self.wait_done()['state'], 'ready')
            self.assertEqual(self.wait_done(next_endpoint)['state'], 'ready')
        self.assertEqual(maximum[0], 1)

    def test_chat_omitted_build_can_archive_legacy_malformed_chat_without_exposing_it(self):
        self.app.state.store.mutate(self.game_id, lambda s: s['messages'][0].update(author='private-internal-role'))
        ready = self.generate(False)
        page = self.client.get(ready['download_url']).text
        self.assertNotIn('private-internal-role', page)
        self.assertEqual(EmbeddedReplay(page).value()['messages'], [])


class ReplayCspTests(unittest.TestCase):
    def test_hashes_exact_normalized_script_text_and_never_allows_external_script(self):
        block = '\nconst message = "<&";\n'
        digest = base64.b64encode(hashlib.sha256(block.encode()).digest()).decode()
        csp = standalone_csp('<script>' + block.replace('\n', '\r\n') + '</script>')
        self.assertIn("'sha256-" + digest + "'", csp)
        self.assertIn("connect-src 'none'", csp)
        self.assertIn("script-src-attr 'none'", csp)
        self.assertNotIn('https:', csp)
        with self.assertRaises(ValueError):
            standalone_csp('<script src="https://example.invalid/a.js"></script>')

    def test_manager_close_drains_jobs_before_returning(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as folder:
                config = Config(data_dir=Path(folder), player_mode='disabled')
                config.validate()
                manager = ReplayLibrary(config, Store(config))
                done = []
                async def job():
                    await asyncio.to_thread(time.sleep, .03)
                    done.append(True)
                manager.tasks['fixture'] = asyncio.create_task(job())
                await manager.close()
                self.assertEqual(done, [True])
                self.assertTrue(manager.closing)
        asyncio.run(scenario())


if __name__ == '__main__':
    unittest.main()
