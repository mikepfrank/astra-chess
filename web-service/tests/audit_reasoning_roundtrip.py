"""Real Codex CLI, mocked upstream: inspect reasoning across tools and restart.

Creates fresh disposable homes only. Neither credentials nor real game state are
read. The saved report contains structural checks and hashes, never wire text.
An audit can complete successfully while demonstrating lost reasoning fields;
``all_reasoning_fields_preserved`` reports that separately from ``audit_completed``.
"""
import argparse
import asyncio
from collections import Counter
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
import tempfile

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from astra_web import codex_bridge as bridge
from astra_web.config import Config
from astra_web.openrouter_gateway import OpenRouterGateway
from astra_web.player_profiles import get_profile, new_player_binding


VARIANTS = ('summary', 'content', 'encrypted_content', 'combined')
TOOL_RESULT = {'fixture': True, 'ply': 20, 'fen': 'fixture-position-at-ply-20',
               'current_attempt': {'candidate_recorded': False,
                                   'root_query_completed': False, 'move_accepted': False}}


def reasoning_item(variant, serial):
    item = {'type': 'reasoning', 'id': f'rs-roundtrip-{variant}-{serial}', 'summary': []}
    if variant in ('summary', 'combined'):
        item['summary'] = [{'type': 'summary_text', 'text': f'Synthetic summary sentinel {serial}.'}]
    if variant in ('content', 'combined'):
        item['content'] = [{'type': 'reasoning_text', 'text': f'Synthetic reasoning sentinel {serial}.'}]
    if variant in ('encrypted_content', 'combined'):
        # Opaque synthetic text, not an encrypted real model response.
        item['encrypted_content'] = f'fixture-opaque-reasoning-{serial}'
    return item


def stream_response(serial, variant, call_tool):
    response_id = f'resp-roundtrip-{serial}'
    if call_tool:
        items = [reasoning_item(variant, serial), {
            'type': 'function_call', 'id': f'fc-roundtrip-{serial}', 'status': 'completed',
            'call_id': f'call-roundtrip-{serial}', 'name': 'chess_status', 'arguments': '{}'}]
    else:
        items = [{'type': 'message', 'id': f'msg-roundtrip-{serial}', 'role': 'assistant',
                  'status': 'completed', 'content': [{'type': 'output_text',
                  'text': 'Synthetic fixture turn completed.', 'annotations': []}]}]
    events = [{'type': 'response.created', 'response': {
        'id': response_id, 'model': 'z-ai/glm-5.3-flash', 'status': 'in_progress'}}]
    for index, item in enumerate(items):
        initial = {**item}
        if item['type'] == 'function_call':
            initial.update(status='in_progress', arguments='')
        elif item['type'] == 'message':
            initial.update(status='in_progress', content=[])
        events.append({'type': 'response.output_item.added', 'output_index': index, 'item': initial})
        if item['type'] == 'function_call':
            events.append({'type': 'response.function_call_arguments.delta',
                           'item_id': item['id'], 'output_index': index, 'delta': '{}'})
        elif item['type'] == 'message':
            events.append({'type': 'response.output_text.delta', 'item_id': item['id'],
                           'output_index': index, 'content_index': 0,
                           'delta': item['content'][0]['text']})
        events.append({'type': 'response.output_item.done', 'output_index': index, 'item': item})
    events.append({'type': 'response.completed', 'response': {
        'id': response_id, 'model': 'z-ai/glm-5.3-flash', 'status': 'completed', 'output': items,
        'usage': {'input_tokens': 100, 'output_tokens': 30, 'total_tokens': 130,
                  'input_tokens_details': {'cached_tokens': 0},
                  'output_tokens_details': {'reasoning_tokens': 10 if call_tool else 0}, 'cost': 0}}})
    return ''.join('event: ' + event['type'] + '\ndata: ' + json.dumps(event) + '\n\n'
                   for event in events).encode() + b'data: [DONE]\n\n'


