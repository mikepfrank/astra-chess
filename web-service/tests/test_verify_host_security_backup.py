"""Tiny fixtures exercise archive checks without host access or private data."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import stat
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('verify_host_security_backup',
    Path(__file__).parents[1] / 'tools/ops/verify_host_security_backup.py')
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


def archive(path, entries):
    with tarfile.open(path, 'w') as tar:
        for name, data, kind in entries:
            item = tarfile.TarInfo(name)
            item.type = kind
            item.size = len(data)
            tar.addfile(item, io.BytesIO(data))


class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.backup = self.root / '20261117T000000Z'
        self.backup.mkdir()
        self.live = self.root / 'live.sqlite3'
        self.live.write_bytes(b'fixture database')
        self.tar = self.backup / 'applications.tar'
        self.selected = {'home/test/primary.sqlite3': self.live}

    def fixture_archive(self, data=b'fixture database', extra=(), kind=tarfile.REGTYPE):
        archive(self.tar, [('home/test/primary.sqlite3', data, kind), *extra])

    def test_reviewed_guard_helper_loads_under_isolated_python(self):
        helper = m.backup_helper()
        self.assertEqual(helper.IMAGE_TAG, 'gpt2-codex-runtime:0.154.0')
        with patch.object(m, 'BACKUP_HELPER_SHA256', '0' * 64):
            with self.assertRaises(RuntimeError):
                m.backup_helper()

    def test_selected_files_match_without_extraction(self):
        self.fixture_archive()
        self.assertEqual(m.compare_selected(self.tar, self.selected), 1)

    def test_changed_missing_duplicate_and_nonregular_files_fail(self):
        for entries in ([], [('home/test/primary.sqlite3', b'changed', tarfile.REGTYPE)],
                        [('home/test/primary.sqlite3', b'fixture database', tarfile.SYMTYPE)],
                        [('home/test/primary.sqlite3', b'fixture database', tarfile.REGTYPE)] * 2):
            with self.subTest(entries=entries):
                archive(self.tar, entries)
                with self.assertRaises(RuntimeError):
                    m.compare_selected(self.tar, self.selected)

    def test_unsafe_member_paths_fail_even_when_not_selected(self):
        for name in ('../escape', '/absolute', 'home/../escape', 'home\\escape'):
            self.fixture_archive(extra=[(name, b'', tarfile.REGTYPE)])
            with self.assertRaises(RuntimeError):
                m.compare_selected(self.tar, self.selected)

    def test_canonical_directory_rejects_escape_and_noncanonical_path(self):
        self.assertEqual(m.canonical_directory(str(self.backup), self.root), self.backup)
        for path in (self.root, self.root / '..' / self.root.name / self.backup.name):
            with self.assertRaises(RuntimeError):
                m.canonical_directory(str(path), self.root)
        with patch.object(Path, 'is_symlink', return_value=True):
            with self.assertRaises(RuntimeError):
                m.canonical_directory(str(self.backup), self.root)

    def test_private_modes_owner_and_type(self):
        for mode, uid, directory, success in (
            (stat.S_IFREG | 0o600, 0, False, True),
            (stat.S_IFDIR | 0o700, 0, True, True),
            (stat.S_IFREG | 0o644, 0, False, False),
            (stat.S_IFREG | 0o600, 1, False, False),
            (stat.S_IFLNK | 0o600, 0, False, False)):
            path = SimpleNamespace(lstat=lambda: SimpleNamespace(st_mode=mode, st_uid=uid))
            if success:
                m.private_path(path, directory)
            else:
                with self.assertRaises(RuntimeError):
                    m.private_path(path, directory)

    def test_manifest_completion_and_artifact_sizes(self):
        records = {}
        for name in m.ARTIFACTS:
            (self.backup / name).write_bytes(b'fixture')
            records[name] = {'bytes': 7, 'sha256': hashlib.sha256(b'fixture').hexdigest()}
        manifest = {'complete': True, 'files': records}
        path = self.backup / 'manifest.json'
        path.write_text(json.dumps(manifest))
        # Windows does not expose POSIX ownership/modes; these are tested above.
        with patch.object(m, 'private_path'):
            self.assertTrue(m.check_manifest(self.backup)['complete'])
            manifest['complete'] = False
            path.write_text(json.dumps(manifest))
            with self.assertRaises(RuntimeError):
                m.check_manifest(self.backup)
            manifest['complete'] = True
            manifest['files']['applications.tar']['bytes'] += 1
            path.write_text(json.dumps(manifest))
            with self.assertRaises(RuntimeError):
                m.check_manifest(self.backup)

    def test_docker_tag_and_config_digest(self):
        config = b'{"fixture":true}'
        image_id = 'sha256:' + hashlib.sha256(config).hexdigest()
        expected = {'tag': 'fixture:old', 'id': image_id}
        listing = [{'RepoTags': ['fixture:old'], 'Config': 'config.json', 'Layers': []}]
        archive(self.tar, [('manifest.json', json.dumps(listing).encode(), tarfile.REGTYPE),
                           ('config.json', config, tarfile.REGTYPE)])
        m.verify_image(self.tar, expected)
        for wrong in ({'tag': 'fixture:other', 'id': image_id},
                      {'tag': 'fixture:old', 'id': 'sha256:' + '0' * 64}):
            with self.assertRaises(RuntimeError):
                m.verify_image(self.tar, wrong)


if __name__ == '__main__':
    unittest.main()
