"""Public replay identity follows the saved game without exporting its binding."""
from copy import deepcopy
from html import escape
import json
from pathlib import Path
import secrets
import tempfile
import unittest

from fastapi.testclient import TestClient

from astra_web import chess_game as game
from astra_web.app import create_app
from astra_web.config import Config
from astra_web.player_profiles import saved_player_name
from astra_web.replay_library import ReplayLibrary
from astra_web.store import Store
from test_replay_archive import EmbeddedReplay


class ReplayBrandingTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.directory = Path(folder.name)

    def config(self, profile='astra', persona=None):
        config = Config(data_dir=self.directory, origin='http://testserver',
                        model_profile=profile, persona=persona,
                        player_mode='disabled', max_workers=1,
                        secure_cookies=False, smtp_host='', smtp_from='')
        config.validate()
        return config

    def finished(self, config, *, user=None, human_side='white'):
        state = game.new_game(user or {'id': 'private-owner-id', 'name': 'Replay owner'},
                              human_side, config)
        for index, uci in enumerate(('f2f3', 'e7e5', 'g2g4', 'd8h4')):
            actor = 'human' if game.side_to_move(state) == human_side else 'astra'
            game.apply_move(state, uci, actor)
            state['moves'][index]['at'] = 1001.0 + index
        state.update(created_at=1000.0, updated_at=1006.0, last_human_activity=1006.0,
                     thread_id='PRIVATE-THREAD-DO-NOT-SHARE',
                     player_prompt='PRIVATE-PROMPT-DO-NOT-SHARE')
        state['player_profile']['private_marker'] = 'PRIVATE-PROFILE-DO-NOT-SHARE'
        state['player_persona']['private_marker'] = 'PRIVATE-PERSONA-DO-NOT-SHARE'
        state['messages'] = [dict(id='private-message-id', author='astra', ply=4,
                                  text='That is checkmate.', created_at=1004.5)]
        return state

    def build_and_share(self, library, state):
        archive_id = secrets.token_hex(16)
        with library.store.connection() as db:
            db.execute("INSERT INTO replay_variant_jobs VALUES(?,?,?,'building',NULL,?)",
                       (state['id'], 1, archive_id, 1007.0))
        library._construct(deepcopy(state), archive_id, True)
        shared = library.share(state, archive_id, listed=True)
        token = Path(shared['share_url']).stem
        return library.public_page(token), token

    def assert_binding_private(self, text):
        for private in ('player_prompt', 'player_profile', 'player_persona',
                        'PRIVATE-PROMPT-DO-NOT-SHARE', 'PRIVATE-PROFILE-DO-NOT-SHARE',
                        'PRIVATE-PERSONA-DO-NOT-SHARE', 'PRIVATE-THREAD-DO-NOT-SHARE'):
            self.assertNotIn(private, text)

    def test_arcturus_archive_and_listing_keep_saved_identity_under_astra_site(self):
        state = self.finished(self.config('openrouter-glm', 'arcturus'))
        before = deepcopy(state)
        current = self.config('astra', 'astra')
        library = ReplayLibrary(current, Store(current))
        page, _ = self.build_and_share(library, state)

        self.assertEqual(state, before)
        entries = library.public_entries()
        self.assertEqual(entries['games'][0]['player_name'], 'Arcturus')
        index = library.index_page()
        self.assertIn('<title>Public game replays · Astra plays chess</title>', index)
        self.assertIn('Replay owner <span>vs.</span> Arcturus', index)
        self.assertNotIn('Replay owner <span>vs.</span> Astra', index)
        data = EmbeddedReplay(page).value()
        self.assertEqual(data['playerName'], 'Arcturus')
        self.assertEqual(data['archive']['playerName'], 'Arcturus')
        self.assertEqual(data['messages'][0]['name'], 'Arcturus')
        self.assertIn("Arcturus's actual moves", data['evaluations']['description'])
        self.assert_binding_private(page + index + json.dumps(entries))
        self.assertNotIn(state['id'], page + index + json.dumps(entries))
        self.assertNotIn(state['user_id'], page + index + json.dumps(entries))

    def test_old_astra_publication_without_name_keeps_astra_under_arcturus_site(self):
        state = self.finished(self.config('astra', 'astra'))
        for field in ('player_profile', 'player_persona', 'player_prompt'):
            state.pop(field)
        current = self.config('openrouter-glm', 'arcturus')
        library = ReplayLibrary(current, Store(current))
        page, token = self.build_and_share(library, state)
        # Existing listed publications predate the new public metadata field.
        with library.store.connection() as db:
            row = db.execute('SELECT metadata FROM replay_variant_shares WHERE token=?',
                             (token,)).fetchone()
            metadata = json.loads(row['metadata'])
            metadata.pop('player_name')
            db.execute('UPDATE replay_variant_shares SET metadata=? WHERE token=?',
                       (json.dumps(metadata), token))
        index = library.index_page()
        self.assertIn('<title>Public game replays · Arcturus plays chess</title>', index)
        self.assertIn('Replay owner <span>vs.</span> Astra', index)
        self.assertNotIn('Replay owner <span>vs.</span> Arcturus', index)
        self.assertEqual(EmbeddedReplay(page).value()['playerName'], 'Astra')
        self.assertEqual(saved_player_name(state), 'Astra')
        pgn = game.pgn(state)
        self.assertIn('[Black "Astra"]', pgn)
        self.assertIn('[Event "Astra Chess Public Beta"]', pgn)
        self.assertIn('[AstraModel "gpt-6-astra"]', pgn)
        self.assertNotIn('[Model ', pgn)

    def test_pre_persona_glm_record_uses_its_recorded_model_display_name(self):
        state = self.finished(self.config('openrouter-glm', 'arcturus'))
        state.pop('player_persona')
        state.pop('player_prompt')
        self.assertEqual(saved_player_name(state), 'GLM 5.3 Flash')
        self.assertIn('[Black "GLM 5.3 Flash"]', game.pgn(state))
        self.assertIn('[Event "GLM 5.3 Flash Chess Public Beta"]', game.pgn(state))

    def test_player_name_html_is_escaped_in_index_and_standalone_archive(self):
        state = self.finished(self.config('openrouter-glm', 'arcturus'))
        malicious = 'Arcturus </script><script>alert("NAME")</script>'
        state['player_persona']['display_name'] = malicious
        state['name'] = '<img src=x onerror=alert(1)>'
        current = self.config('astra', 'astra')
        library = ReplayLibrary(current, Store(current))
        page, _ = self.build_and_share(library, state)
        index = library.index_page()
        self.assertIn(escape(malicious), index)
        self.assertIn(escape(state['name']), index)
        for html in (page, index):
            self.assertNotIn(malicious, html)
            self.assertNotIn(state['name'], html)
            self.assertNotIn('<script>alert("NAME")</script>', html)
        data = EmbeddedReplay(page).value()
        self.assertEqual(data['playerName'], malicious)
        self.assertEqual(data['messages'][0]['name'], malicious)
        self.assert_binding_private(page + index)

    def test_non_astra_pgn_names_both_colors_and_uses_generic_model_headers(self):
        config = self.config('openrouter-glm', 'arcturus')
        for human_side in ('white', 'black'):
            with self.subTest(human_side=human_side):
                state = self.finished(config, human_side=human_side)
                pgn = game.pgn(state)
                side = 'Black' if human_side == 'white' else 'White'
                self.assertIn(f'[{side} "Arcturus"]', pgn)
                self.assertIn('[Event "Arcturus Chess Public Beta"]', pgn)
                self.assertIn('[Site "Arcturus Chess"]', pgn)
                self.assertIn('[Model "z-ai/glm-5.3-flash:nitro"]', pgn)
                self.assertIn('[Reasoning "max"]', pgn)
                self.assertNotIn('[AstraModel ', pgn)
                self.assertNotIn('[AstraReasoning ', pgn)
                self.assert_binding_private(pgn)

    def test_legacy_share_api_exports_saved_name_without_private_binding(self):
        current = self.config('astra', 'astra')
        app = create_app(current)
        with TestClient(app) as client:
            response = client.post('/api/auth/register', json={'name': 'Replay owner'},
                                   headers={'Origin': current.origin})
            self.assertEqual(response.status_code, 200, response.text)
            user = response.json()['user']
            client.headers.update({'Origin': current.origin,
                                   'X-CSRF-Token': response.json()['csrf_token']})
            arcturus = self.finished(self.config('openrouter-glm', 'arcturus'), user=user)
            astra = self.finished(current, user=user)
            for field in ('player_profile', 'player_persona', 'player_prompt'):
                astra.pop(field)
            for state, name in ((arcturus, 'Arcturus'), (astra, 'Astra')):
                with self.subTest(player=name):
                    app.state.store.create(state)
                    response = client.post(f"/api/games/{state['id']}/share",
                                           json={'include_commentary': True})
                    self.assertEqual(response.status_code, 200, response.text)
                    token = response.json()['url'].rsplit('/', 1)[1]
                    public = client.get('/api/replays/' + token)
                    self.assertEqual(public.status_code, 200, public.text)
                    self.assertEqual(public.json()['player_name'], name)
                    self.assertEqual(public.json()['model'], state['model'])
                    self.assertEqual(public.json()['messages'][0]['author'], 'astra')
                    self.assert_binding_private(public.text)
                    self.assertNotIn(state['id'], public.text)
                    self.assertNotIn(user['id'], public.text)


if __name__ == '__main__':
    unittest.main()
