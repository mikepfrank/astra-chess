"""Guard/rollback fixtures; no host/service/network access."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

SPEC = importlib.util.spec_from_file_location('activate_gpt2_security_runtime',
    Path(__file__).parents[1] / 'tools/ops/activate_gpt2_security_runtime.py')
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


class ActivationTests(unittest.TestCase):
    def test_inventory_rejects_changed_bytes_and_added_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'venv'
            root.mkdir()
            (root / 'module.py').write_text('approved')
            stage = Path(temp) / 'stage'
            stage.mkdir()
            expected = m.files(root)
            (stage / 'live-files.json').write_text(json.dumps(expected))
            with patch.object(m, 'STAGE', stage), patch.dict(m.INVENTORY_HASHES, live=m.canonical_digest(expected)):
                self.assertEqual(m.check_inventory(root, 'live'), 1)
                (root / 'module.py').write_text('different')
                with self.assertRaisesRegex(RuntimeError, 'content'):
                    m.check_inventory(root, 'live')
                (root / 'module.py').write_text('approved')
                (root / 'extra.py').write_text('unexpected')
                with self.assertRaisesRegex(RuntimeError, 'content'):
                    m.check_inventory(root, 'live')

    def test_inventory_rejects_modified_recorded_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            stage = Path(temp)
            (stage / 'live-files.json').write_text('{}')
            with patch.object(m, 'STAGE', stage), self.assertRaisesRegex(RuntimeError, 'Recorded inventory'):
                m.check_inventory(stage, 'live')

    def test_ordinary_directory_collision(self):
        with tempfile.TemporaryDirectory() as temp:
            live, candidate, rollback = (Path(temp) / x for x in ('live', 'candidate', 'rollback'))
            live.mkdir()
            candidate.mkdir()
            self.assertEqual(m.placement(live, candidate, rollback), 'original')
            rollback.mkdir()
            with self.assertRaisesRegex(RuntimeError, 'Rollback path'):
                m.placement(live, candidate, rollback)

    def test_swap_preserves_directory_then_links_candidate(self):
        live, candidate, rollback = Mock(), Mock(), Mock()
        rollback.stat.return_value.st_uid = 1001
        rollback.stat.return_value.st_gid = 1001
        with patch.object(m, 'placement', return_value='original'), patch.object(m.os, 'rename') as rename, \
             patch.object(m.os, 'symlink') as link, patch.object(m.os, 'chown', create=True) as chown, \
             patch.object(m, 'sync_directory') as sync:
            m.swap(live, candidate, rollback)
            rename.assert_called_once_with(live, rollback)
            link.assert_called_once_with(candidate, live)
            chown.assert_called_once_with(live, 1001, 1001, follow_symlinks=False)
            sync.assert_called_once_with(live.parent)

    def test_link_failure_restores_original_directory(self):
        live, candidate, rollback = Mock(), Mock(), Mock()
        live.is_symlink.return_value = False
        with patch.object(m, 'placement', return_value='original'), patch.object(m.os, 'rename') as rename, \
             patch.object(m.os, 'symlink', side_effect=OSError('fixture')), \
             patch.object(m.os.path, 'lexists', return_value=False), patch.object(m, 'sync_directory'):
            with self.assertRaises(OSError):
                m.swap(live, candidate, rollback)
            self.assertEqual(rename.call_args_list[0].args, (live, rollback))
            self.assertEqual(rename.call_args_list[1].args, (rollback, live))
            live.unlink.assert_not_called()

    def test_repeated_apply_is_refused_before_mutation(self):
        with patch.object(m, 'placement', return_value='activated'), patch.object(m.os, 'rename') as rename:
            with self.assertRaisesRegex(RuntimeError, 'Already activated'):
                m.swap()
            rename.assert_not_called()

    def test_postcheck_rollback_restores_only_verified_link(self):
        live, candidate, rollback = Mock(), Mock(), Mock()
        guard = Mock()
        with patch.object(m, 'placement', return_value='activated'), patch.object(m.os, 'rename') as rename, \
             patch.object(m, 'sync_directory') as sync:
            m.restore_original(guard, live, candidate, rollback)
            guard.assert_called_once_with()
            live.unlink.assert_called_once_with()
            rename.assert_called_once_with(rollback, live)
            sync.assert_called_once_with(live.parent)

    def test_postcheck_rollback_refuses_running_host_without_unlink(self):
        live, candidate, rollback = Mock(), Mock(), Mock()
        guard = Mock(side_effect=RuntimeError('running'))
        with patch.object(m, 'placement', return_value='activated'), patch.object(m.os, 'rename') as rename:
            with self.assertRaisesRegex(RuntimeError, 'running'):
                m.restore_original(guard, live, candidate, rollback)
            live.unlink.assert_not_called()
            rename.assert_not_called()

    def test_postcheck_rollback_refuses_wrong_placement(self):
        live, candidate, rollback = Mock(), Mock(), Mock()
        with patch.object(m, 'placement', return_value='original'), patch.object(m.os, 'rename') as rename:
            with self.assertRaisesRegex(RuntimeError, 'identity'):
                m.restore_original(Mock(), live, candidate, rollback)
            live.unlink.assert_not_called()
            rename.assert_not_called()


if __name__ == '__main__':
    unittest.main()
