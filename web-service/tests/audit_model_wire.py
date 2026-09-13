"""Capture a candidate Codex Responses request against a loopback-only fixture.

No provider is contacted. A fixed dummy key is supplied only to the local HTTP
fixture. This proves the emitted request shape, not model/provider behavior.
"""
import argparse
import asyncio
from dataclasses import replace
import json
import hashlib
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from astra_web import codex_bridge as bridge
from astra_web.player_profiles import get_profile
from astra_web.player_profiles import new_player_binding
from astra_web.config import Config
from audit_model_profile import CANDIDATE_VERSION


async def audit(codex_bin, audit_dir, catalog=None, restrict_builtins=False, through_gateway=False,
                candidate_version=CANDIDATE_VERSION):
    if candidate_version not in bridge.reviewed_versions('openrouter-glm'):
        raise bridge.CodexError('Wire audit requires an explicitly reviewed candidate version')
    instructions = new_player_binding(Config(model_profile='openrouter-glm'))['prompt']
    base = Path(audit_dir).resolve()
    base.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='model-wire-', dir=base)).resolve()
    home = bridge._private_directory(root / 'codex-home', root)
    workspace = bridge._private_directory(root / 'workspace', root)
    for name in ('tmp', 'appdata'):
        bridge._private_directory(root / name, root)
    captured = asyncio.Event()
    report = {'audit_directory': str(root), 'external_provider_contacted': False,
              'real_credentials_inherited': False, 'candidate_version': candidate_version,
              'catalog_configured': catalog is not None, 'request_captured': False,
              'restrict_builtins_probe': restrict_builtins, 'through_gateway': through_gateway}

    def record_request(request, path, authorization):
        # Persist only protocol metadata, never headers or full input text.
        tools = request.get('tools', [])
        canonical = {tool['name']: tool['inputSchema'] for tool in bridge.dynamic_tools()}
        def schema_diff(expected, actual, path=''):
            if isinstance(expected, dict) and isinstance(actual, dict):
                return [difference for key in sorted(expected.keys() | actual.keys())
                    for difference in schema_diff(expected.get(key), actual.get(key), path + '/' + key)]
            if expected != actual:
                return [{'path': path, 'expected': expected, 'actual': actual}]
            return []
        report.update(request_captured=True, request_path=path,
            instructions_match=request.get('instructions') == instructions,
            instructions_sha256=hashlib.sha256(instructions.encode('utf-8')).hexdigest(),
            requested_model=request.get('model'), reasoning=request.get('reasoning'),
            stream=request.get('stream'), max_output_tokens=request.get('max_output_tokens'),
            tool_types=[tool.get('type') for tool in tools], tool_names=[tool.get('name') for tool in tools],
            extra_tool_structure=[{'name': tool.get('name'), 'type': tool.get('type'),
                'nested_tools': [{'name': nested.get('name'), 'type': nested.get('type')}
                                 for nested in tool.get('tools', [])]}
                for tool in tools if tool.get('name') not in bridge.TOOL_NAMES],
            canonical_schemas_match={tool['name']: tool.get('parameters') == canonical[tool['name']]
                                     for tool in tools if tool.get('name') in canonical},
            canonical_schema_differences={tool['name']: schema_diff(canonical[tool['name']], tool.get('parameters'))
                                         for tool in tools if tool.get('name') in canonical},
            request_keys=sorted(request), dummy_auth_verified=(
                authorization == 'Bearer local-wire-audit-placeholder'))

    async def serve(reader, writer):
        try:
            header = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 10)
            lines = header.decode('ascii').split('\r\n')
            headers = dict(line.split(':', 1) for line in lines[1:] if ':' in line)
            headers = {key.lower(): value.strip() for key, value in headers.items()}
            size = int(headers.get('content-length', '0'))
            if not 0 < size <= bridge.MAX_RPC_BYTES:
                raise ValueError('Unsupported local fixture body size')
            request = json.loads(await asyncio.wait_for(reader.readexactly(size), 10))
            record_request(request, lines[0].split()[1], headers.get('authorization'))
        except Exception as error:
            report['fixture_failure_type'] = type(error).__name__
        finally:
            body = b'{"error":{"message":"Local audit captured request; no inference occurs.","type":"audit_fixture"}}'
            writer.write(b'HTTP/1.1 400 Bad Request\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: '
                         + str(len(body)).encode('ascii') + b'\r\n\r\n' + body)
            await writer.drain()
            writer.close()
            await writer.wait_closed()
            captured.set()

    server = await asyncio.start_server(serve, host='127.0.0.1', port=0, limit=bridge.MAX_RPC_BYTES)
    port = server.sockets[0].getsockname()[1]
    profile = replace(get_profile('openrouter-glm'), base_url=f'http://127.0.0.1:{port}/v1',
                      env_key='LOCAL_WIRE_AUDIT_KEY')
    gateway = None
    if through_gateway:
        import httpx
        from astra_web.openrouter_gateway import OpenRouterGateway

        async def mock_upstream(request):
            record_request(json.loads(request.content), request.url.path, request.headers.get('authorization'))
            captured.set()
            return httpx.Response(400, json={'error': {'type': 'audit_fixture', 'message': 'No inference occurs.'}})

        gateway = OpenRouterGateway('local-wire-audit-placeholder',
            transport=httpx.MockTransport(mock_upstream), budget_check=lambda key: {'remaining_usd': 49},
            expected_instructions=instructions)
        await gateway.__aenter__()
        profile = replace(profile, base_url=gateway.base_url, env_key='CHESS_GATEWAY_TOKEN')
    config = bridge._config_text(profile.model, profile.reasoning, profile=profile)
    if restrict_builtins:
        # These names were observed in this exact candidate's features list.
        # The resulting wire audit decides whether the switches remove tools.
        probe_flags = ('collaboration_modes', 'default_mode_request_user_input', 'skill_mcp_dependency_install')
        report['probe_disabled_features'] = list(probe_flags)
        config = config.replace('[apps._default]',
            ''.join(f'{name} = false\n' for name in probe_flags) + '[apps._default]')
    if catalog:
        config = 'model_catalog_json = ' + json.dumps(str(Path(catalog).resolve())) + '\n' + config
    (home / 'config.toml').write_text(config, encoding='utf-8')
    env = bridge._child_environment(root, home, include_key=False, env_key=profile.env_key)
    if any(key in env for key in ('OPENAI_API_KEY', 'OPENROUTER_API_KEY', 'CODEX_API_KEY')):
        raise bridge.CodexError('Real credential entered the local wire audit')
    env[profile.env_key] = gateway.token if gateway else 'local-wire-audit-placeholder'
    process = None
    stage = 'candidate_version'
    try:
        version_process = await bridge._spawn(str(codex_bin), '--version', env=env, cwd=str(workspace),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, limit=4096)
        try:
            output, _ = await asyncio.wait_for(version_process.communicate(), 10)
            if version_process.returncode != 0 or output.decode('utf-8').strip() != f'codex-cli {candidate_version}':
                raise bridge.CodexError('Local wire audit requires its exact candidate CLI version')
        finally:
            await bridge._terminate(version_process)

        async def event(method, params):
            pass

        async def request(request_id, method, params):
            raise bridge.CodexError('Local wire fixture must not invoke a host tool')

        with (root / 'startup-stderr.txt').open('wb') as errors:
            process = await bridge._spawn(str(codex_bin), 'app-server', '--stdio', '--strict-config',
                cwd=str(workspace), env=env, stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=errors, limit=bridge.MAX_RPC_BYTES)
            rpc = bridge._Rpc(process, event, request)
            async with asyncio.timeout(30):
                stage = 'initialize'
                initialized = await rpc.request('initialize', {
                    'clientInfo': {'name': 'chess_local_wire_audit', 'version': '0.1.0'},
                    'capabilities': {'experimentalApi': True}})
                if Path(initialized.get('codexHome', '')).resolve() != home:
                    raise bridge.CodexError('Local wire audit did not use its isolated home')
                await rpc.send({'method': 'initialized', 'params': {}})
                stage = 'config_read'
                effective = (await rpc.request('config/read', {'includeLayers': False}))['config']
                bridge._verify_effective_config(effective, profile.model, profile.reasoning, profile=profile)
                if restrict_builtins:
                    report['effective_probe_features'] = {
                        name: effective.get('features', {}).get(name) for name in probe_flags}
                stage = 'thread_start'
                response = await rpc.request('thread/start', {
                    'model': profile.model, 'modelProvider': profile.provider,
                    'approvalPolicy': 'never', 'approvalsReviewer': 'user', 'sandbox': 'read-only',
                    'cwd': str(workspace), 'runtimeWorkspaceRoots': [], 'environments': [],
                    **({'selectedCapabilityRoots': []} if restrict_builtins else {}),
                    'dynamicTools': bridge.dynamic_tools(), 'ephemeral': False,
                    'allowProviderModelFallback': False,
                    'baseInstructions': instructions,
                    'developerInstructions': 'This fixture has no external model or credentials.'})
                expected = {'model': profile.model, 'modelProvider': profile.provider,
                    'approvalPolicy': 'never', 'approvalsReviewer': 'user',
                    'runtimeWorkspaceRoots': [], 'activePermissionProfile': None,
                    'instructionSources': [], 'sandbox': {'type': 'readOnly', 'networkAccess': False}}
                if any(response.get(key) != value for key, value in expected.items()):
                    raise bridge.CodexError('Local wire fixture thread boundaries differ')
                stage = 'local_turn_start'
                await rpc.request('turn/start', {'threadId': response['thread']['id'],
                    'model': profile.model, 'effort': profile.reasoning,
                    'approvalPolicy': 'never', 'approvalsReviewer': 'user',
                    'environments': [], 'runtimeWorkspaceRoots': [],
                    'sandboxPolicy': {'type': 'readOnly', 'networkAccess': False}, 'summary': 'none',
                    'input': [{'type': 'text', 'text': 'Call chess_status.'}]})
                await captured.wait()
                report['seven_chess_tools_only'] = (set(report.get('tool_names', [])) == bridge.TOOL_NAMES
                    and len(report.get('tool_names', [])) == len(bridge.TOOL_NAMES))
                if not report.get('instructions_match'):
                    raise bridge.CodexError('The provider request omitted or changed its pinned instructions')
                stage = 'complete'
    except Exception as error:
        report['failure_type'] = type(error).__name__
        raise
    finally:
        if process:
            await bridge._terminate(process)
        server.close()
        await server.wait_closed()
        if gateway:
            await gateway.close()
            report['gateway_request_count'] = gateway.request_count
            report['gateway_budget_check_count'] = gateway.budget_check_count
            report['gateway_evidence'] = gateway.evidence
            report['gateway_rejections'] = gateway.rejections
        report['stage'] = stage
        (root / 'audit.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(report, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex', required=True)
    parser.add_argument('--candidate-version', required=True, choices=sorted(bridge.reviewed_versions('openrouter-glm')))
    parser.add_argument('--audit-dir', type=Path, required=True)
    parser.add_argument('--catalog', type=Path)
    parser.add_argument('--restrict-builtins', action='store_true')
    parser.add_argument('--through-gateway', action='store_true', help='Exercise the real filter against mocked upstream inference')
    args = parser.parse_args()
    try:
        asyncio.run(audit(args.codex, args.audit_dir, args.catalog, args.restrict_builtins, args.through_gateway,
                          args.candidate_version))
    except (bridge.CodexError, OSError, ValueError, KeyError, TimeoutError) as error:
        parser.exit(1, f'Local model wire audit failed ({type(error).__name__}); inspect sanitized report.\n')


if __name__ == '__main__':
    main()
