"""Offline identity repair preserves captured snapshots and sharing authority."""
from contextlib import closing, redirect_stdout
from copy import deepcopy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from astra_web import chess_game as game, replay_archive
from astra_web.config import Config
from astra_web.replay_library import ReplayLibrary, standalone_csp
from astra_web.store import Store

SOURCE = Path(__file__).resolve().parents[1] / 'tools/ops/repair_arcturus_replay_branding.py'
SPEC = importlib.util.spec_from_file_location('branding_repair', SOURCE)
repair = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(repair)


class ReplayBrandingRepairTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.root = self.folder / 'data'
        self.config = Config(data_dir=self.root, model_profile='openrouter-glm', persona='arcturus')
        self.config.validate()
        self.store = Store(self.config)
        ReplayLibrary(self.config, self.store)
        state = game.new_game({'id': 'fixture-owner', 'name': 'Astra admirer <&>'}, 'white', self.config)
        for index, uci in enumerate(('f2f3', 'e7e5', 'g2g4', 'd8h4')):
            game.apply_move(state, uci, 'human' if index % 2 == 0 else 'astra')
            state['moves'][index]['at'] = 1001.0 + index
        state.update(created_at=1000.0, updated_at=1006.0, last_human_activity=1006.0)
        state['messages'] = [
            {'id': 'one', 'author': 'human', 'ply': 0, 'text': 'Astra is the old name. <script>not code</script>', 'created_at': 1000.5},
            {'id': 'two', 'author': 'astra', 'ply': 4, 'text': 'Astra wrote the engine.', 'created_at': 1004.5},
            {'id': 'three', 'author': 'human', 'ply': 4, 'text': 'Private newer captured discussion', 'created_at': 1005.0},
        ]
        self.state, self.game_id = state, state['id']
        self.private_id, self.shared_id, self.moves_id = '1' * 32, '2' * 32, '3' * 32
        self.chat_token, self.moves_token = '4' * 32, '5' * 32
        self.paths = {}
        for kind, archive_id, messages, relative in (
                ('private_chat', self.private_id, state['messages'], Path('replay-archives') / self.game_id / 'chat' / (self.private_id + '.html')),
                ('shared_chat', self.shared_id, state['messages'][:2], Path('public-replays') / (self.chat_token + '.html')),
                ('private_moves', self.moves_id, [], Path('replay-archives') / self.game_id / 'moves' / (self.moves_id + '.html')),
                ('shared_moves', self.moves_id, [], Path('public-replays') / (self.moves_token + '.html'))):
            self.paths[kind] = self.root / relative
            self.legacy_page(self.paths[kind], archive_id, messages)
        # The current game contains discussion absent from BOTH captured chat
        # snapshots. Repair must never re-export this current conversation.
        state['messages'].append({'id': 'four', 'author': 'human', 'ply': 4,
                                  'text': 'NOT IN ANY SAVED REPLAY', 'created_at': 1005.5})
        self.store.create(state)
        metadata = {'name': state['name'], 'human_side': 'white', 'astra_side': 'black',
                    'result': state['result'], 'termination': state['termination'], 'created_at': 1000.0, 'plies': 4}
        with self.store.connection() as db:
            for archive_id, include in ((self.private_id, 1), (self.moves_id, 0)):
                db.execute('INSERT INTO replay_versions VALUES(?,?,?,?,?,?,?)',
                           (self.game_id, archive_id, 'ready', include, 2000.0, None, 1500.0))
            for archive_id, token, include, listed in ((self.shared_id, self.chat_token, 1, 1),
                                                       (self.moves_id, self.moves_token, 0, 0)):
                db.execute('INSERT INTO replay_variant_shares VALUES(?,?,?,?,?,?,?)',
                           (self.game_id, token, archive_id, include, 2100.0, json.dumps(metadata), listed))
            db.execute('INSERT INTO shares VALUES(?,?,?,?)', ('legacy-token', self.game_id, 1200.0, '{"name":"Astra unchanged"}'))
        for relative, contents in ((Path('games') / self.game_id / 'queries/result.json', b'{"saved_score":34}'),
                                   (Path('players') / self.game_id / 'bridge-state.json', b'{"private":"Astra session"}'),
                                   (Path('openrouter-budget.json'), b'{"unchanged_spending_baseline":50}')):
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(contents)

    def legacy_page(self, output, archive_id, messages):
        snapshot = deepcopy(self.state)
        snapshot['messages'] = deepcopy(messages)
        record = replay_archive.make_record(snapshot, self.root, exported_at=2000.0)
        record['schema_version'] = 1
        record['game'].pop('player_name', None)
        record['game']['id'] = archive_id
        for message in record['messages']:
            if message['author'] == 'astra':
                message['name'] = 'Astra'
        record['evaluations'][0]['evaluation'] = {
            'score_pawns': .34, 'mate_in_moves': None, 'mate_for': None, 'ply': 1,
            'uci': 'e7e5', 'san': 'e5', 'completed_depth': 5}
        with redirect_stdout(io.StringIO()):
            replay_archive.build_archive(record, output)
        # Reproduce the old installed HTML's absent identity fields and eyebrow.
        page, start, end, data = repair.page_data(output.read_bytes())
        data.pop('playerName', None)
        data['archive'].pop('playerName', None)
        page = page[:start] + repair.canonical(data).replace('<', '\\u003c') + page[end:]
        page = page.replace('<p class="eyebrow">CHESS · HOSTED GAME REPLAY</p>',
                            '<p class="eyebrow">ASTRA CHESS · HOSTED GAME REPLAY</p>')
        output.write_bytes(page.encode())

    def rows(self):
        with closing(repair.connect(self.root)) as db:
            return repair.database_rows(db)

    def test_dry_run_preserves_source_and_identifies_all_independent_snapshots(self):
        before_rows = self.rows()
        before_files = {kind: path.read_bytes() for kind, path in self.paths.items()}
        protected = repair.protected_files(self.root)
        plan = repair.make_plan(self.root, self.game_id)
        self.assertEqual(len(plan['files']), 4)
        self.assertEqual(len(plan['metadata']), 2)
        self.assertEqual(plan['legacy_shares_skipped'], 1)
        self.assertEqual(self.rows(), before_rows)
        self.assertEqual({kind: path.read_bytes() for kind, path in self.paths.items()}, before_files)
        self.assertEqual(repair.protected_files(self.root), protected)

    def test_apply_preserves_snapshots_ids_flags_evidence_and_current_game(self):
        rows = self.rows()
        originals = {kind: path.read_bytes() for kind, path in self.paths.items()}
        protected = repair.protected_files(self.root)
        plan = repair.make_plan(self.root, self.game_id)
        backup = self.folder / 'private-backup'
        result = repair.apply_plan(self.root, self.game_id, plan['plan_sha256'], backup)
        self.assertTrue(result['captured_snapshots_preserved'])
        for kind, path in self.paths.items():
            old, new = repair.page_data(originals[kind])[3], repair.page_data(path.read_bytes())[3]
            self.assertEqual(old['frames'], new['frames'])
            self.assertEqual(old['archive']['gameId'], new['archive']['gameId'])
            self.assertEqual(old['pgn'].partition('\n\n')[2], new['pgn'].partition('\n\n')[2])
            self.assertEqual(repair.immutable_snapshot(old), repair.immutable_snapshot(new))
            self.assertEqual(new['playerName'], 'Arcturus')
            self.assertNotIn('NOT IN ANY SAVED REPLAY', path.read_text(encoding='utf-8'))
            self.assertIn('script-src', standalone_csp(path.read_text(encoding='utf-8')))
            self.assertEqual((backup / 'files' / path.relative_to(self.root)).read_bytes(), originals[kind])
        shared = repair.page_data(self.paths['shared_chat'].read_bytes())[3]
        private = repair.page_data(self.paths['private_chat'].read_bytes())[3]
        self.assertEqual((len(shared['messages']), len(private['messages'])), (2, 3))
        self.assertEqual(shared['messages'][1]['text'], 'Astra wrote the engine.')
        self.assertEqual(shared['displayNames']['white'], 'Astra admirer <&>')
        after_rows = self.rows()
        for old, new in zip(rows['replay_variant_shares'], after_rows['replay_variant_shares']):
            self.assertEqual({key: value for key, value in old.items() if key != 'metadata'},
                             {key: value for key, value in new.items() if key != 'metadata'})
            self.assertEqual(json.loads(new['metadata']), {**json.loads(old['metadata']), 'player_name': 'Arcturus'})
        rows.pop('replay_variant_shares')
        after_rows.pop('replay_variant_shares')
        self.assertEqual(rows, after_rows)
        self.assertEqual(protected, repair.protected_files(self.root))
        again = repair.make_plan(self.root, self.game_id)
        self.assertEqual((again['files'], again['metadata']), ([], []))

    def test_stale_plan_after_budget_change_refuses_before_backup_or_repair(self):
        plan = repair.make_plan(self.root, self.game_id)
        original = self.paths['shared_chat'].read_bytes()
        (self.root / 'openrouter-budget.json').write_text('{"new_usage":1}')
        backup = self.folder / 'stale-backup'
        with self.assertRaisesRegex(ValueError, 'differs from the reviewed'):
            repair.apply_plan(self.root, self.game_id, plan['plan_sha256'], backup)
        self.assertFalse(backup.exists())
        self.assertEqual(self.paths['shared_chat'].read_bytes(), original)

    def test_failed_second_file_rolls_back_first_and_metadata(self):
        plan = repair.make_plan(self.root, self.game_id)
        rows = self.rows()
        files = {kind: path.read_bytes() for kind, path in self.paths.items()}
        rewrite = repair.rewrite_file
        calls = []
        def fail_second(path, raw):
            calls.append(path)
            if len(calls) == 2:
                raise OSError('fixture write failure')
            rewrite(path, raw)
        with patch.object(repair, 'rewrite_file', side_effect=fail_second), self.assertRaises(OSError):
            repair.apply_plan(self.root, self.game_id, plan['plan_sha256'], self.folder / 'rollback-backup')
        self.assertEqual(rows, self.rows())
        self.assertEqual(files, {kind: path.read_bytes() for kind, path in self.paths.items()})

    def test_identity_mismatch_and_wrong_chat_flag_refuse(self):
        raw = self.paths['shared_chat'].read_bytes()
        with self.assertRaisesRegex(ValueError, 'chat choice'):
            repair.repair_page(raw, archive_id=self.shared_id, include_commentary=False, side='black')
        with self.store.connection() as db:
            state = deepcopy(self.state)
            state['model'] = 'gpt-6-astra'
            db.execute('UPDATE games SET state=? WHERE id=?', (json.dumps(state), self.game_id))
        with self.assertRaisesRegex(ValueError, 'only finished games with saved Arcturus'):
            repair.make_plan(self.root, self.game_id)


if __name__ == '__main__':
    unittest.main()
