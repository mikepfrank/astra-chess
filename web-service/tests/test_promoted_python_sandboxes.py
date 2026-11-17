import importlib.util
import json
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('sandbox_probe', Path(__file__).parents[1] / 'tools/ops/check_promoted_python_sandboxes.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class ProbeTests(unittest.TestCase):
    def test_repeated_environment_files_are_separate_and_ordered(self):
        lines = m.service_lines('[Service]\nUser=astra\nEnvironmentFile=/first\nEnvironment=VALUE=old\n')
        lines += m.service_lines('[Service]\nEnvironmentFile=/second\nEnvironment=VALUE=new\n')
        text = m.build_unit(lines, 'astra', 'astra-preflight')
        self.assertIn('EnvironmentFile=/first\nEnvironment=VALUE=old\nEnvironmentFile=/second\nEnvironment=VALUE=new\n', text)

    def test_runtime_strips_credentials_and_every_exec_hook(self):
        lines = ['EnvironmentFile=/secret', 'Environment=KEY=secret', 'PassEnvironment=KEY',
                 'UnsetEnvironment=KEY', 'ExecStartPre=/guard', 'ExecStart=/app',
                 'ExecStopPost=+/cleanup', 'ExecCondition=/gate', 'Restart=always', 'Type=simple',
                 'BindReadOnlyPaths=/venv', 'ReadWritePaths=/cache', 'MemoryMax=9G']
        text = m.build_unit(lines, 'gpt2-public', 'runtime')
        for value in ('/secret', 'KEY', '/guard', '/app', '/cleanup', '/gate', 'Restart=always', 'Type=simple'):
            self.assertNotIn(value, text)
        self.assertIn('BindReadOnlyPaths=/venv', text)
        self.assertIn('ReadWritePaths=/cache', text)
        self.assertIn('MemoryMax=9G', text)
        self.assertEqual(sum(line.startswith('Exec') for line in text.splitlines()), 1)

    def test_unit_sections_and_continuations(self):
        self.assertEqual(m.service_lines('[Unit]\nAfter=network.target\n[Service]\nUser=gpt-2\n[Install]\nWantedBy=x'), ['User=gpt-2'])
        with self.assertRaises(RuntimeError):
            m.service_lines('[Service]\nReadWritePaths=/a \\\n /b')

    def test_wrong_preflight_target_refused(self):
        with self.assertRaises(RuntimeError):
            m.build_unit([], 'gpt2-lab', 'astra-preflight')

    def test_runtime_output_requires_one_payload(self):
        text = 'status\nRUNTIME_VALIDATION_JSON {"tls_context":true}\nstatus'
        self.assertEqual(m.parse_output(text, 'runtime'), {'tls_context': True})
        with self.assertRaises(RuntimeError):
            m.parse_output(text + '\nRUNTIME_VALIDATION_JSON {}', 'runtime')

    def test_preflight_requires_all_checks_true(self):
        record = {'checks': {'sandbox': True}, 'limits': {}, 'python': '3.12.16', 'sqlite': '3.53.1', 'codex': '0.154.0'}
        self.assertEqual(m.parse_output('prefix\n' + json.dumps(record, indent=2) + '\nsuffix', 'astra-preflight'), record)
        record['checks']['sandbox'] = False
        with self.assertRaises(RuntimeError):
            m.parse_output(json.dumps(record), 'astra-preflight')


if __name__ == '__main__':
    unittest.main()
