"""Offline gate transactions with real temporary files and mocked host services.

Linux privilege/locking and TLS/process operations are fixtures here. The tests
exercise exact-byte writes and rollback without network, signals, or live paths.
"""
import importlib.util
import json
import os
from pathlib import Path
import signal
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


SOURCE = Path(__file__).resolve().parents[1] / 'tools/ops/arcturus_maintenance_gate.py'
SPEC = importlib.util.spec_from_file_location('arcturus_maintenance_gate', SOURCE)
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)
caddy = gate._primitives()
ASTRA = (b'{\n    admin off\n}\n\nastraplayschess.com {\n'
         b'    reverse_proxy 127.0.0.1:8788\n}\n\n'
         b'www.astraplayschess.com {\n'
         b'    redir https://astraplayschess.com{uri} permanent\n}\n\n')
ARCTURUS = (b'arcturus.astraplayschess.com {\n    reverse_proxy 127.0.0.1:8792\n}\n\n'
            b'arcturuschess.com {\n    reverse_proxy 127.0.0.1:8792\n}\n\n')
WWW = b'www.arcturuschess.com {\n    redir https://arcturuschess.com{uri} 308\n}\n'
ORIGINAL = ASTRA + ARCTURUS + WWW


class CandidateTests(unittest.TestCase):
    def test_changes_only_the_two_arcturus_proxy_blocks(self):
        candidate = gate.candidate_bytes(ORIGINAL)
        self.assertTrue(candidate.startswith(ASTRA))
        self.assertTrue(candidate.endswith(WWW))
        self.assertEqual(candidate.count(b'header Retry-After "30"'), 2)
        self.assertEqual(candidate.count(b'respond "' + gate.BODY + b'" 503'), 2)
        self.assertNotIn(b'reverse_proxy 127.0.0.1:8792', candidate)
        self.assertEqual(candidate.count(b'reverse_proxy 127.0.0.1:8788'), 1)

    def test_rejects_changed_duplicate_and_already_gated_blocks(self):
        for data in (b'', ORIGINAL.replace(b'127.0.0.1:8792', b'127.0.0.1:9999'),
                     ORIGINAL + ARCTURUS, gate.candidate_bytes(ORIGINAL), b'\x00' + ORIGINAL):
            with self.subTest(data=data), self.assertRaises(ValueError):
                gate.candidate_bytes(data)


class FixtureOS:
    """Keep real file I/O while simulating only Linux privilege/directory fsync."""
    O_NOFOLLOW = getattr(os, 'O_NOFOLLOW', 0)
    O_DIRECTORY = getattr(os, 'O_DIRECTORY', 0)
    geteuid = staticmethod(lambda: 0)
    pidfd_open = staticmethod(lambda pid: None)

    def __getattr__(self, name):
        return getattr(os, name)

    @staticmethod
    def open(path, flags):
        if Path(path).is_dir():
            path = Path(path) / '.fixture-directory-fsync'
            flags = os.O_RDWR | os.O_CREAT
        return os.open(path, flags | getattr(os, 'O_BINARY', 0))


class FixtureAuditRoot:
    def __init__(self, path):
        self.path = path

    def __fspath__(self):
        return str(self.path)

    def mkdir(self, **kwargs):
        self.path.mkdir(**kwargs)

    @staticmethod
    def lstat():
        return SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_uid=0)


class TransactionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.config = self.root / 'Caddyfile'
        self.config.write_bytes(ORIGINAL)
        self.original_stat = self.config.stat()
        self.candidate = gate.candidate_bytes(ORIGINAL)
        self.audit_root = self.root / 'audits'
        self.host_checks = []
        self.patcher(gate, 'os', FixtureOS())
        self.patcher(gate, 'sys', SimpleNamespace(platform='linux'))
        self.patcher(gate, 'signal', SimpleNamespace(SIGTERM=signal.SIGTERM,
            SIGHUP=getattr(signal, 'SIGHUP', 1), pidfd_send_signal=Mock(), signal=Mock(return_value=0)))
        self.patcher(gate, 'AUDIT_ROOT', FixtureAuditRoot(self.audit_root))
        self.patcher(gate, '_primitives', return_value=caddy)
        modules = patch.dict(sys.modules, {'fcntl': SimpleNamespace(LOCK_EX=2, LOCK_NB=4, flock=Mock())})
        modules.start()
        self.addCleanup(modules.stop)
        self.patcher(caddy, 'CONFIG', self.config)
        self.identity = self.patcher(caddy, 'caddy_identity', return_value=(111, 'caddy-start'))
        self.patcher(caddy, 'active_pid', return_value=222)
        self.patcher(caddy, 'process_stamp', return_value=(222, 'astra-start'))
        self.signal = self.patcher(caddy, 'signal_caddy')
        self.patcher(caddy, 'original_sites', return_value={'astra': 'unchanged', 'www': 'unchanged'})
        self.patcher(caddy, 'await_routes', side_effect=lambda check, **kwargs: check())
        self.command = self.patcher(caddy, 'run', side_effect=self.command_result)
        self.patcher(caddy, 'request', side_effect=self.health)
        owner = self

        class Connection:
            def __init__(self, host, **kwargs):
                self.host = host

            def request(self, method, path, headers):
                owner.assertEqual((method, path), ('GET', '/health'))
                owner.assertEqual(headers['Host'], self.host)
                owner.host_checks.append(('gated', self.host))

            def getresponse(self):
                owner.assertEqual(owner.config.read_bytes(), owner.candidate)
                return SimpleNamespace(status=503, getheader=lambda name: '30',
                                       read=lambda limit: gate.BODY)

            def close(self):
                pass

        self.patcher(caddy, 'LocalTLSConnection', Connection)

    def patcher(self, module, name, *args, **kwargs):
        patcher = patch.object(module, name, *args, **kwargs)
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    @staticmethod
    def command_result(command, **kwargs):
        return b'v2.11.4 fixture\n' if command[1] == 'version' else b'validated\n'

    def health(self, host, path):
        self.assertIn(host, gate.HOSTS)
        self.assertEqual(path, '/health')
        self.assertEqual(self.config.read_bytes(), ORIGINAL)
        self.host_checks.append(('healthy', host))
        return 200, None, b'{"ok":true}'

    def report(self):
        paths = list(self.audit_root.glob('gate-*/report.json'))
        self.assertEqual(len(paths), 1)
        return json.loads(paths[0].read_text())

    def test_context_body_error_restores_exact_bytes_inode_and_pinned_processes(self):
        with self.assertRaisesRegex(RuntimeError, 'fixture deployment failed'):
            with gate.arcturus_maintenance_gate() as receipt:
                self.assertEqual(self.config.read_bytes(), self.candidate)
                self.assertTrue(receipt['entered'])
                self.assertFalse(receipt['restored'])
                raise RuntimeError('fixture deployment failed')
        self.assertEqual(self.config.read_bytes(), ORIGINAL)
        self.assertEqual(self.config.stat().st_ino, self.original_stat.st_ino)
        self.assertEqual(self.signal.call_count, 2)
        for call in self.signal.call_args_list:
            self.assertEqual(call.kwargs, {'expected': (111, 'caddy-start')})
            self.assertEqual(call.args[0].st_ino, self.original_stat.st_ino)
        report = self.report()
        self.assertTrue(report['restored'])
        self.assertEqual(report['caddy_pid'], 111)
        self.assertEqual(report['original_astra_pid'], 222)
        self.assertEqual(self.host_checks,
            [('healthy', host) for host in gate.HOSTS] +
            [('gated', host) for host in gate.HOSTS] +
            [('healthy', host) for host in gate.HOSTS])

    def test_candidate_validation_failure_never_mutates_or_signals(self):
        self.command.side_effect = [b'v2.11.4 fixture\n', caddy.ActivationError('invalid candidate')]
        with self.assertRaisesRegex(caddy.ActivationError, 'invalid candidate'):
            with gate.arcturus_maintenance_gate():
                self.fail('Invalid candidate must not yield to a deployment')
        self.assertEqual(self.config.read_bytes(), ORIGINAL)
        self.assertEqual(self.config.stat().st_ino, self.original_stat.st_ino)
        self.signal.assert_not_called()
        self.assertFalse(self.report()['entered'])

    def test_concurrent_edit_is_preserved_and_manual_recovery_source_is_recorded(self):
        changed = self.candidate + b'\n# concurrent operator edit\n'
        with self.assertRaisesRegex(caddy.ActivationError, 'manual recovery'):
            with gate.arcturus_maintenance_gate():
                self.config.write_bytes(changed)
        self.assertEqual(self.config.read_bytes(), changed)
        self.assertEqual(self.signal.call_count, 1)
        report = self.report()
        self.assertFalse(report['restored'])
        self.assertEqual(Path(report['manual_recovery_source']).read_bytes(), ORIGINAL)


if __name__ == '__main__':
    unittest.main()
