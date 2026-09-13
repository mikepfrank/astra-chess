"""Real CLI, mocked provider: compact, continue, restart and resume one thread.

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


def response_stream(serial, text):
    response_id, item_id = f'resp-fixture-{serial}', f'msg-fixture-{serial}'
    item = {'id': item_id, 'type': 'message', 'role': 'assistant', 'status': 'completed',
            'content': [{'type': 'output_text', 'text': text, 'annotations': []}]}
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
    return ''.join('event: ' + event['type'] + '\ndata: ' + json.dumps(event) + '\n\n'
                   for event in events).encode() + b'data: [DONE]\n\n'


async def audit(codex, candidate_version, audit_dir):
    if candidate_version not in bridge.reviewed_versions('openrouter-glm'):
        raise bridge.CodexError('Lifecycle audit requires a reviewed exact CLI version')
    audit_dir = Path(audit_dir).resolve()
    audit_dir.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='compaction-lifecycle-', dir=audit_dir)).resolve()
    home = bridge._private_directory(root / 'codex-home', root)
    workspace = bridge._private_directory(root / 'workspace', root)
    for name in ('tmp', 'appdata'):
        bridge._private_directory(root / name, root)
    instructions = new_player_binding(Config(model_profile='openrouter-glm', persona='arcturus'))['prompt']
    report = {'candidate_version': candidate_version, 'audit_directory': str(root),
              'context_window': get_profile('openrouter-glm').context_window,
              'compact_limit': get_profile('openrouter-glm').compact_limit,
              'external_provider_contacted': False, 'real_credentials_inherited': False,
              'requests': [], 'compaction_events': [], 'completed_turns': 0,
              'same_thread_resumed': False, 'success': False}
    process = None
    async def provider(request):
        body = json.loads(request.content)
        tools = body.get('tools')
        kind = 'compaction' if tools == [] else 'chess'
        names = [tool.get('name') for tool in tools]
        if kind == 'chess' and (set(names) != bridge.TOOL_NAMES or len(names) != 7):
            raise bridge.CodexError('Lifecycle fixture received unexpected tool schemas')
        history_text = json.dumps(body.get('input', []))
        report['requests'].append({'kind': kind, 'tools': names,
            'instructions_match': body.get('instructions') == instructions,
            'instructions_sha256': hashlib.sha256(instructions.encode()).hexdigest(),
            'model': body.get('model'), 'reasoning': body.get('reasoning'),
            'max_output_tokens': body.get('max_output_tokens'),
            'checkpoint_in_history': SUMMARY in history_text})
        return httpx.Response(200, content=response_stream(len(report['requests']),
            SUMMARY if kind == 'compaction' else 'Fixture normal response complete.'),
            headers={'content-type': 'text/event-stream'})

    gateway = OpenRouterGateway('compaction-lifecycle-dummy-key',
        transport=httpx.MockTransport(provider),
        budget_check=lambda key: {'remaining_usd': 49}, expected_instructions=instructions)

    async def forbid_tool(request_id, method, params):
        raise bridge.CodexError('Text-only fixture unexpectedly requested a host capability')

    done = False
    async def event(method, params):
        nonlocal done
        item = params.get('item', {})
        if method in ('item/started', 'item/completed') and item.get('type') == 'contextCompaction':
            report['compaction_events'].append(method)
        if method == 'turn/completed':
            if params.get('turn', {}).get('status') != 'completed':
                raise bridge.CodexError('Fixture model turn did not complete')
            done = True
            report['completed_turns'] += 1
        if method == 'error' and not params.get('willRetry', False):
            raise bridge.CodexError('Fixture CLI reported an action error')

    try:
        async with gateway:
            profile = replace(get_profile('openrouter-glm'), base_url=gateway.base_url,
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
                rpc = bridge._Rpc(process, event, forbid_tool)
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
                        await rpc.request('thread/compact/start', {'threadId': thread_id})
                        while not done:
                            await rpc.dispatch(await rpc.read())
                    done = False
                    await rpc.request('turn/start', {'threadId': thread_id, 'model': profile.model,
                        'effort': profile.reasoning, 'approvalPolicy': 'never', 'approvalsReviewer': 'user',
                        'environments': [], 'runtimeWorkspaceRoots': [],
                        'sandboxPolicy': {'type': 'readOnly', 'networkAccess': False}, 'summary': 'none',
                        'input': [{'type': 'text', 'text': 'Continue the local fixture with a short text response.'}]})
                    while not done:
                        await rpc.dispatch(await rpc.read())
                await bridge._terminate(process)
                process = None
            report['success'] = (report['same_thread_resumed'] and report['completed_turns'] == 3
                and report['compaction_events'] == ['item/started', 'item/completed']
                and [row['kind'] for row in report['requests']] == ['compaction', 'chess', 'chess']
                and all(row['instructions_match'] and row['max_output_tokens'] == 8192
                        and row['model'] == MODEL and row['reasoning'] == {'effort': 'high'} for row in report['requests'])
                and all(row['checkpoint_in_history'] for row in report['requests'][1:]))
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
        report['success'] = bool(report['success'] and gateway.request_count == 3 and gateway.budget_check_count == 3)
        destination = root / 'audit.json'
        destination.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(report, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex', required=True)
    parser.add_argument('--candidate-version', required=True)
    parser.add_argument('--audit-dir', type=Path, required=True)
    args = parser.parse_args()
    report = asyncio.run(audit(args.codex, args.candidate_version, args.audit_dir))
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
