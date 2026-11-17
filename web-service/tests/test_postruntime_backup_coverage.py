"""Post-runtime backup regression: retaining a venv alias must retain its target."""
import importlib.util
import io
from pathlib import Path, PurePosixPath
import stat
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


def load(name):
    path = Path(__file__).parents[1] / 'tools/ops' / (name + '.py')
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


b = load('backup_host_security_20261117')
v = load('verify_host_security_backup_20261117')
PARENT = PurePosixPath('/home/gpt-2/.venvs')
LIVE = PARENT / 'gpt2-public'
CANDIDATE = PARENT / 'gpt2-public-security-20261116'
ROLLBACK = PARENT / 'gpt2-public-pre-security-20261117'
FILES = (CANDIDATE / 'pyvenv.cfg',
         CANDIDATE / 'lib/python3.12/site-packages/certifi/cacert.pem',
         ROLLBACK / 'pyvenv.cfg')


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.archive = self.root / 'applications.tar'

    def write_archive(self, *, include=FILES, link=str(CANDIDATE), duplicate=False):
        with tarfile.open(self.archive, 'w') as handle:
            member = tarfile.TarInfo(LIVE.as_posix().lstrip('/'))
            member.type = tarfile.SYMTYPE
            member.linkname = link
            handle.addfile(member)
            for path in (*include, *([include[0]] if duplicate and include else [])):
                data = ('fixture for ' + path.name).encode()
                member = tarfile.TarInfo(path.as_posix().lstrip('/'))
                member.size = len(data)
                handle.addfile(member, io.BytesIO(data))

    def verify(self):
        with patch.object(b, 'GPT2_LIVE', LIVE), patch.object(b, 'GPT2_CANDIDATE', CANDIDATE), \
             patch.object(b, 'GPT2_SELECTED', FILES):
            return b.check_gpt2_archive(self.archive)

    def test_parent_is_archived_instead_of_only_live_alias(self):
        self.assertIn('home/gpt-2/.venvs', b.ROOTS)
        self.assertNotIn('home/gpt-2/.venvs/gpt2-public', b.ROOTS)

    def test_symlink_only_archive_regression_is_refused(self):
        # This models the old producer after its once-ordinary ROOT became a link.
        self.write_archive(include=())
        with self.assertRaisesRegex(RuntimeError, 'omits'):
            self.verify()

    def test_link_and_target_and_rollback_coverage_are_required(self):
        self.write_archive()
        self.assertEqual(self.verify(), 3)
        for missing in FILES:
            self.write_archive(include=tuple(path for path in FILES if path != missing))
            with self.subTest(missing=missing), self.assertRaisesRegex(RuntimeError, 'omits'):
                self.verify()

    def test_changed_link_and_duplicate_target_are_refused(self):
        self.write_archive(link='/unrelated/venv')
        with self.assertRaisesRegex(RuntimeError, 'symlink'):
            self.verify()
        self.write_archive(duplicate=True)
        with self.assertRaisesRegex(RuntimeError, 'Duplicate'):
            self.verify()

    def test_verifier_checks_active_config_and_ca_bundle_bytes(self):
        self.write_archive()
        selected = {}
        for index, path in enumerate(FILES):
            live = self.root / str(index)
            live.write_bytes(('fixture for ' + path.name).encode())
            selected[path.as_posix().lstrip('/')] = live
            self.assertIn(str(path), v.SELECTED)
        self.assertEqual(v.compare_selected(self.archive, selected), 3)
        selected[FILES[1].as_posix().lstrip('/')].write_bytes(b'changed CA bundle')
        with self.assertRaises(RuntimeError):
            v.compare_selected(self.archive, selected)

    def test_launcher_guard_requires_root_owned_expected_executable(self):
        good = b'fixture launcher'
        import hashlib
        digest = hashlib.sha256(good).hexdigest()
        for mode, uid, content, success in (
                (stat.S_IFREG | 0o755, 0, good, True),
                (stat.S_IFREG | 0o755, 0, b'old launcher', False),
                (stat.S_IFREG | 0o777, 0, good, False),
                (stat.S_IFREG | 0o755, 1000, good, False),
                (stat.S_IFLNK | 0o755, 0, good, False)):
            path = SimpleNamespace(lstat=lambda: SimpleNamespace(st_mode=mode, st_uid=uid),
                                   read_bytes=lambda: content)
            with patch.object(b, 'LAUNCHER', path), patch.object(b, 'LAUNCHER_SHA256', digest):
                if success:
                    b.check_launcher()
                else:
                    with self.assertRaises(RuntimeError):
                        b.check_launcher()

    def test_layout_guard_rejects_redirected_live_or_target_files(self):
        class FakePath:
            def __init__(self, name, mode):
                self.name, self.mode, self.resolved = name, mode, self
            def __str__(self):
                return self.name
            def as_posix(self):
                return self.name
            def lstat(self):
                return SimpleNamespace(st_mode=self.mode)
            def resolve(self, strict=True):
                return self.resolved
            def is_symlink(self):
                return stat.S_ISLNK(self.mode)

        parent = FakePath(str(PARENT), stat.S_IFDIR)
        candidate = FakePath(str(CANDIDATE), stat.S_IFDIR)
        rollback = FakePath(str(ROLLBACK), stat.S_IFDIR)
        live = FakePath(str(LIVE), stat.S_IFLNK)
        live.resolved = candidate
        files = [FakePath(str(path), stat.S_IFREG) for path in FILES]
        with patch.object(b, 'GPT2_VENVS', parent), patch.object(b, 'GPT2_CANDIDATE', candidate), \
             patch.object(b, 'GPT2_ROLLBACK', rollback), patch.object(b, 'GPT2_LIVE', live), \
             patch.object(b, 'GPT2_SELECTED', files), patch.object(b.os, 'readlink', return_value=str(candidate)):
            b.check_gpt2_layout()
            live.resolved = rollback
            with self.assertRaisesRegex(RuntimeError, 'does not select'):
                b.check_gpt2_layout()
            live.resolved = candidate
            files[1].mode = stat.S_IFLNK
            with self.assertRaisesRegex(RuntimeError, 'missing or redirected'):
                b.check_gpt2_layout()
            files[1].mode = stat.S_IFREG
            with patch.object(b, 'ROOTS', ('home/gpt-2/.venvs/gpt2-public',)):
                with self.assertRaisesRegex(RuntimeError, 'parent is missing'):
                    b.check_gpt2_layout()


if __name__ == '__main__':
    unittest.main()
