"""Maintenance isolation and accounting; no service control or model calls."""
import contextlib
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from astra_web import chess_game
from astra_web.config import Config
from astra_web.store import Store
from tools.ops import compact_player_context as ops


class ContextMaintenanceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.config = Config(data_dir=Path(self.folder.name), model_profile='openrouter-glm', persona='arcturus')
        self.store = Store(self.config)
        self.state = chess_game.new_game({'id': 'fixture-user', 'name': 'Fixture'}, 'black', self.config)
        self.state.update(thread_id='existing-thread', worker={'state': 'error', 'message': 'Saved failure'})
        self.store.create(self.state)
        (self.config.data_dir / 'players' / self.state['id']).mkdir(parents=True)

    async def exercise(self, fail=False, tool_call=False):
        class Player:
            def __init__(self, config):
                pass
            async def compact(self, game_id, snapshot, tool, thread_id, player_binding):
                await tool('_thread', {'thread_id': thread_id})
                await tool('_compaction', {'phase': 'started', 'item_id': 'compact-fixture'})
                await tool('_usage', {'tokens': 450})
                if fail:
                    raise RuntimeError('fixture provider error')
                if tool_call:
                    await tool('chess_choose', {'action': 'move', 'uci': 'e2e4'})
                await tool('_compaction', {'phase': 'completed', 'item_id': 'compact-fixture'})
                return {'thread_id': thread_id, 'usage_tokens': 450, 'model': 'fixture', 'reasoning': 'max'}
            async def close(self):
                pass
        with patch.object(ops, 'require_stopped'), patch.object(ops, 'CodexPlayer', Player), contextlib.redirect_stdout(io.StringIO()):
            return await ops.compact(self.config, self.state['id'], 0, 'fixture.service')

    async def test_preserves_every_game_field_and_settles_model_usage(self):
        before = self.store.get(self.state['id'])
        report = await self.exercise()
        self.assertTrue(report['success'])
        self.assertTrue(report['same_thread'])
        self.assertEqual(before, self.store.get(self.state['id']))
        with self.store.connection() as db:
            row = db.execute('SELECT tokens,reserved FROM budget').fetchone()
            self.assertEqual(tuple(row), (450, 0))
            self.assertEqual(db.execute("SELECT count(*) FROM events WHERE kind='operator_context_compaction'").fetchone()[0], 1)

    async def test_failure_and_forbidden_move_preserve_game_and_charge_observed_usage(self):
        before = self.store.get(self.state['id'])
        for options in ({'fail': True}, {'tool_call': True}):
            with self.assertRaises(RuntimeError):
                await self.exercise(**options)
            self.assertEqual(before, self.store.get(self.state['id']))
        with self.store.connection() as db:
            self.assertEqual(tuple(db.execute('SELECT tokens,reserved FROM budget').fetchone()), (900, 0))

    async def test_changed_version_or_busy_other_game_refuses_before_spending(self):
        with patch.object(ops, 'require_stopped'), patch.object(ops, 'CodexPlayer') as player:
            with self.assertRaises(ValueError):
                await ops.compact(self.config, self.state['id'], 1, 'fixture.service')
            other = chess_game.new_game({'id': 'other', 'name': 'Other'}, 'white', self.config)
            other['worker']['state'] = 'thinking'
            self.store.create(other)
            with self.assertRaises(ValueError):
                await ops.compact(self.config, self.state['id'], 0, 'fixture.service')
            player.assert_not_called()
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM budget').fetchone()[0], 0)

    def test_active_or_missing_systemd_unit_is_not_an_idle_service(self):
        for output in ('LoadState=loaded\nActiveState=active\nMainPID=123\n',
                       'LoadState=not-found\nActiveState=inactive\nMainPID=0\n'):
            with patch.object(ops.subprocess, 'run', return_value=SimpleNamespace(stdout=output)):
                with self.assertRaises(ValueError):
                    ops.require_stopped('fixture.service')


if __name__ == '__main__':
    unittest.main()
