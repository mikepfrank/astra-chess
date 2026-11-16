"""Run deployed GPT-2 fixture suites inside the separately restricted unit.

No real model is loaded: these are the existing mock/FakeRunner suites.
The caller must supply PrivateNetwork, private HOME/tmp, read-only source and
candidate venv, and no production state/cache/credential access.
"""
from pathlib import Path
import importlib.metadata
import json
import os
import ssl
import sys
import tempfile
import time
import unittest


STAGE = Path('/home/gpt-2/.local/share/gpt2-security-stage/20261116/python')


def main():
    name = sys.argv[1]
    if name not in ('public', 'lab'):
        raise RuntimeError('Unknown fixture suite')
    source = STAGE / ('source-' + name)
    os.environ['HOME'] = tempfile.mkdtemp(prefix='gpt2-fixture-home-')
    os.environ['HF_HOME'] = tempfile.mkdtemp(prefix='gpt2-fixture-cache-')
    os.chdir(source)
    started = time.monotonic()
    # Explicit tiny tensor confirms compiled extension import/dispatch, not
    # checkpoint inference. Unit memory cap prevents a full-model accident.
    import torch
    import transformers
    import tokenizers
    import certifi
    import httpx
    assert torch.equal(torch.tensor([1, 2]) + 1, torch.tensor([2, 3]))
    assert certifi.__version__ == '2026.10.23'
    ssl.create_default_context(cafile=certifi.where())
    client = httpx.Client(verify=ssl.create_default_context(cafile=certifi.where()))
    client.close()
    discovered = unittest.defaultTestLoader.discover(str(source / 'tests'), pattern='test_*.py')
    # Legacy operator fixtures require uid=0 ownership in their temporary files.
    # They do not exercise the Python application/certifi change. Keep the
    # application tests under the real unprivileged service identity instead.
    excluded_modules = {'test_lightsail_preview', 'test_lightsail_promote',
                        'test_lightsail_update', 'test_gpt2_exclusive_preflight'}
    excluded_ids = []
    def selected(tests):
        for test in tests:
            if isinstance(test, unittest.TestSuite):
                yield from selected(test)
            elif test.__class__.__module__ in excluded_modules:
                excluded_ids.append(test.id())
            else:
                yield test
    suite = unittest.TestSuite(selected(discovered))
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    report = {
        'suite': name, 'tests_run': result.testsRun, 'failures': len(result.failures),
        'errors': len(result.errors), 'skips': len(result.skipped),
        'skip_reasons': sorted(set(reason for _, reason in result.skipped)),
        'excluded_operator_tests': len(excluded_ids),
        'excluded_operator_modules': sorted(excluded_modules),
        'failed_tests': [test.id() for test, _ in result.failures],
        'error_tests': [test.id() for test, _ in result.errors],
        'elapsed_seconds': round(time.monotonic() - started, 2),
        'python': sys.version.split()[0], 'openssl': ssl.OPENSSL_VERSION,
        'packages': {k: importlib.metadata.version(k) for k in
                     ('torch', 'transformers', 'tokenizers', 'certifi', 'httpx')},
        'tiny_tensor_and_tls_context_check': True,
        'real_model_loaded': False, 'real_api_calls': 0,
    }
    (STAGE / 'results' / (name + '-fixtures.json')).write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report), flush=True)
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__ == '__main__':
    main()
