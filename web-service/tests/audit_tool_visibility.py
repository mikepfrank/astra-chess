"""Actual Codex CLI, mocked upstream: preserve large Unicode tool results.

Three synthetic chess_status results put a long human message in their middle.
Check the actual next API request, saved history after a process restart, and
another tool result on that resumed thread. No private game data, real API
credentials or paid calls are used. Reports retain structure and hashes only.

Pass --commit with a full clean checkout SHA to create a deployment receipt;
without it, local development results explicitly are not exact-commit receipts.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tomllib
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from astra_web import codex_bridge as bridge
from astra_web.player_profiles import get_profile
from tests import audit_reasoning_roundtrip as roundtrip


APP = Path(__file__).resolve().parents[1]
FIXTURE_CHARACTERS = (20_000, 80_000, 160_000)
TOOL_OUTPUT_TOKEN_LIMIT = 65_536


class UnicodeJSON:
    """Patch one fixture module's JSON binding, never the global JSON module."""

    loads = staticmethod(json.loads)

    @staticmethod
    def dumps(value, **kwargs):
        kwargs.setdefault('ensure_ascii', False)
        return json.dumps(value, **kwargs)


def repeated(text, size):
    return (text * (size // len(text) + 1))[:size]


def fixture(size):
    message = repeated(
        'Synthetic user question: can you describe the tools available here? '
        'The museum asks about Unicode: café, λ, 日本語, ♟, 🐂, e\u0301 — please explain.\n',
        10_000)
    status = {'fixture': True, 'older_board_evidence': '',
              'messages': [{'role': 'human', 'text': message}],
              'later_decision_evidence': ''}
    padding = size - len(UnicodeJSON.dumps(status))
    assert padding > 0
    status['older_board_evidence'] = repeated('Synthetic previous board evidence. ', padding // 2)
    status['later_decision_evidence'] = repeated('Synthetic later decision evidence. ', padding - padding // 2)
    assert len(UnicodeJSON.dumps(status)) == size
    return status, message


def checkout():
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=APP, text=True).strip()
    tracked_changes = subprocess.check_output(
        ['git', 'status', '--porcelain', '--untracked-files=no'], cwd=APP, text=True).strip()
    return revision, not tracked_changes


async def audit(codex, version, audit_dir, *, commit=None):
    if version not in bridge.reviewed_versions('openrouter-glm'):
        raise bridge.CodexError('Tool visibility fixture requires an audited CLI version')
    revision, clean = checkout()
    if commit is not None and (revision != commit or not clean):
        raise bridge.CodexError('Exact-commit tool visibility audit requires the requested clean checkout')
    selected = get_profile('openrouter-glm')
    configured_limit = tomllib.loads(bridge._config_text(
        selected.model, selected.reasoning, selected)).get('tool_output_token_limit')
    if configured_limit != TOOL_OUTPUT_TOKEN_LIMIT:
        raise bridge.CodexError('Tool visibility audit requires the 65536-token tool output budget')
    audit_dir = Path(audit_dir).resolve()
    audit_dir.mkdir(parents=True, exist_ok=True)
    cases = []
    original_inspect = roundtrip.inspect_request
    for size in FIXTURE_CHARACTERS:
        status, message = fixture(size)
        expected_text = UnicodeJSON.dumps(status)

        def inspect(body, variant, serial, tool_result):
            row = original_inspect(body, variant, serial, tool_result)
            if serial == 1:
                return row
            expected_serial = 1 if serial in (2, 3) else 3
            outputs = [item for item in body.get('input', [])
                       if item.get('type') == 'function_call_output'
                       and item.get('call_id') == f'call-roundtrip-{expected_serial}']
            output = outputs[0].get('output') if len(outputs) == 1 else None
            if isinstance(output, list) and len(output) == 1:
                output = output[0].get('text')
            row['output_exact'] = output == expected_text
            row['output_characters'] = len(output) if isinstance(output, str) else None
            row['output_sha256'] = hashlib.sha256(output.encode()).hexdigest() if isinstance(output, str) else None
            row['user_message_exact'] = False
            if isinstance(output, str):
                try:
                    decoded = json.loads(output)
                    row['user_message_exact'] = decoded.get('messages') == [{'role': 'human', 'text': message}]
                except (ValueError, TypeError, AttributeError):
                    pass
            return row

        # audit_case runs sequentially; these scoped patches affect only its
        # fixture hooks, including production-style Unicode tool serialization.
        with patch.object(roundtrip, 'inspect_request', inspect), \
                patch.object(roundtrip, 'json', UnicodeJSON):
            case = await roundtrip.audit_case(codex, version, audit_dir, 'summary', tool_result=status)
        case.update(fixture_characters=len(expected_text), fixture_utf8_bytes=len(expected_text.encode()),
                    user_message_characters=len(message),
                    fixture_sha256=hashlib.sha256(expected_text.encode()).hexdigest())
        cases.append(case)
    final_revision, final_clean = checkout()
    exact = commit is not None and revision == final_revision == commit and clean and final_clean
    wire_checks = [row for case in cases for row in case['requests'][1:]]
    all_status = (len(wire_checks) == 9 and all(row.get('output_exact')
                  and row.get('status_snapshot_exact') for row in wire_checks))
    all_messages = len(wire_checks) == 9 and all(row.get('user_message_exact') for row in wire_checks)
    all_resumed = all(case.get('same_thread_resumed') for case in cases)
    report = {'commit': revision, 'checkout_clean': clean and final_clean, 'exact_commit': exact,
              'success': bool(all_status and all_messages and all_resumed
                              and all(case['audit_completed'] for case in cases)
                              and revision == final_revision and (commit is None or exact)),
              'cli_version': version, 'tool_output_token_limit': configured_limit,
              'external_provider_contacted': False, 'real_credentials_inherited': False,
              'case_count': len(cases), 'request_count': sum(len(case['requests']) for case in cases),
              'wire_check_count': len(wire_checks), 'all_status_snapshots_preserved': all_status,
              'all_user_messages_preserved': all_messages, 'all_threads_resumed': all_resumed, 'cases': cases}
    (audit_dir / 'tool-visibility.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex', required=True)
    parser.add_argument('--candidate-version', default='0.154.0')
    parser.add_argument('--audit-dir', type=Path, required=True)
    parser.add_argument('--receipt', type=Path)
    parser.add_argument('--commit', help='Full clean Git revision required for a deployment receipt')
    args = parser.parse_args(argv)
    if args.commit is not None and not re.fullmatch('[0-9a-f]{40}', args.commit):
        parser.error('--commit must be a full lowercase Git SHA')
    report = asyncio.run(audit(args.codex, args.candidate_version, args.audit_dir, commit=args.commit))
    if args.receipt is not None:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    # Per-case audit files hold bounded structural details. Keep CLI output short.
    print(json.dumps({key: value for key, value in report.items() if key != 'cases'}, indent=2))
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
