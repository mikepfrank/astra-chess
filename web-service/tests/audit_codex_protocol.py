"""No-key CLI startup audit. Never sends turn/start or calls a model/engine.

Run inside the deployment's final service namespace to verify strict config
and thread permissions. Code-mode prewarming remains disabled, so this cannot
replace the authenticated tool-execution and durable-resume smoke tests.
"""
import argparse
import asyncio
from collections import Counter
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from astra_web import codex_bridge as bridge


async def audit(codex_bin, audit_dir):
    base = Path(audit_dir).resolve()
    base.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='codex-protocol-', dir=base)).resolve()
    home = bridge._private_directory(root / 'codex-home', root)
    workspace = bridge._private_directory(root / 'workspace', root)
    for name in ('tmp', 'appdata'):
        bridge._private_directory(root / name, root)
    (home / 'config.toml').write_text(bridge._config_text('gpt-6-astra', 'ultra'), encoding='utf-8')
    env = bridge._child_environment(root, home, include_key=False)
    assert 'OPENAI_API_KEY' not in env and 'CODEX_API_KEY' not in env
    player = bridge.CodexPlayer(SimpleNamespace(codex_bin=codex_bin))
    version = await player._version_check(env, workspace)
    events = Counter()
    report = {'cli_version': version, 'audit_directory': str(root), 'credentials_inherited': False,
              'model_turn_started': False, 'dynamic_tool_count': len(bridge.dynamic_tools())}

    async def event(method, params):
        # Record method counts only, never arbitrary notification contents.
        events[method] += 1

    async def request(request_id, method, params):
        raise bridge.CodexError('A no-turn audit unexpectedly requested a host capability')

    with (root / 'startup-stderr.txt').open('wb') as errors:
        process = await bridge._spawn(str(codex_bin), 'app-server', '--stdio', '--strict-config',
            cwd=str(workspace), env=env, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=errors, limit=bridge.MAX_RPC_BYTES)
        rpc = bridge._Rpc(process, event, request)
        try:
            async with asyncio.timeout(30):
                initialized = await rpc.request('initialize', {
                    'clientInfo': {'name': 'astra_protocol_audit', 'version': '0.1.0'},
                    'capabilities': {'experimentalApi': True}})
                if Path(initialized.get('codexHome', '')).resolve() != home:
                    raise bridge.CodexError('The audit did not use its fresh isolated home')
                await rpc.send({'method': 'initialized', 'params': {}})
                config = (await rpc.request('config/read', {'includeLayers': False}))['config']
                bridge._verify_effective_config(config, 'gpt-6-astra', 'ultra')
                result = await rpc.request('thread/start', {
                    'model': 'gpt-6-astra', 'modelProvider': bridge.PROVIDER,
                    'approvalPolicy': 'never', 'approvalsReviewer': 'user', 'sandbox': 'read-only',
                    'cwd': str(workspace), 'runtimeWorkspaceRoots': [], 'environments': [],
                    'dynamicTools': bridge.dynamic_tools(), 'ephemeral': False,
                    'allowProviderModelFallback': False,
                    'baseInstructions': 'No-key protocol audit. No model turn will be started.',
                    'developerInstructions': 'Only explicitly registered chess tools are permitted.',
                    'config': {'model_reasoning_effort': 'ultra',
                               'model_context_window': bridge.MODEL_CONTEXT_WINDOW,
                               'model_auto_compact_token_limit': bridge.AUTO_COMPACT_TOKEN_LIMIT,
                               'model_auto_compact_token_limit_scope': 'total'}})
                expected = {'model': 'gpt-6-astra', 'modelProvider': bridge.PROVIDER,
                            'reasoningEffort': 'ultra', 'approvalPolicy': 'never',
                            'approvalsReviewer': 'user', 'runtimeWorkspaceRoots': [],
                            'activePermissionProfile': None, 'instructionSources': []}
                if any(result.get(key) != value for key, value in expected.items()):
                    raise bridge.CodexError('Thread permissions or model differ from the audited configuration')
                if result.get('sandbox') != {'type': 'readOnly', 'networkAccess': False}:
                    raise bridge.CodexError('The audit thread has an unexpected sandbox')
                report.update(strict_config_verified=True, thread_start_verified=True,
                              model='gpt-6-astra', reasoning='ultra', sandbox=result['sandbox'],
                              model_context_window=bridge.MODEL_CONTEXT_WINDOW,
                              auto_compact_token_limit=bridge.AUTO_COMPACT_TOKEN_LIMIT)
        finally:
            await bridge._terminate(process)
    report['event_counts'] = dict(events)
    (root / 'audit.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex', default=os.getenv('ASTRA_CODEX_BIN', 'codex'))
    parser.add_argument('--audit-dir', type=Path, required=True, help='Writable audit parent; each run creates a fresh private child')
    args = parser.parse_args()
    try:
        print(json.dumps(asyncio.run(audit(args.codex, args.audit_dir)), indent=2))
    except (bridge.CodexError, OSError, TimeoutError) as error:
        parser.exit(1, f'No-key Codex audit failed: {error}\n')


if __name__ == '__main__':
    main()