def inspect_request(body, variant, serial):
    items = body.get('input', [])
    if not isinstance(items, list):
        raise bridge.CodexError('Reasoning fixture input is not an item list')
    phase = {1: 'initial', 2: 'same_turn_tool_result',
             3: 'after_process_restart', 4: 'resumed_turn_tool_result'}[serial]
    expected_serial = 1 if serial in (2, 3) else 3 if serial == 4 else None
    report = {'phase': phase, 'input_items': len(items),
              'input_types': dict(Counter(item.get('type', 'message') for item in items)),
              'include': body.get('include'), 'reasoning': body.get('reasoning'),
              'input_sha256': hashlib.sha256(json.dumps(items, sort_keys=True).encode()).hexdigest()}
    if expected_serial is None:
        return report
    expected = reasoning_item(variant, expected_serial)
    call_id = f'call-roundtrip-{expected_serial}'
    calls = [(i, item) for i, item in enumerate(items)
             if item.get('type') == 'function_call' and item.get('call_id') == call_id]
    outputs = [(i, item) for i, item in enumerate(items)
               if item.get('type') == 'function_call_output' and item.get('call_id') == call_id]
    report['matching_calls'] = len(calls)
    report['matching_outputs'] = len(outputs)
    # Codex may omit an upstream item's id on its next wire serialization.
    # Associate the adjacent reasoning item with our unique function call;
    # report id preservation separately from substantive field preservation.
    reasoning_index, actual = None, {}
    if len(calls) == 1 and calls[0][0] > 0:
        previous = calls[0][0] - 1
        if items[previous].get('type') == 'reasoning':
            reasoning_index, actual = previous, items[previous]
    report['reasoning_item_matches'] = int(reasoning_index is not None)
    report['reasoning_id_exact'] = actual.get('id') == expected['id']
    report['reasoning_field_exact'] = {field: actual.get(field) == expected[field]
        for field in ('summary', 'content', 'encrypted_content')
        if expected.get(field)}
    report['reasoning_item_fields'] = sorted(actual)
    report['status_snapshot_exact'] = False
    if len(outputs) == 1:
        output = outputs[0][1].get('output')
        try:
            if isinstance(output, str):
                output = json.loads(output)
            elif isinstance(output, list) and len(output) == 1:
                output = json.loads(output[0].get('text', ''))
        except (ValueError, TypeError, AttributeError):
            output = None
        report['status_snapshot_exact'] = output == TOOL_RESULT
    report['reasoning_call_result_order'] = bool(reasoning_index is not None and len(calls) == len(outputs) == 1
        and reasoning_index < calls[0][0] < outputs[0][0])
    return report


