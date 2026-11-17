"""No-network parser, state guard, proof and request-bound tests."""
import importlib.util
import io
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch


def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / 'tools/ops' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


public = load('probe_gpt2_public_generation')
private = load('probe_gpt2_private_provider')


class ProbeTests(unittest.TestCase):
    def test_sse_heartbeat_and_terminal(self):
        source = io.BytesIO(b': heartbeat\n\nid: 2\nevent: progress\ndata: {"version":1,"seq":2}\n\n'
                            b'id: 3\nevent: complete\ndata: {"version":1,"seq":3}\n\n')
        events = list(public.read_events(source, time.monotonic() + 1))
        self.assertEqual(events, [('progress', '2', {'version': 1, 'seq': 2}),
                                  ('complete', '3', {'version': 1, 'seq': 3})])

    def test_sse_frame_bound(self):
        with patch.object(public, 'MAX_FRAME', 8), self.assertRaisesRegex(RuntimeError, 'too large'):
            list(public.read_events(io.BytesIO(b'0123456789\n\n'), time.monotonic() + 1))

    def test_sse_deadline(self):
        with self.assertRaisesRegex(RuntimeError, 'deadline'):
            list(public.read_events(io.BytesIO(b''), time.monotonic() - 1))

    def test_normalization_does_not_mutate(self):
        value = {'exported_at': 'now', 'blocks': [1]}
        self.assertEqual(public.normalized(value), {'blocks': [1]})
        self.assertIn('exported_at', value)

    def test_private_readiness_requires_stopped_disabled(self):
        with patch.object(private.subprocess, 'check_output', return_value='ActiveState=inactive\nMainPID=0\nUnitFileState=disabled\n'):
            private.require_lab_stopped()
        for bad in ('ActiveState=active\nMainPID=0\nUnitFileState=disabled\n',
                    'ActiveState=inactive\nMainPID=17\nUnitFileState=disabled\n',
                    'ActiveState=inactive\nMainPID=0\nUnitFileState=enabled\n'):
            with patch.object(private.subprocess, 'check_output', return_value=bad), self.assertRaises(RuntimeError):
                private.require_lab_stopped()

    def test_native_proof_required_and_duplicate_message_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            recorded = []
            callback = private.proof_callback(workspace, recorded)
            callback('_thread', {'thread_id': 'synthetic-thread_1'})
            self.assertTrue(callback('emit_message', {'text': 'Maintenance check started.'})['ok'])
            args = {'text': 'Maintenance check: 42.'}
            with self.assertRaisesRegex(RuntimeError, 'proof'):
                callback('emit_message', args)
            (workspace / 'maintenance-proof.txt').write_bytes(b'42\n')
            self.assertTrue(callback('emit_message', args)['ok'])
            with self.assertRaisesRegex(RuntimeError, 'more than two'):
                callback('emit_message', args)

    def test_internal_thread_acknowledgement_is_validated_and_stable(self):
        with tempfile.TemporaryDirectory() as temp:
            record = {}
            callback = private.proof_callback(Path(temp), [], record)
            with self.assertRaisesRegex(RuntimeError, 'initialization'):
                callback('emit_message', {'text': 'Maintenance check started.'})
            for bad in ({}, {'thread_id': '../escape'}, {'thread_id': 1}, {'thread_id': 'x', 'extra': 2}):
                with self.assertRaisesRegex(RuntimeError, 'Invalid internal'):
                    callback('_thread', bad)
            self.assertTrue(callback('_thread', {'thread_id': 'fixture-123'})['ok'])
            self.assertEqual(record, {'thread_id': 'fixture-123'})
            self.assertTrue(callback('_thread', {'thread_id': 'fixture-123'})['ok'])
            with self.assertRaisesRegex(RuntimeError, 'identifier changed'):
                callback('_thread', {'thread_id': 'different-456'})

    def test_final_comment_before_initial_ack_is_refused_even_with_proof(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            (workspace / 'maintenance-proof.txt').write_bytes(b'42\n')
            callback = private.proof_callback(workspace, [])
            callback('_thread', {'thread_id': 'fixture-123'})
            with self.assertRaisesRegex(RuntimeError, 'initial maintenance comment'):
                callback('emit_message', {'text': 'Maintenance check: 42.'})

    def test_unrequested_application_tools_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            callback = private.proof_callback(Path(temp), [])
            for name in ('query_gpt2', 'wait_for_human', 'search_web'):
                with self.assertRaisesRegex(RuntimeError, 'Unexpected application tool'):
                    callback(name, {})

    def test_request_limit_is_enforced_before_seventh_admission(self):
        class Base:
            def __init__(self):
                self.calls = 0
            def reserve(self, *args, **kwargs):
                self.calls += 1
                return {'id': self.calls}
        class Exceeded(Exception):
            pass
        ledger = private.bounded_ledger_type(Base, Exceeded)()
        for i in range(6):
            self.assertEqual(ledger.reserve('synthetic', 100)['id'], i + 1)
        with self.assertRaises(Exceeded):
            ledger.reserve('synthetic', 100)
        self.assertEqual(ledger.calls, 6)


if __name__ == '__main__':
    unittest.main()
