"""Read-only inventories and isolated migration rehearsals, without model calls."""
from contextlib import redirect_stdout
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from astra_web.config import Config
from astra_web.store import Store
from astra_web.replay_library import ReplayLibrary
from tools.ops.report_games import main as report_main, markdown, read_database, report
from tools.ops.rehearse_replay_migration import rehearse


class OperatorToolsTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.source = self.root / 'source'
        self.config = Config(data_dir=self.source, player_mode='disabled')
        self.config.validate()
        self.store = Store(self.config)
        self.library = ReplayLibrary(self.config, self.store)
        self.library.recover()
        self.game_id = 'a' * 32
        self.state = dict(id=self.game_id, user_id='PRIVATE ACCOUNT', name='Fixture player', human_side='white',
                          astra_side='black', status='finished', result='0-1', termination='checkmate',
                          moves=[{'san': 'f3'}, {'san': 'e5'}, {'san': 'g4'}, {'san': 'Qh4#'}],
                          fen='8/8/8/8/8/8/8/8 w - - 0 3', updated_at=2000.0, created_at=1000.0,
                          last_human_activity=1900.0, worker={'state': 'idle', 'message': 'PRIVATE ERROR'},
                          active_started=None, version=0, messages=[{'text': 'PRIVATE CHAT'}], thread_id='PRIVATE CODEX ID')
        self.store.create(self.state)
        with self.store.connection() as db:
            db.execute('CREATE TABLE auth_fixture(secret TEXT)')
            db.execute('INSERT INTO auth_fixture VALUES(?)', ('PRIVATE AUTH SECRET',))
            db.execute('INSERT INTO budget VALUES(?,?,?,?)', ('2026-09-11', 12, 3456, 0))

    def test_report_does_not_expose_private_content_and_exact_qa_names_do_not_guess(self):
        data = report(self.source, qa_names=('Fixture',), now=datetime(2026, 9, 11, tzinfo=timezone.utc))
        self.assertEqual(data['summary']['player_games'], 1)
        row = data['games'][0]
        self.assertEqual(row['last_move'], '2… Qh4#')
        self.assertEqual(row['human_outcome'], 'loss')
        self.assertEqual(data['today_budget']['tokens'], 3456)
        self.assertTrue(data['activity']['idle_snapshot'])
        serialized = json.dumps(data)
        for secret in ('PRIVATE CHAT', 'PRIVATE ACCOUNT', 'PRIVATE AUTH SECRET', 'PRIVATE CODEX ID', 'PRIVATE ERROR'):
            self.assertNotIn(secret, serialized)
        qa = report(self.source, qa_names=('Fixture player',))
        self.assertEqual(qa['summary']['qa_games'], 1)
        self.assertEqual(qa['summary']['player_games'], 0)
        with read_database(self.source) as db:
            with self.assertRaises(sqlite3.OperationalError):
                db.execute('DELETE FROM games')
        self.assertEqual(self.store.get(self.game_id), self.state)

    def test_report_tracks_variants_busy_reservations_and_escapes_markdown(self):
        self.store.mutate(self.game_id, lambda s: s.update(name='<b>Player</b>|next\nline', status='active',
                                                         worker={'state': 'calculating'}, active_started=2001))
        with self.store.connection() as db:
            db.execute("UPDATE budget SET reserved=3000000")
            db.execute("INSERT INTO replay_versions VALUES(?,?,'ready',0,2000,NULL,2000)", (self.game_id, 'b' * 32))
            db.execute("INSERT INTO replay_variant_jobs VALUES(?,1,?,'building',NULL,2001)", (self.game_id, 'c' * 32))
            db.execute('INSERT INTO replay_variant_shares VALUES(?,?,?,0,2000,?,1)',
                       (self.game_id, 'd' * 32, 'b' * 32, '{}'))
        data = report(self.source)
        self.assertEqual(data['activity'], dict(active_responses=1, building_replays=1, reserved_tokens=3000000, idle_snapshot=False))
        self.assertTrue(data['games'][0]['replays']['moves']['listed'])
        self.assertTrue(data['games'][0]['replays']['chat']['building'])
        text = markdown(data)
        self.assertNotIn('<b>', text)
        self.assertIn('&lt;b&gt;Player&lt;/b&gt;&#124;next line', text)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(report_main(['--data-dir', str(self.source), '--json', '--require-idle']), 2)

    def old_replay_fixture(self):
        html = '<!doctype html>\n<title>Fixture replay</title>\n'
        chat_id, moves_id, token = 'b' * 32, 'c' * 32, 'd' * 32
        old_private = self.source / 'replay-archives' / self.game_id / (chat_id + '.html')
        old_private.parent.mkdir(parents=True)
        old_private.write_text(html, encoding='utf-8')
        public = self.source / 'public-replays' / (token + '.html')
        public.write_text(html.replace('Fixture', 'Moves'), encoding='utf-8')
        with self.store.connection() as db:
            db.execute('DELETE FROM replay_library_migrations')
            db.execute("INSERT INTO replay_archives VALUES(?,?,'ready',1,2000,NULL)", (self.game_id, chat_id))
            db.execute('INSERT INTO replay_publications VALUES(?,?,?,0,2000,?)',
                       (self.game_id, token, moves_id, json.dumps({'name': 'Fixture', 'human_side': 'white', 'astra_side': 'black',
                           'result': '0-1', 'created_at': 1000, 'plies': 4})))
        return chat_id, moves_id, token

    def test_private_rehearsal_preserves_source_and_restores_both_variants(self):
        chat_id, moves_id, token = self.old_replay_fixture()
        with read_database(self.source) as db:
            original = {table: [tuple(r) for r in db.execute('SELECT * FROM ' + table)]
                        for table in ('games', 'budget', 'shares', 'auth_fixture', 'replay_archives', 'replay_publications')}
        files = {p.relative_to(self.source): p.read_bytes() for p in self.source.rglob('*.html')}
        target = self.root / 'private-rehearsal'
        result = rehearse(self.source, target)
        self.assertTrue(result['rehearsal_passed'])
        self.assertEqual(result['saved_variants'], 2)
        self.assertTrue((target / 'replay-archives' / self.game_id / 'moves' / (moves_id + '.html')).is_file())
        self.assertTrue((target / 'replay-archives' / self.game_id / 'chat' / (chat_id + '.html')).is_file())
        with read_database(self.source) as db:
            after = {table: [tuple(r) for r in db.execute('SELECT * FROM ' + table)] for table in original}
        self.assertEqual(after, original)
        self.assertEqual({p.relative_to(self.source): p.read_bytes() for p in self.source.rglob('*.html')}, files)
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.assertEqual(json.loads((target / 'result.json').read_text()), result)

    def test_rehearsal_refuses_existing_contained_and_busy_destinations_without_deleting(self):
        existing = self.root / 'existing'
        existing.mkdir()
        sentinel = existing / 'keep.txt'
        sentinel.write_text('retain')
        with self.assertRaisesRegex(ValueError, 'new directory'):
            rehearse(self.source, existing)
        self.assertEqual(sentinel.read_text(), 'retain')
        with self.assertRaisesRegex(ValueError, 'outside'):
            rehearse(self.source, self.source / 'copy')
        self.assertFalse((self.source / 'copy').exists())
        self.store.mutate(self.game_id, lambda s: s.update(worker={'state': 'thinking'}))
        destination = self.root / 'busy-copy'
        with self.assertRaisesRegex(ValueError, 'idle'):
            rehearse(self.source, destination)
        self.assertFalse(destination.exists())

    def test_rehearsal_detects_file_change_and_retains_failed_copy_for_review(self):
        self.old_replay_fixture()
        import tools.ops.rehearse_replay_migration as migration
        original = migration.shutil.copyfile
        def changed(source, target):
            result = original(source, target)
            Path(target).write_text('tampered copy', encoding='utf-8')
            return result
        destination = self.root / 'changed-copy'
        with patch.object(migration.shutil, 'copyfile', side_effect=changed):
            with self.assertRaisesRegex(ValueError, 'changed while copying'):
                rehearse(self.source, destination)
        self.assertTrue(destination.is_dir())
        self.assertFalse((destination / 'result.json').exists())

    def test_rehearsal_checks_replay_metadata_on_second_recovery(self):
        self.old_replay_fixture()
        original = ReplayLibrary.recover
        calls = []
        def non_idempotent(manager):
            original(manager)
            calls.append(True)
            if len(calls) == 2:
                with manager.store.connection() as db:
                    db.execute('UPDATE replay_variant_shares SET listed=0')
        destination = self.root / 'non-idempotent-copy'
        with patch.object(ReplayLibrary, 'recover', new=non_idempotent):
            with self.assertRaisesRegex(ValueError, 'not idempotent'):
                rehearse(self.source, destination)
        self.assertEqual(len(calls), 2)
        self.assertFalse((destination / 'result.json').exists())


if __name__ == '__main__':
    unittest.main()
