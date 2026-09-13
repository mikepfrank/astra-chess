"""Capture real Codex compaction against the existing no-key loopback fixture.

Creates only a fresh disposable Codex home and sanitized audit report. No live
thread, credential, provider or paid inference is used. The mock intentionally
returns HTTP 400 after capture; this audits request shape, not summarization.
"""
import argparse
import asyncio
import importlib.util
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit-script', type=Path,
                        default=Path(__file__).with_name('audit_model_wire.py'))
    parser.add_argument('--codex', required=True)
    parser.add_argument('--candidate-version', required=True)
    parser.add_argument('--audit-dir', type=Path, required=True)
    args = parser.parse_args()
    source = args.audit_script.resolve()
    sys.path.insert(0, str(source.parent))
    spec = importlib.util.spec_from_file_location('compaction_wire_base', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original_rpc = module.bridge._Rpc
    evidence = {'initiated_rpc': 'thread/compact/start', 'compaction_rpc_requested': False}

    class CompactionRpc(original_rpc):
        async def request(self, method, params):
            if method == 'turn/start':
                method, params = 'thread/compact/start', {'threadId': params['threadId']}
                evidence['compaction_rpc_requested'] = True
            return await super().request(method, params)

    module.bridge._Rpc = CompactionRpc
    try:
        report = asyncio.run(module.audit(args.codex, args.audit_dir,
                                          candidate_version=args.candidate_version))
    finally:
        module.bridge._Rpc = original_rpc
    report.update(evidence)
    report['compaction_shape_verified'] = bool(
        evidence['compaction_rpc_requested'] and report.get('request_captured') and report.get('instructions_match')
        and report.get('request_path') == '/v1/responses'
        and report.get('tool_names') == [] and report.get('tool_types') == []
        and report.get('external_provider_contacted') is False
        and report.get('real_credentials_inherited') is False)
    destination = Path(report['audit_directory']) / 'audit.json'
    destination.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'compaction_shape_verified': report['compaction_shape_verified'],
                      'report': str(destination), **evidence}, indent=2))
    return 0 if report['compaction_shape_verified'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
