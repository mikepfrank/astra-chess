"""Run the offline chat/bridge regression suite for an exact checkout revision.

This preserves the runner used for the September 14, 2026 Linux deployments.
Fixtures use temporary data and mocked providers, never live player records.
"""
import argparse
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest


APP = Path(__file__).resolve().parents[1]
MODULES = (
    'test_bridge_time_policy', 'test_supervisor_limits', 'test_compaction_clock',
    'test_parallel_workers', 'test_chat_time_policy', 'test_postgame_chat',
    'test_chat_reasoning_policy', 'test_codex_bridge', 'test_player_profiles',
    'test_openrouter_gateway',
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('commit', help='Exact 40-character checkout commit to validate')
    args = parser.parse_args(argv)
    if not re.fullmatch('[0-9a-f]{40}', args.commit):
        parser.error('commit must be a full lowercase Git SHA')
    actual = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=APP, text=True).strip()
    if actual != args.commit:
        parser.error('checkout HEAD differs from the requested commit')
    if subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'],
                               cwd=APP, text=True).strip():
        parser.error('tracked checkout changes would invalidate the commit receipt')
    for key in ('OPENROUTER_API_KEY', 'OPENAI_API_KEY', 'CODEX_API_KEY', 'CHESS_GATEWAY_TOKEN'):
        os.environ.pop(key, None)
    os.chdir(APP)
    sys.path.insert(0, str(APP))
    logging.getLogger('asyncio').setLevel(logging.CRITICAL)
    suite = unittest.defaultTestLoader.loadTestsFromNames(['tests.' + name for name in MODULES])
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    receipt = dict(commit=args.commit, tests=result.testsRun, failures=len(result.failures),
                   errors=len(result.errors), skipped=len(result.skipped), success=result.wasSuccessful())
    output = APP / 'var/chat-tests.json'
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    print(json.dumps(receipt))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
