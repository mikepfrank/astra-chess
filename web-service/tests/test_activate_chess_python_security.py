"""Exercise admission and two-venv rollback without touching a host or services."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('activate_chess_python_security',
    Path(__file__).parents[1] / 'tools/ops/activate_chess_python_security.py')
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


class ActivationTests(unittest.TestCase):
    def setUp(self):
        self.fs = {}
        self.plans = []
        for index, owner in enumerate(('astra', 'or-chess')):
            live, rollback, candidate = (Path('/fixture') / owner / x for x in ('live', 'rollback', 'candidate'))
            self.fs[str(live)] = ('directory', index)
            self.fs[str(candidate)] = ('directory', index + 10)
            self.plans.append(dict(owner=owner, live=live, rollback=rollback, candidate=candidate,
                                   runtime=Path('/runtime'), uid=0, identity=index, packages={}))
        self.mutations = []

    def ordinary_directory(self, path, uid):
        item = self.fs.get(str(path))
        if item is None or item[0] != 'directory':
            raise RuntimeError('Unexpected fixture directory')
        return item[1]

    def rename(self, old, new):
        self.assertNotIn(str(new), self.fs)
        self.fs[str(new)] = self.fs.pop(str(old))
        self.mutations.append(('rename', str(old), str(new)))

    def symlink(self, target, path):
        self.assertNotIn(str(path), self.fs)
        self.fs[str(path)] = ('symlink', str(target))
        self.mutations.append(('link', str(path), str(target)))

    def activate(self, *, fail_link=None, fail_probe=False, stopped_results=None):
        calls = 0
        def make_link(target, path):
            nonlocal calls
            calls += 1
            if calls == fail_link:
                raise OSError('Injected link failure')
            self.symlink(target, path)
        with patch.object(m, 'check_stopped', side_effect=stopped_results), \
             patch.object(m, 'sync_parent'), patch.object(m, 'ordinary_directory', side_effect=self.ordinary_directory), \
             patch.object(m.os.path, 'lexists', side_effect=lambda p: str(p) in self.fs), \
             patch.object(m.os, 'rename', side_effect=self.rename), patch.object(m.os, 'symlink', side_effect=make_link), \
             patch.object(m.os, 'readlink', side_effect=lambda p: self.fs[str(p)][1]), \
             patch.object(Path, 'is_symlink', lambda p: self.fs.get(str(p), (None,))[0] == 'symlink'), \
             patch.object(Path, 'unlink', lambda p: self.fs.pop(str(p))), \
             patch.object(m, 'probe', side_effect=RuntimeError('Injected probe failure') if fail_probe else None):
            m.activate(self.plans)

    def assert_originals_restored(self):
        for plan in self.plans:
            self.assertEqual(self.fs[str(plan['live'])], ('directory', plan['identity']))
            self.assertNotIn(str(plan['rollback']), self.fs)

    def test_both_paths_switched_and_originals_preserved(self):
        self.activate()
        for plan in self.plans:
            self.assertEqual(self.fs[str(plan['live'])], ('symlink', str(plan['candidate'])))
            self.assertEqual(self.fs[str(plan['rollback'])], ('directory', plan['identity']))

    def test_second_collision_refuses_before_first_mutation(self):
        self.fs[str(self.plans[1]['rollback'])] = ('directory', 100)
        with self.assertRaisesRegex(RuntimeError, 'collision'):
            self.activate()
        self.assertEqual(self.mutations, [])

    def test_changed_identity_refuses_before_any_mutation(self):
        self.fs[str(self.plans[1]['live'])] = ('directory', 100)
        with self.assertRaisesRegex(RuntimeError, 'identity'):
            self.activate()
        self.assertEqual(self.mutations, [])

    def test_first_link_failure_restores_originals(self):
        with self.assertRaisesRegex(RuntimeError, 'were restored'):
            self.activate(fail_link=1)
        self.assert_originals_restored()

    def test_second_link_failure_restores_both_originals(self):
        with self.assertRaisesRegex(RuntimeError, 'were restored'):
            self.activate(fail_link=2)
        self.assert_originals_restored()

    def test_post_switch_probe_failure_restores_both_originals(self):
        with self.assertRaisesRegex(RuntimeError, 'were restored'):
            self.activate(fail_probe=True)
        self.assert_originals_restored()

    def test_failed_stopped_guard_prevents_runtime_rollback(self):
        with self.assertRaisesRegex(RuntimeError, 'rollback was not attempted'):
            self.activate(stopped_results=[None, RuntimeError('Application started'), RuntimeError('Still running')])
        for plan in self.plans:
            self.assertEqual(self.fs[str(plan['live'])], ('symlink', str(plan['candidate'])))
            self.assertEqual(self.fs[str(plan['rollback'])], ('directory', plan['identity']))
        self.assertEqual(len(self.mutations), 4)

    def test_running_lingering_or_enabled_unit_refused(self):
        for changed in ({'ActiveState': 'active'}, {'MainPID': '123'}, {'UnitFileState': 'enabled'}):
            state = dict(ActiveState='inactive', MainPID='0', UnitFileState='disabled')
            state.update(changed)
            with patch.object(m, 'run', return_value='\n'.join(k + '=' + v for k, v in state.items())), \
                 patch.object(m, 'CHECKPOINTS', ()):
                with self.assertRaises(RuntimeError):
                    m.check_stopped()

    def test_stopped_timer_without_mainpid_is_accepted(self):
        def show(args):
            state = dict(ActiveState='inactive', UnitFileState='disabled')
            if not args[2].endswith('.timer'):
                state['MainPID'] = '0'
            return '\n'.join(k + '=' + v for k, v in state.items())
        with patch.object(m, 'run', side_effect=show), patch.object(m, 'CHECKPOINTS', ()):
            m.check_stopped()


if __name__ == '__main__':
    unittest.main()
