"""Real CLI, mocked provider: use a tool, compact, continue and resume one thread.

Fresh disposable state and a dummy loopback credential only. All upstream
inference and spending checks are mocked; no live game or provider is accessed.
The report contains structural checks, not prompts or model output.
"""
import argparse
import asyncio
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
from astra_web.openrouter_gateway import OpenRouterGateway, MODEL
from astra_web.player_profiles import get_profile, new_player_binding


SUMMARY = 'Fixture checkpoint: compaction completed. The next step is a normal fixture turn. No chess move has been made.'
TOOL_RESULT = {'fixture_status': 'authoritative local fixture; no game is active'}
CALL_ID = 'call-fixture-status'


def response_stream(serial, text, *, function_call=False, incomplete=False):
    response_id, item_id = f'resp-fixture-{serial}', f'msg-fixture-{serial}'
    item = {'id': item_id, 'type': 'message', 'role': 'assistant', 'status': 'completed',
            'content': [{'type': 'output_text', 'text': text, 'annotations': []}]}
    if function_call:
        item = {'id': f'fc-fixture-{serial}', 'type': 'function_call', 'status': 'completed',
                'call_id': CALL_ID, 'name': 'chess_status', 'arguments': '{}'}
    events = [
        {'type': 'response.created', 'response': {'id': response_id, 'model': 'z-ai/glm-5.3-flash'}},
        {'type': 'response.output_item.added', 'output_index': 0,
         'item': {**item, 'status': 'in_progress', 'content': []}},
        {'type': 'response.output_text.delta', 'item_id': item_id, 'output_index': 0,
         'content_index': 0, 'delta': text},
        {'type': 'response.output_item.done', 'output_index': 0, 'item': item},
        {'type': 'response.completed', 'response': {'id': response_id, 'model': 'z-ai/glm-5.3-flash',
         'status': 'completed', 'output': [item], 'usage': {'input_tokens': 100, 'output_tokens': 20,
         'total_tokens': 120, 'input_tokens_details': {'cached_tokens': 0},
         'output_tokens_details': {'reasoning_tokens': 0}, 'cost': 0}}},
    ]
    if function_call:
        events[1]['item'] = {**item, 'status': 'in_progress', 'arguments': ''}
        events[2] = {'type': 'response.function_call_arguments.delta', 'item_id': item['id'],
                     'output_index': 0, 'delta': '{}'}
    if incomplete:
        events[-1]['type'] = 'response.incomplete'
        events[-1]['response'].update(status='incomplete', incomplete_details={'reason': 'max_output_tokens'})
    return ''.join('event: ' + event['type'] + '\ndata: ' + json.dumps(event) + '\n\n'
                   for event in events).encode() + b'data: [DONE]\n\n'


