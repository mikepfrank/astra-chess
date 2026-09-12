"""Operator diagnostics must not pass service credentials to Codex."""
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from tools import check_linux_service


class ServiceCheckEnvironmentTests(unittest.TestCase):
    def test_version_probe_has_no_service_secrets_or_operator_profile(self):
        ambient = {name: 'private-placeholder' for name in (
            'OPENAI_API_KEY', 'ASTRA_SMTP_USER', 'ASTRA_SMTP_PASSWORD',
            'SMTP_PASSWORD', 'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY',
            'AWS_SESSION_TOKEN', 'HTTPS_PROXY', 'CODEX_HOME', 'HOME')}
        ambient['LANG'] = 'C.UTF-8'
        with tempfile.TemporaryDirectory() as scratch:
            config = SimpleNamespace(data_dir=Path(scratch), codex_bin='/reviewed/codex')
            roots = []

            def run(command, **kwargs):
                self.assertEqual(command, ['/reviewed/codex', '--version'])
                env = kwargs['env']
                for name in set(ambient) - {'LANG', 'HOME', 'CODEX_HOME'}:
                    self.assertNotIn(name, env)
                self.assertNotIn('private-placeholder', env.values())
                self.assertEqual(env['LANG'], 'C.UTF-8')
                root = Path(env['HOME'])
                roots.append(root)
                self.assertEqual(root.parent, config.data_dir)
                self.assertEqual(kwargs['cwd'], root)
                for name in ('CODEX_HOME', 'TMPDIR', 'APPDATA'):
                    self.assertTrue(Path(env[name]).is_dir())
                return SimpleNamespace(stdout='codex-cli 0.154.0\n')

            with patch.dict(os.environ, ambient, clear=True), patch.object(check_linux_service.subprocess, 'run', side_effect=run):
                self.assertEqual(check_linux_service._codex_version(config), 'codex-cli 0.154.0')
            self.assertEqual(len(roots), 1)
            self.assertFalse(roots[0].exists())


if __name__ == '__main__':
    unittest.main()
