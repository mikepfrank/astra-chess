"""The offline CLI must reject artifact/source aliases before any export write."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import export_replay as exporter


class ExportDestinationTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.source = self.root / 'source.json'
        self.source.write_text('original source', encoding='utf-8')
        self.record = {'game': {'id': 'a' * 32}, 'moves': [], 'messages': [], 'evaluations': []}

    def invoke(self, arguments, *, rejected=False):
        def build(record, path):
            Path(path).write_text('standalone HTML', encoding='utf-8')
        output, errors = io.StringIO(), io.StringIO()
        with (patch.object(exporter, 'load_record', return_value=self.record),
              patch.object(exporter, 'read_game', return_value={}),
              patch.object(exporter, 'make_record', return_value=self.record),
              patch.object(exporter, 'record_pgn', return_value='validated PGN'),
              patch.object(exporter, 'build_archive', side_effect=build) as builder,
              redirect_stdout(output), redirect_stderr(errors)):
            if rejected:
                before = {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()}
                with self.assertRaises(SystemExit) as raised:
                    exporter.main([str(argument) for argument in arguments])
                self.assertEqual(raised.exception.code, 1)
                self.assertIn('conflicts with', errors.getvalue())
                builder.assert_not_called()
                self.assertEqual({p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()}, before)
            else:
                exporter.main([str(argument) for argument in arguments])
            return builder.call_count

    def test_default_json_record_cannot_overwrite_html_with_json_extension(self):
        target = self.root / 'replay.json'
        target.write_text('previous artifact', encoding='utf-8')
        self.invoke(['--game', 'a' * 32, '--data-dir', self.root, '--output', target], rejected=True)

    def test_all_active_artifact_pairs_must_be_distinct(self):
        for first, second in (('--output', '--record'), ('--output', '--pgn'), ('--record', '--pgn')):
            with self.subTest(pair=(first, second)):
                target = self.root / 'same-file'
                arguments = ['--from-record', self.source, '--output', self.root / 'replay.html',
                             first, target, second, target]
                self.invoke(arguments, rejected=True)

    def test_each_output_must_preserve_the_source_archive(self):
        for flag in ('--output', '--record', '--pgn'):
            with self.subTest(output=flag):
                self.invoke(['--from-record', self.source, '--output', self.root / 'replay.html',
                             flag, self.source], rejected=True)
        self.invoke(['--from-record', self.source, '--record-only', '--record', self.source], rejected=True)

    def test_resolved_parent_segments_cannot_alias_source(self):
        folder = self.root / 'subfolder'
        folder.mkdir()
        self.invoke(['--from-record', self.source, '--output', folder / '..' / self.source.name], rejected=True)

    def test_existing_hard_link_cannot_alias_source(self):
        target = self.root / 'hardlink.html'
        try:
            target.hardlink_to(self.source)
        except OSError:
            self.skipTest('Hard-link creation is unavailable on this filesystem.')
        self.invoke(['--from-record', self.source, '--output', target], rejected=True)

    def test_existing_symlink_cannot_alias_source(self):
        target = self.root / 'symlink.html'
        try:
            target.symlink_to(self.source)
        except OSError:
            self.skipTest('Symlink creation is unavailable for this Windows account.')
        self.invoke(['--from-record', self.source, '--output', target], rejected=True)

    def test_record_only_ignores_unused_html_path(self):
        target = self.root / 'copy.json'
        calls = self.invoke(['--from-record', self.source, '--output', self.source,
                             '--record-only', '--record', target])
        self.assertEqual(calls, 0)
        self.assertEqual(json.loads(target.read_text(encoding='utf-8')), self.record)
        self.assertEqual(self.source.read_text(encoding='utf-8'), 'original source')
        target = self.root / 'default-record.json'
        calls = self.invoke(['--game', 'a' * 32, '--data-dir', self.root,
                             '--record-only', '--output', target])
        self.assertEqual(calls, 0)
        self.assertEqual(json.loads(target.read_text(encoding='utf-8')), self.record)

    def test_source_database_and_sqlite_sidecars_are_protected_only_for_database_exports(self):
        for suffix in ('', '-wal', '-shm'):
            with self.subTest(suffix=suffix):
                self.invoke(['--game', 'a' * 32, '--data-dir', self.root,
                             '--output', self.root / ('astra.sqlite3' + suffix)], rejected=True)
        target = self.root / 'astra.sqlite3'
        self.assertEqual(self.invoke(['--from-record', self.source, '--data-dir', self.root,
                                     '--output', target]), 1)
        self.assertEqual(target.read_text(encoding='utf-8'), 'standalone HTML')

    def test_distinct_artifacts_all_write_successfully(self):
        html, record, pgn = (self.root / name for name in ('replay.html', 'record.json', 'game.pgn'))
        self.assertEqual(self.invoke(['--from-record', self.source, '--output', html,
                                     '--record', record, '--pgn', pgn]), 1)
        self.assertEqual(html.read_text(encoding='utf-8'), 'standalone HTML')
        self.assertEqual(json.loads(record.read_text(encoding='utf-8')), self.record)
        self.assertEqual(pgn.read_text(encoding='utf-8'), 'validated PGN')
        self.assertEqual(self.source.read_text(encoding='utf-8'), 'original source')


    def test_omit_commentary_excludes_chat_from_generated_artifacts(self):
        self.record['messages'] = [{'text': 'Private chat fixture that must not be exported'}]
        target = self.root / 'moves-only.json'
        self.invoke(['--from-record', self.source, '--record-only', '--record', target,
                     '--omit-commentary'])
        saved = json.loads(target.read_text(encoding='utf-8'))
        self.assertEqual(saved['messages'], [])
        self.assertNotIn('Private chat fixture', target.read_text(encoding='utf-8'))
        self.assertEqual(self.source.read_text(), 'original source')


if __name__ == '__main__':
    unittest.main()