async def audit(codex, candidate_version, audit_dir, *, terminal_incomplete=False):
    if candidate_version not in bridge.reviewed_versions('openrouter-glm'):
        raise bridge.CodexError('Lifecycle audit requires a reviewed exact CLI version')
    audit_dir = Path(audit_dir).resolve()
    audit_dir.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='compaction-lifecycle-', dir=audit_dir)).resolve()
    home = bridge._private_directory(root / 'codex-home', root)
    workspace = bridge._private_directory(root / 'workspace', root)
    for name in ('tmp', 'appdata'):
        bridge._private_directory(root / name, root)
    model_profile = get_profile('openrouter-glm')
    instructions = new_player_binding(Config(model_profile='openrouter-glm', persona='arcturus'))['prompt']
    report = {'candidate_version': candidate_version, 'audit_directory': str(root),
              'context_window': model_profile.context_window,
              'compact_limit': model_profile.compact_limit,
              'expected_reasoning': model_profile.reasoning,
              'expected_max_output_tokens': model_profile.max_output_tokens,
              'external_provider_contacted': False, 'real_credentials_inherited': False,
              'requests': [], 'compaction_events': [], 'completed_turns': 0, 'turn_statuses': [],
              'tool_calls': [], 'terminal_incomplete_fixture': terminal_incomplete,
              'output_limit_error_observed': False, 'cli_preserved_output_limit_code': False,
              'fatal_error_without_retry': False,
              'same_thread_resumed': False, 'success': False}
    process = None
    async def provider(request):
        body = json.loads(request.content)
        tools = body.get('tools')
        kind = 'compaction' if tools == [] else 'chess'
        names = [tool.get('name') for tool in tools]
        if kind == 'chess' and (set(names) != bridge.TOOL_NAMES or len(names) != 7):
            raise bridge.CodexError('Lifecycle fixture received unexpected tool schemas')
        canonical = {tool['name']: tool['inputSchema'] for tool in bridge.dynamic_tools()}
        schemas_match = all(tool.get('parameters') == canonical.get(tool.get('name')) for tool in tools)
        if not schemas_match:
            raise bridge.CodexError('Lifecycle fixture tool parameter bounds changed')
        history_text = json.dumps(body.get('input', []))
        report['requests'].append({'kind': kind, 'tools': names,
            'canonical_schemas_match': schemas_match,
            'instructions_match': body.get('instructions') == instructions,
            'instructions_sha256': hashlib.sha256(instructions.encode()).hexdigest(),
            'model': body.get('model'), 'reasoning': body.get('reasoning'),
            'max_output_tokens': body.get('max_output_tokens'),
            'checkpoint_in_history': SUMMARY in history_text,
            'tool_result_in_history': any(isinstance(item, dict) and item.get('type') == 'function_call_output'
                and item.get('call_id') == CALL_ID and TOOL_RESULT['fixture_status'] in json.dumps(item.get('output'))
                for item in body.get('input', []))})
        serial = len(report['requests'])
        return httpx.Response(200, content=response_stream(serial,
            SUMMARY if kind == 'compaction' else 'Fixture normal response complete.',
            function_call=serial == 1, incomplete=terminal_incomplete and serial == 5),
            headers={'content-type': 'text/event-stream'})

    gateway = OpenRouterGateway('compaction-lifecycle-dummy-key',
        transport=httpx.MockTransport(provider),
        budget_check=lambda key: {'remaining_usd': 49}, expected_instructions=instructions,
        profile=model_profile)

    async def fixture_tool(request_id, method, params):
        if (method != 'item/tool/call' or params.get('threadId') != thread_id
                or params.get('tool') != 'chess_status' or params.get('arguments') != {}
                or params.get('namespace') is not None or params.get('callId') != CALL_ID
                or report['tool_calls'] or expect_limit_error):
            raise bridge.CodexError('Lifecycle fixture requested an unexpected host capability')
        report['tool_calls'].append('chess_status')
        await rpc.send({'id': request_id, 'result': {'success': True,
            'contentItems': [{'type': 'inputText', 'text': json.dumps(TOOL_RESULT)}]}})

    done = False
    expect_limit_error = False
    async def event(method, params):
        nonlocal done
        item = params.get('item', {})
        if method in ('item/started', 'item/completed') and item.get('type') == 'contextCompaction':
            report['compaction_events'].append(method)
        if method == 'turn/completed':
            status = params.get('turn', {}).get('status')
            report['turn_statuses'].append(status)
            if status != ('failed' if expect_limit_error else 'completed'):
                raise bridge.CodexError('Fixture model turn did not complete')
            done = True
            if status == 'completed':
                report['completed_turns'] += 1
        if method == 'error':
            if expect_limit_error and not params.get('willRetry', False):
                # Some audited CLIs rewrite a terminal SSE error as a generic
                # stream disconnect. Classification then comes from the
                # gateway's independently observed provider terminal event.
                report['cli_preserved_output_limit_code'] = 'chess_gateway_output_limit' in json.dumps(params)
                report['fatal_error_without_retry'] = True
                report['output_limit_error_observed'] = bool(gateway.evidence
                    and gateway.evidence[-1].get('incomplete_reason') == 'max_output_tokens'
                    and gateway.evidence[-1].get('stream_complete') is False)
                if not report['output_limit_error_observed']:
                    raise bridge.CodexError('Fixture action error lacks matching provider output-limit evidence')
            else:
                raise bridge.CodexError('Fixture CLI reported an unexpected action error or retry')

    try:
        async with gateway:
            profile = replace(model_profile, base_url=gateway.base_url,
                              env_key='CHESS_GATEWAY_TOKEN')
            (home / 'config.toml').write_text(bridge._config_text(profile.model, profile.reasoning, profile), encoding='utf-8')
            env = bridge._child_environment(root, home, include_key=False, env_key=profile.env_key)
            if any(name in env for name in ('OPENAI_API_KEY', 'OPENROUTER_API_KEY', 'CODEX_API_KEY')):
                raise bridge.CodexError('Provider credentials entered lifecycle fixture')
            env[profile.env_key] = gateway.token
            version = await bridge._spawn(str(codex), '--version', cwd=str(workspace), env=env,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, limit=4096)
            try:
                output, _ = await asyncio.wait_for(version.communicate(), 10)
                if version.returncode or output.decode().strip() != f'codex-cli {candidate_version}':
                    raise bridge.CodexError('Lifecycle fixture CLI version differs')
            finally:
                await bridge._terminate(version)
            thread_id = None
            for resumed in (False, True):
                process = await bridge._spawn(str(codex), 'app-server', '--stdio', '--strict-config',
                    cwd=str(workspace), env=env, stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, limit=bridge.MAX_RPC_BYTES)
                rpc = bridge._Rpc(process, event, fixture_tool)
                async with asyncio.timeout(30):
                    initialized = await rpc.request('initialize', {'clientInfo': {'name': 'compaction_lifecycle_audit', 'version': '0.1'},
                        'capabilities': {'experimentalApi': True}})
                    if Path(initialized.get('codexHome', '')).resolve() != home:
                        raise bridge.CodexError('Lifecycle fixture did not use its isolated home')
                    await rpc.send({'method': 'initialized', 'params': {}})
                    effective = (await rpc.request('config/read', {'includeLayers': False}))['config']
                    bridge._verify_effective_config(effective, profile.model, profile.reasoning, profile)
                    params = {'model': profile.model, 'modelProvider': profile.provider,
                        'approvalPolicy': 'never', 'approvalsReviewer': 'user', 'sandbox': 'read-only',
                        'cwd': str(workspace), 'runtimeWorkspaceRoots': [], 'baseInstructions': instructions,
                        'developerInstructions': 'Local mocked protocol audit; no real chess game or provider.'}
                    if resumed:
                        params.update(threadId=thread_id, excludeTurns=True)
                    else:
                        params.update(environments=[], dynamicTools=bridge.dynamic_tools(), ephemeral=False,
                                      allowProviderModelFallback=False)
                    started = await rpc.request('thread/resume' if resumed else 'thread/start', params)
                    for name, expected in {'model': profile.model, 'modelProvider': profile.provider,
                            'approvalPolicy': 'never', 'approvalsReviewer': 'user',
                            'runtimeWorkspaceRoots': [], 'activePermissionProfile': None, 'instructionSources': [],
                            'sandbox': {'type': 'readOnly', 'networkAccess': False}}.items():
                        if started.get(name) != expected:
                            raise bridge.CodexError('Lifecycle fixture thread boundaries differ')
                    if resumed:
                        if started['thread']['id'] != thread_id:
                            raise bridge.CodexError('Lifecycle fixture resumed another thread')
                        report['same_thread_resumed'] = True
                    else:
                        thread_id = started['thread']['id']
                        done = False
                        await rpc.request('turn/start', {'threadId': thread_id, 'model': profile.model,
                            'effort': profile.reasoning, 'approvalPolicy': 'never', 'approvalsReviewer': 'user',
                            'environments': [], 'runtimeWorkspaceRoots': [],
                            'sandboxPolicy': {'type': 'readOnly', 'networkAccess': False}, 'summary': 'none',
                            'input': [{'type': 'text', 'text': 'Call chess_status, then finish the local fixture response.'}]})
                        while not done:
                            await rpc.dispatch(await rpc.read())
                        done = False
                        await rpc.request('thread/compact/start', {'threadId': thread_id})
                        while not done:
                            await rpc.dispatch(await rpc.read())
                    done = False
                    expect_limit_error = resumed and terminal_incomplete
                    await rpc.request('turn/start', {'threadId': thread_id, 'model': profile.model,
                        'effort': profile.reasoning, 'approvalPolicy': 'never', 'approvalsReviewer': 'user',
                        'environments': [], 'runtimeWorkspaceRoots': [],
                        'sandboxPolicy': {'type': 'readOnly', 'networkAccess': False}, 'summary': 'none',
                        'input': [{'type': 'text', 'text': 'Continue the local fixture with a short text response.'}]})
                    while not done:
                        await rpc.dispatch(await rpc.read())
                await bridge._terminate(process)
                process = None
            report['success'] = (report['same_thread_resumed']
                and report['turn_statuses'] == ['completed', 'completed', 'completed',
                                               'failed' if terminal_incomplete else 'completed']
                and report['compaction_events'] == ['item/started', 'item/completed']
                and report['tool_calls'] == ['chess_status']
                and [row['kind'] for row in report['requests']] == ['chess', 'chess', 'compaction', 'chess', 'chess']
                and all(row['instructions_match'] and row['max_output_tokens'] == model_profile.max_output_tokens
                        and row['model'] == MODEL and row['reasoning'] == {'effort': model_profile.reasoning}
                        for row in report['requests'])
                and report['requests'][1]['tool_result_in_history']
                and all(row['checkpoint_in_history'] for row in report['requests'][3:])
                and (not terminal_incomplete or (report['output_limit_error_observed']
                                                and report['fatal_error_without_retry'])))
    except Exception as error:
        report['failure_type'] = type(error).__name__
        if isinstance(error, bridge.CodexError):
            report['failure'] = str(error)
    finally:
        if process:
            await bridge._terminate(process)
        report.update(gateway_request_count=gateway.request_count,
                      gateway_budget_check_count=gateway.budget_check_count,
                      gateway_rejections=gateway.rejections, gateway_evidence=gateway.evidence)
        report['gateway_profile_evidence_verified'] = (len(gateway.evidence) == 5
            and all(row.get('requested_reasoning') == model_profile.reasoning
                    and row.get('max_output_tokens') == model_profile.max_output_tokens
                    and row.get('instructions_verified') is True for row in gateway.evidence)
            and all(row.get('stream_complete') is True for row in gateway.evidence[:-1])
            and gateway.evidence[-1].get('stream_complete') is not terminal_incomplete)
        report['success'] = bool(report['success'] and gateway.request_count == 5 and gateway.budget_check_count == 5
                                 and report['gateway_profile_evidence_verified'])
        destination = root / 'audit.json'
        destination.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(report, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex', required=True)
    parser.add_argument('--candidate-version', required=True)
    parser.add_argument('--audit-dir', type=Path, required=True)
    parser.add_argument('--terminal-incomplete', action='store_true',
                        help='Require the resumed turn to fail explicitly on a mocked provider output limit')
    args = parser.parse_args()
    report = asyncio.run(audit(args.codex, args.candidate_version, args.audit_dir,
                               terminal_incomplete=args.terminal_incomplete))
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