async def audit_case(codex, version, audit_dir, variant):
    root = Path(tempfile.mkdtemp(prefix=f'reasoning-{variant}-', dir=audit_dir)).resolve()
    home = bridge._private_directory(root / 'codex-home', root)
    workspace = bridge._private_directory(root / 'workspace', root)
    for directory in ('tmp', 'appdata'):
        bridge._private_directory(root / directory, root)
    selected = get_profile('openrouter-glm')
    instructions = new_player_binding(Config(model_profile='openrouter-glm', persona='arcturus'))['prompt']
    report = {'variant': variant, 'candidate_version': version, 'audit_directory': str(root),
              'external_provider_contacted': False, 'real_credentials_inherited': False,
              'requests': [], 'turn_statuses': [], 'tool_calls': [], 'audit_completed': False}
    process = rpc = None
    thread_id = None
    done = False

    async def provider(request):
        body = json.loads(request.content)
        serial = len(report['requests']) + 1
        if serial > 4:
            raise bridge.CodexError('Reasoning fixture exceeded its four-request bound')
        names = [tool.get('name') for tool in body.get('tools', [])]
        if (len(names) != 7 or set(names) != bridge.TOOL_NAMES
                or body.get('instructions') != instructions
                or body.get('model') != selected.model
                or body.get('reasoning') != {'effort': selected.reasoning}):
            raise bridge.CodexError('Reasoning fixture request boundaries differ')
        report['requests'].append(inspect_request(body, variant, serial))
        return httpx.Response(200, content=stream_response(serial, variant, serial in (1, 3)),
                              headers={'content-type': 'text/event-stream'})

    gateway = OpenRouterGateway('reasoning-roundtrip-dummy-key', transport=httpx.MockTransport(provider),
        budget_check=lambda key: {'remaining_usd': 49}, expected_instructions=instructions, profile=selected)

    async def fixture_tool(request_id, method, params):
        serial = 1 if not report['tool_calls'] else 3
        if (len(report['tool_calls']) >= 2 or method != 'item/tool/call'
                or params.get('threadId') != thread_id or params.get('namespace') is not None
                or params.get('tool') != 'chess_status' or params.get('arguments') != {}
                or params.get('callId') != f'call-roundtrip-{serial}'):
            raise bridge.CodexError('Reasoning fixture requested an unexpected host capability')
        report['tool_calls'].append('chess_status')
        await rpc.send({'id': request_id, 'result': {'success': True,
            'contentItems': [{'type': 'inputText', 'text': json.dumps(TOOL_RESULT)}]}})

    async def event(method, params):
        nonlocal done
        if method == 'turn/completed':
            status = params.get('turn', {}).get('status')
            report['turn_statuses'].append(status)
            if status != 'completed':
                raise bridge.CodexError('Reasoning fixture turn did not complete')
            done = True
        elif method == 'error':
            raise bridge.CodexError('Reasoning fixture CLI reported an action error')

    try:
        async with gateway:
            profile = replace(selected, base_url=gateway.base_url, env_key='CHESS_GATEWAY_TOKEN')
            (home / 'config.toml').write_text(bridge._config_text(profile.model, profile.reasoning, profile), encoding='utf-8')
            env = bridge._child_environment(root, home, include_key=False, env_key=profile.env_key)
            if any(key in env for key in ('OPENAI_API_KEY', 'OPENROUTER_API_KEY', 'CODEX_API_KEY')):
                raise bridge.CodexError('Real provider credential entered reasoning fixture')
            env[profile.env_key] = gateway.token
            check = await bridge._spawn(str(codex), '--version', env=env, cwd=str(workspace),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, limit=4096)
            try:
                output, _ = await asyncio.wait_for(check.communicate(), 10)
                if check.returncode or output.decode().strip() != f'codex-cli {version}':
                    raise bridge.CodexError('Reasoning fixture CLI version differs')
            finally:
                await bridge._terminate(check)
            for resumed in (False, True):
                process = await bridge._spawn(str(codex), 'app-server', '--stdio', '--strict-config',
                    cwd=str(workspace), env=env, stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, limit=bridge.MAX_RPC_BYTES)
                rpc = bridge._Rpc(process, event, fixture_tool)
                async with asyncio.timeout(30):
                    initialized = await rpc.request('initialize', {'clientInfo': {
                        'name': 'reasoning_roundtrip_audit', 'version': '0.1'},
                        'capabilities': {'experimentalApi': True}})
                    if Path(initialized.get('codexHome', '')).resolve() != home:
                        raise bridge.CodexError('Reasoning fixture did not use its isolated home')
                    await rpc.send({'method': 'initialized', 'params': {}})
                    effective = (await rpc.request('config/read', {'includeLayers': False}))['config']
                    bridge._verify_effective_config(effective, profile.model, profile.reasoning, profile)
                    params = {'model': profile.model, 'modelProvider': profile.provider,
                        'approvalPolicy': 'never', 'approvalsReviewer': 'user', 'sandbox': 'read-only',
                        'cwd': str(workspace), 'runtimeWorkspaceRoots': [], 'baseInstructions': instructions,
                        'developerInstructions': 'Synthetic reasoning protocol fixture; no live game or provider.'}
                    if resumed:
                        params.update(threadId=thread_id, excludeTurns=True)
                    else:
                        params.update(environments=[], dynamicTools=bridge.dynamic_tools(), ephemeral=False,
                                      allowProviderModelFallback=False)
                    started = await rpc.request('thread/resume' if resumed else 'thread/start', params)
                    expected = {'model': profile.model, 'modelProvider': profile.provider,
                        'approvalPolicy': 'never', 'approvalsReviewer': 'user', 'reasoningEffort': profile.reasoning,
                        'runtimeWorkspaceRoots': [], 'activePermissionProfile': None, 'instructionSources': [],
                        'sandbox': {'type': 'readOnly', 'networkAccess': False}}
                    if any(started.get(key) != value for key, value in expected.items()):
                        raise bridge.CodexError('Reasoning fixture thread boundaries differ')
                    observed_thread = started.get('thread', {}).get('id')
                    if not observed_thread or (resumed and observed_thread != thread_id):
                        raise bridge.CodexError('Reasoning fixture thread identity differs')
                    thread_id = observed_thread
                    report['same_thread_resumed'] = resumed
                    done = False
                    await rpc.request('turn/start', {'threadId': thread_id, 'model': profile.model,
                        'effort': profile.reasoning, 'approvalPolicy': 'never', 'approvalsReviewer': 'user',
                        'environments': [], 'runtimeWorkspaceRoots': [],
                        'sandboxPolicy': {'type': 'readOnly', 'networkAccess': False}, 'summary': 'none',
                        'input': [{'type': 'text', 'text': 'Read chess_status and complete this synthetic fixture turn.'}]})
                    while not done:
                        await rpc.dispatch(await rpc.read())
                await bridge._terminate(process)
                process = None
            report['audit_completed'] = (len(report['requests']) == 4 and report['same_thread_resumed']
                and report['turn_statuses'] == ['completed', 'completed']
                and report['tool_calls'] == ['chess_status', 'chess_status'])
    except Exception as error:
        report['failure_type'] = type(error).__name__
        if isinstance(error, bridge.CodexError):
            report['failure'] = str(error)
    finally:
        if process:
            await bridge._terminate(process)
        report['gateway_request_count'] = gateway.request_count
        report['gateway_rejections'] = gateway.rejections
        report['gateway_streams_complete'] = (len(gateway.evidence) == 4
            and all(row.get('stream_complete') is True for row in gateway.evidence))
        report['audit_completed'] = bool(report['audit_completed'] and report['gateway_streams_complete']
            and gateway.request_count == 4 and gateway.budget_check_count == 4 and not gateway.rejections)
        checks = report['requests'][1:]
        report['all_reasoning_fields_preserved'] = bool(report['audit_completed']
            and all(all(row.get('reasoning_field_exact', {}).values())
                    and row.get('reasoning_item_matches') == 1 for row in checks))
        report['all_status_snapshots_preserved'] = bool(report['audit_completed']
            and all(row.get('status_snapshot_exact') for row in checks))
        (root / 'audit.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


async def audit(codex, version, audit_dir, variants=VARIANTS):
    if version not in bridge.reviewed_versions('openrouter-glm'):
        raise bridge.CodexError('Reasoning fixture requires an audited CLI version')
    audit_dir = Path(audit_dir).resolve()
    audit_dir.mkdir(parents=True, exist_ok=True)
    cases = []
    for variant in variants:
        cases.append(await audit_case(codex, version, audit_dir, variant))
    return {'audit_completed': all(case['audit_completed'] for case in cases),
            'external_provider_contacted': False, 'cases': cases}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex', required=True)
    parser.add_argument('--candidate-version', default='0.154.0')
    parser.add_argument('--audit-dir', type=Path, required=True)
    parser.add_argument('--variant', choices=('all',) + VARIANTS, default='all')
    args = parser.parse_args()
    report = asyncio.run(audit(args.codex, args.candidate_version, args.audit_dir,
        VARIANTS if args.variant == 'all' else (args.variant,)))
    print(json.dumps(report, indent=2))
    return 0 if report['audit_completed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
