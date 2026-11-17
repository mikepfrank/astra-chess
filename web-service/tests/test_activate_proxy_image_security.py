"""Local guarded file-swap fixtures; no SSH, services or model calls."""
import importlib.util
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('proxy_image_security',
    Path(__file__).parents[1] / 'tools/ops/activate_proxy_image_security.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class ActivationTests(unittest.TestCase):
    def test_launcher_changes_only_one_token(self):
        raw = b'#!/bin/bash\nset -euo pipefail\nrun ' + m.OLD_TAG.encode() + b' "$@"\n'
        expected = raw.replace(m.OLD_TAG.encode(), m.NEW_IMAGE.encode())
        with patch.object(m, 'OLD_LAUNCHER', m.digest(raw)), patch.object(m, 'NEW_LAUNCHER', m.digest(expected)):
            self.assertEqual(m.launcher_bytes(raw), expected)

    def test_changed_original_launcher_refused(self):
        with self.assertRaisesRegex(RuntimeError, 'reviewed original'):
            m.launcher_bytes(b'changed')

    def test_multiple_image_tokens_refused(self):
        raw = (m.OLD_TAG + ' ' + m.OLD_TAG).encode()
        with patch.object(m, 'OLD_LAUNCHER', m.digest(raw)), self.assertRaisesRegex(RuntimeError, 'exactly one'):
            m.launcher_bytes(raw)

    def test_missing_image_token_refused(self):
        raw = b'no image reference'
        with patch.object(m, 'OLD_LAUNCHER', m.digest(raw)), self.assertRaisesRegex(RuntimeError, 'exactly one'):
            m.launcher_bytes(raw)

    def test_unreviewed_proposed_hash_refused(self):
        raw = m.OLD_TAG.encode()
        with patch.object(m, 'OLD_LAUNCHER', m.digest(raw)), self.assertRaisesRegex(RuntimeError, 'reviewed change'):
            m.launcher_bytes(raw)

    def plan(self, directory):
        live = Path(directory) / 'live'
        live.write_bytes(b'original')
        info = live.stat()
        return m.placement(live, m.digest(b'original'), m.digest(b'candidate'),
                           (info.st_uid, info.st_gid), stat.S_IMODE(info.st_mode))

    def test_original_placement_rejects_rollback_collision(self):
        with tempfile.TemporaryDirectory() as temp:
            plan = self.plan(temp)
            plan['rollback'].write_bytes(b'previous')
            with self.assertRaisesRegex(RuntimeError, 'Rollback path already'):
                m.placement(plan['live'], plan['old_hash'], plan['new_hash'], plan['owner'], plan['mode'])

    def test_unknown_active_hash_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            plan = self.plan(temp)
            plan['live'].write_bytes(b'unexpected')
            with self.assertRaisesRegex(RuntimeError, 'Unrecognized'):
                m.placement(plan['live'], plan['old_hash'], plan['new_hash'], plan['owner'], plan['mode'])

    def test_atomic_swap_retains_original_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            plan = self.plan(temp)
            with patch.object(m, 'metadata'), patch.object(m, 'sync_directory'), \
                 patch.object(m.os, 'O_NOFOLLOW', getattr(os, 'O_NOFOLLOW', 0), create=True):
                m.preserve_and_replace(plan, b'candidate')
            self.assertEqual(plan['live'].read_bytes(), b'candidate')
            self.assertEqual(plan['rollback'].read_bytes(), b'original')

    def test_candidate_checksum_refused_before_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            plan = self.plan(temp)
            with self.assertRaisesRegex(RuntimeError, 'Candidate bytes'):
                m.preserve_and_replace(plan, b'wrong')
            self.assertFalse(plan['rollback'].exists())
            self.assertEqual(plan['live'].read_bytes(), b'original')

    def test_changed_original_refused_before_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            plan = self.plan(temp)
            plan['live'].write_bytes(b'changed')
            with self.assertRaisesRegex(RuntimeError, 'identity changed'):
                m.preserve_and_replace(plan, b'candidate')
            self.assertFalse(plan['rollback'].exists())

    def test_rollback_requires_stopped_guard_before_writes(self):
        guard = Mock(side_effect=RuntimeError('running'))
        with patch.object(m, 'regular') as regular, patch.object(m, 'replace_bytes') as replace:
            with self.assertRaisesRegex(RuntimeError, 'running'):
                m.restore({}, guard)
            regular.assert_not_called()
            replace.assert_not_called()

    def test_rollback_refuses_unrecognized_live_bytes(self):
        plan = {'live': Path('live'), 'rollback': Path('rollback'), 'owner': (0, 0),
                'mode': 0o755, 'old_hash': m.digest(b'old'), 'new_hash': m.digest(b'new')}
        with patch.object(m, 'regular', side_effect=[(b'other', None), (b'old', None)]), \
             patch.object(m, 'replace_bytes') as replace:
            with self.assertRaisesRegex(RuntimeError, 'Rollback refused'):
                m.restore(plan, Mock())
            replace.assert_not_called()

    def test_rollback_restores_only_verified_original(self):
        plan = {'live': Path('live'), 'rollback': Path('rollback'), 'owner': (0, 0),
                'mode': 0o755, 'old_hash': m.digest(b'old'), 'new_hash': m.digest(b'new')}
        guard = Mock()
        with patch.object(m, 'regular', side_effect=[(b'new', None), (b'old', None)]), \
             patch.object(m, 'replace_bytes') as replace:
            m.restore(plan, guard)
            guard.assert_called_once_with()
            replace.assert_called_once_with(plan['live'], b'old', (0, 0), 0o755)

    def test_replace_failure_keeps_original_and_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            plan = self.plan(temp)
            with patch.object(m, 'metadata'), patch.object(m, 'sync_directory'), \
                 patch.object(m.os, 'O_NOFOLLOW', getattr(os, 'O_NOFOLLOW', 0), create=True), \
                 patch.object(m.os, 'replace', side_effect=OSError('fixture failure')):
                with self.assertRaises(OSError):
                    m.preserve_and_replace(plan, b'candidate')
            self.assertEqual(plan['live'].read_bytes(), b'original')
            self.assertEqual(plan['rollback'].read_bytes(), b'original')
            self.assertFalse(list(Path(temp).glob('.live.security-*')))

    def test_repeated_apply_refused(self):
        with patch.object(m, 'regular') as read:
            with self.assertRaisesRegex(RuntimeError, 'Already activated'):
                m.preserve_and_replace({'state': 'activated'}, b'candidate')
            read.assert_not_called()


if __name__ == '__main__':
    unittest.main()
