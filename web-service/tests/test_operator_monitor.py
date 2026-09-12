"""Operator identity boundaries and read-only inventory; no mail/model/search."""
from contextlib import closing
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from astra_web.app import create_app
from astra_web.config import Config
from astra_web.identity import COOKIE_NAME
from astra_web.operator_monitor import GAME_FIELDS


class OperatorMonitorTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.config = Config(data_dir=Path(self.folder.name), origin='http://testserver',
                             player_mode='disabled', secure_cookies=False, smtp_host='', smtp_from='',
                             operator_user_id='', monitor_excluded_game_ids=())
        self.app = create_app(self.config)
        # The HTTP surface needs no supervisor lifespan or game recovery work.
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.identity = self.app.state.identity
        self.store = self.app.state.store

    def login(self, name='Operator', protected=True):
        token = self.identity.register(name, 'an isolated test password' if protected else None, None)
        self.client.cookies.set(COOKIE_NAME, token)
        return token, self.identity.user_for_token(token)

    def authorize(self):
        token, user = self.login()
        self.config.operator_user_id = user['id']
        return token, user

    def add_game(self, game_id='a' * 32, name='Player', finished=False, busy=False):
        state = dict(id=game_id, user_id='PRIVATE ACCOUNT ' + game_id, name=name,
                     human_side='white', astra_side='black',
                     status='finished' if finished else 'active',
                     result='0-1' if finished else '*', termination='checkmate' if finished else '',
                     moves=[{'san': 'f3'}, {'san': 'e5'}, {'san': 'g4'}, {'san': 'Qh4#'}],
                     fen='8/8/8/8/8/8/8/8 w - - 0 3', updated_at=2000.0, created_at=1000.0,
                     last_human_activity=1900.0,
                     worker={'state': 'thinking' if busy else 'idle', 'message': 'PRIVATE ERROR'},
                     active_started=2001 if busy else None, version=0,
                     messages=[{'text': 'PRIVATE CHAT'}], thread_id='PRIVATE CODEX ID',
                     queries=[{'path': 'PRIVATE PATH', 'credential': 'PRIVATE SECRET'}],
                     decisions=[{'text': 'PRIVATE DECISION'}], clock_used=12.5)
        self.store.create(state)
        return state

    def dump(self):
        with closing(sqlite3.connect(self.config.db_path)) as db:
            return '\n'.join(db.iterdump())

    def assert_denied(self, status):
        with patch('astra_web.operator_monitor.report', side_effect=AssertionError('Must not read inventory')):
            response = self.client.get('/api/operator/games')
        self.assertEqual(response.status_code, status, response.text)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertNotIn('games', response.json())

    def test_anonymous_disabled_and_display_name_never_grant_inventory_access(self):
        self.assertFalse(self.client.get('/api/auth/me').json()['operator'])
        self.assert_denied(401)
        token, user = self.login('Dr. Thanos')
        self.assert_denied(403)  # Disabled even with the requested name and a password.
        self.config.operator_user_id = 'f' * 32
        self.assertFalse(self.client.get('/api/auth/me').json()['operator'])
        self.assert_denied(403)
        self.assertNotIn('operator', self.identity.user_for_token(token))

    def test_only_configured_protected_account_is_allowed_and_flag_is_separate(self):
        token, user = self.authorize()
        state = self.client.get('/api/auth/me').json()
        self.assertTrue(state['operator'])
        self.assertEqual(set(state['user']), {'id', 'name', 'protected', 'memory_enabled'})
        self.assertEqual(self.client.get('/api/operator/games').status_code, 200)
        with self.store.connection() as db:
            db.execute('UPDATE auth_users SET name=?,name_key=? WHERE id=?',
                       ('Renamed operator', 'renamed operator', user['id']))
        self.assertTrue(self.client.get('/api/auth/me').json()['operator'])
        self.assertEqual(self.client.get('/api/operator/games').status_code, 200)
        # Revoking password protection also revokes operator eligibility on the next read.
        with self.store.connection() as db:
            db.execute('UPDATE auth_users SET password_hash=NULL WHERE id=?', (user['id'],))
        self.assertFalse(self.client.get('/api/auth/me').json()['operator'])
        self.assert_denied(403)

    def test_matching_guest_and_revoked_session_cannot_read(self):
        token, user = self.login('Guest', protected=False)
        self.config.operator_user_id = user['id']
        self.assert_denied(403)
        self.identity.logout(token)
        self.assert_denied(401)
        self.client.cookies.clear()
        token, user = self.authorize()
        self.identity.logout(token)
        self.assertFalse(self.client.get('/api/auth/me').json()['operator'])
        self.assert_denied(401)
        token = self.identity.login('Operator', 'an isolated test password', None)
        self.client.cookies.set(COOKIE_NAME, token)
        with self.store.connection() as db:
            db.execute('UPDATE auth_sessions SET expires_at=0')
        self.assertFalse(self.client.get('/api/auth/me').json()['operator'])
        self.assert_denied(401)

    def test_inventory_filters_exact_game_ids_and_preserves_service_wide_activity(self):
        self.authorize()
        kept = self.add_game(finished=True)
        excluded = self.add_game('b' * 32, name='Known QA', busy=True)
        same_name = self.add_game('c' * 32, name='Known QA')
        self.config.monitor_excluded_game_ids = (excluded['id'], 'd' * 32)
        day = datetime.now(timezone.utc).date().isoformat()
        with self.store.connection() as db:
            db.execute('INSERT INTO budget VALUES(?,?,?,?)', (day, 3, 15000, 5000))
            db.execute("INSERT INTO replay_versions VALUES(?,?,'ready',1,2000,NULL,2000)",
                       (kept['id'], 'e' * 32))
            db.execute('INSERT INTO replay_variant_shares VALUES(?,?,?,1,2000,?,1)',
                       (kept['id'], 'f' * 32, 'e' * 32, '{}'))
        response = self.client.get('/api/operator/games')
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data['summary'], dict(total_games=2, player_games=2, qa_games=0,
                         finished_player_games=1, unfinished_player_games=1, excluded_games=1))
        self.assertEqual({row['game_id'] for row in data['games']}, {kept['id'], same_name['id']})
        self.assertEqual(data['activity'], dict(active_responses=1, building_replays=0,
                                              reserved_tokens=5000, idle_snapshot=False))
        self.assertEqual(data['today_budget'], dict(day=day, turns=3, tokens=15000, reserved=5000))
        self.assertEqual(data['max_daily_tokens'], self.config.max_daily_tokens)
        self.assertEqual(data['timezone'], 'UTC')
        self.assertEqual(datetime.fromisoformat(data['as_of']).utcoffset().total_seconds(), 0)
        row = next(row for row in data['games'] if row['game_id'] == kept['id'])
        self.assertEqual(set(row), set(GAME_FIELDS) | {'replays'})
        self.assertEqual(row['last_move'], '2… Qh4#')
        self.assertEqual(row['human_outcome'], 'loss')
        self.assertEqual(row['replays']['chat'], dict(saved=True, building=False, shared=True, listed=True))

    def test_get_is_read_only_and_never_serializes_sensitive_state_or_future_report_fields(self):
        token, user = self.authorize()
        game = self.add_game(busy=True)
        with self.store.connection() as db:
            db.execute('UPDATE auth_users SET email=? WHERE id=?', ('private@example.org', user['id']))
        before = self.dump()
        with patch.object(self.app.state.supervisor, 'schedule', side_effect=AssertionError('No work')):
            one = self.client.get('/api/operator/games')
            two = self.client.get('/api/operator/games')
        self.assertEqual(one.status_code, 200, one.text)
        self.assertEqual(one.json()['games'], two.json()['games'])
        self.assertEqual(one.headers['cache-control'], 'no-store')
        self.assertEqual(before, self.dump())
        self.assertEqual(self.store.get(game['id']), game)
        for sentinel in ('PRIVATE', 'private@example.org', token, user['id'], str(self.config.data_dir)):
            self.assertNotIn(sentinel, one.text)
        from tools.ops.report_games import report
        future = report(self.config.data_dir)
        future['secret'] = 'PRIVATE FUTURE'
        future['games'][0]['messages'] = 'PRIVATE FUTURE CHAT'
        future['games'][0]['replays']['chat']['token'] = 'PRIVATE SHARE TOKEN'
        with patch('astra_web.operator_monitor.report', return_value=future):
            self.assertNotIn('PRIVATE', self.client.get('/api/operator/games').text)

    def test_inventory_errors_do_not_expose_paths_or_private_data(self):
        self.authorize()
        with patch('astra_web.operator_monitor.report', side_effect=ValueError('PRIVATE DATABASE PATH')):
            response = self.client.get('/api/operator/games')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('PRIVATE', response.text)
        self.assertEqual(response.headers['cache-control'], 'no-store')

    def test_operator_config_validation_and_environment_defaults(self):
        for invalid in ('Dr. Thanos', 'a' * 31, 'A' * 32, 'a' * 32 + ',other'):
            self.config.operator_user_id = invalid
            with self.assertRaisesRegex(ValueError, 'ASTRA_OPERATOR_USER_ID'):
                self.config.validate()
        self.config.operator_user_id = ''
        for invalid in (('bad',), ('a' * 32, ''), 'a' * 32, ['a' * 32]):
            self.config.monitor_excluded_game_ids = invalid
            with self.assertRaisesRegex(ValueError, 'ASTRA_MONITOR_EXCLUDED_GAME_IDS'):
                self.config.validate()
        with patch.dict(os.environ, {'ASTRA_OPERATOR_USER_ID': 'a' * 32,
                                     'ASTRA_MONITOR_EXCLUDED_GAME_IDS': 'b' * 32 + ', ' + 'c' * 32}):
            config = Config(data_dir=Path(self.folder.name))
            config.validate()
            self.assertEqual(config.operator_user_id, 'a' * 32)
            self.assertEqual(config.monitor_excluded_game_ids, ('b' * 32, 'c' * 32))


if __name__ == '__main__':
    unittest.main()
