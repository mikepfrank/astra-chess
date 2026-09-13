"""Explicit no-key audit of one candidate CLI and experimental model profile.

This audit intentionally checks a version outside the production acceptance
set. It never changes that set, sends a model turn, or inherits credentials.
Passing verifies startup configuration and thread boundaries only; it does not
establish provider compatibility, model execution, tool use or durable resume.
"""
import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from astra_web import codex_bridge as bridge
from astra_web.player_profiles import get_profile


CANDIDATE_VERSION = '0.154.0-alpha.6.2'
ALLOWED_METHODS = frozenset({'initialize', 'initialized', 'config/read', 'thread/start'})


class NoTurnRpc(bridge._Rpc):
    """Keep the no-model boundary explicit even if this script is extended."""
    async def send(self, payload):
        if payload.get('method') not in ALLOWED_METHODS:
            raise bridge.CodexError('The profile audit only permits no-turn startup methods')
        await super().send(payload)


async def audit(codex_bin, audit_dir, profile_name, candidate_version):
    if candidate_version != CANDIDATE_VERSION or profile_name != 'openrouter-glm':
        raise bridge.CodexError('This audit requires its exact candidate version and experimental profile')
    profile = get_profile(profile_name)
    if profile.code_mode:
        raise bridge.CodexError('This audit is restricted to direct function tools with code mode disabled')
    base = Path(audit_dir).resolve()
    base.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='model-profile-', dir=base)).resolve()
    home = bridge._private_directory(root / 'codex-home', root)
    workspace = bridge._private_directory(root / 'workspace', root)
    for name in ('tmp', 'appdata'):
        bridge._private_directory(root / name, root)
    binary = Path(codex_bin).resolve(strict=True)
    events = Counter()
    report = {
        'audited_at_utc': datetime.now(timezone.utc).isoformat(),
        'audit_directory': str(root), 'cli_binary': str(binary),
        'candidate_version': candidate_version, 'profile': profile.name,
        'credentials_inherited': False, 'model_turn_started': False,
        'production_version_gate_modified': False, 'passed': False,
        'strict_config_verified': False, 'thread_start_verified': False,
        'dynamic_tool_count': len(bridge.dynamic_tools()),
        'scope': 'No-key startup configuration and thread permissions only',
    }
    stage = 'configuration'
    try:
        with binary.open('rb') as source:
            report['cli_sha256'] = hashlib.file_digest(source, 'sha256').hexdigest()
        (home / 'config.toml').write_text(
            bridge._config_text(profile.model, profile.reasoning, profile=profile), encoding='utf-8')
        env = bridge._child_environment(root, home, include_key=False, env_key=profile.env_key)
        if any(key in env for key in ('OPENAI_API_KEY', 'CODEX_API_KEY', 'OPENROUTER_API_KEY', profile.env_key)):
            raise bridge.CodexError('A credential entered the no-key audit environment')
        stage = 'exact_candidate_version'
        process = await bridge._spawn(str(binary), '--version', env=env, cwd=str(workspace),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, limit=4096)
        try:
            output, _ = await asyncio.wait_for(process.communicate(), 10)
            if process.returncode != 0 or output.decode('utf-8').strip() != f'codex-cli {candidate_version}':
                raise bridge.CodexError('The installed CLI does not match the explicitly requested candidate version')
            report['cli_version'] = candidate_version
        finally:
            await bridge._terminate(process)

        async def event(method, params):
            events[method] += 1
            if method.startswith('turn/') or method == 'model/rerouted':
                raise bridge.CodexError('The no-turn profile audit received an unexpected model lifecycle event')

        async def request(request_id, method, params):
            raise bridge.CodexError('The no-turn profile audit unexpectedly requested a host capability')

        stage = 'initialize'
        with (root / 'startup-stderr.txt').open('wb') as errors:
            process = await bridge._spawn(str(binary), 'app-server', '--stdio', '--strict-config',
                cwd=str(workspace), env=env, stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=errors, limit=bridge.MAX_RPC_BYTES)
            rpc = NoTurnRpc(process, event, request)
            try:
                async with asyncio.timeout(30):
                    initialized = await rpc.request('initialize', {
                        'clientInfo': {'name': 'chess_model_profile_audit', 'version': '0.1.0'},
                        'capabilities': {'experimentalApi': True}})
                    if Path(initialized.get('codexHome', '')).resolve() != home:
                        raise bridge.CodexError('The profile audit did not use its isolated home')
                    await rpc.send({'method': 'initialized', 'params': {}})
                    stage = 'config_read'
                    config = (await rpc.request('config/read', {'includeLayers': False}))['config']
                    # Whitelisted configuration only; never persist arbitrary RPC output.
                    report['effective_config'] = {key: config.get(key) for key in (
                        'model', 'model_provider', 'model_reasoning_effort',
                        'model_context_window', 'model_auto_compact_token_limit',
                        'model_auto_compact_token_limit_scope', 'approval_policy',
                        'sandbox_mode', 'web_search')}
                    providers = config.get('model_providers')
                    report['provider_config_type'] = type(providers).__name__
                    provider = providers.get(profile.provider) if isinstance(providers, dict) else None
                    report['selected_provider_type'] = type(provider).__name__
                    if isinstance(provider, dict):
                        report['effective_provider'] = {key: provider.get(key) for key in (
                            'base_url', 'env_key', 'wire_api', 'requires_openai_auth',
                            'request_max_retries', 'stream_max_retries',
                            'supports_standalone_web_search', 'supports_websockets')}
                    bridge._verify_effective_config(config, profile.model, profile.reasoning, profile=profile)
                    report['strict_config_verified'] = True
                    report['disabled_features_verified'] = list(bridge.DISABLED_FEATURES)
                    report['code_mode'] = profile.code_mode
                    stage = 'thread_start'
                    result = await rpc.request('thread/start', {
                        'model': profile.model, 'modelProvider': profile.provider,
                        'approvalPolicy': 'never', 'approvalsReviewer': 'user', 'sandbox': 'read-only',
                        'cwd': str(workspace), 'runtimeWorkspaceRoots': [], 'environments': [],
                        'dynamicTools': bridge.dynamic_tools(), 'ephemeral': False,
                        'allowProviderModelFallback': False,
                        'baseInstructions': 'No-key profile audit. No model turn will be started.',
                        'developerInstructions': 'Only registered chess tools are permitted.',
                        'config': {'model_reasoning_effort': profile.reasoning,
                                   'model_context_window': profile.context_window,
                                   'model_auto_compact_token_limit': profile.compact_limit,
                                   'model_auto_compact_token_limit_scope': 'total'}})
                    expected = {'model': profile.model, 'modelProvider': profile.provider,
                        'reasoningEffort': profile.reasoning, 'approvalPolicy': 'never',
                        'approvalsReviewer': 'user', 'runtimeWorkspaceRoots': [],
                        'activePermissionProfile': None, 'instructionSources': [],
                        'sandbox': {'type': 'readOnly', 'networkAccess': False}}
                    report['observed_thread'] = {key: result.get(key) for key in expected}
                    if any(result.get(key) != value for key, value in expected.items()):
                        raise bridge.CodexError('Profile thread model or permissions differ from the requested boundaries')
                    report.update(thread_start_verified=True, effective_thread=expected, passed=True)
                    stage = 'complete'
            finally:
                await bridge._terminate(process)
    except Exception as error:
        # Exception text can contain paths, provider output or configuration.
        report['failure_type'] = type(error).__name__
        raise
    finally:
        report['stage'] = stage
        report['event_counts'] = dict(events)
        (root / 'audit.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(report, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex', required=True, help='Absolute path to the candidate CLI executable')
    parser.add_argument('--candidate-version', required=True, choices=[CANDIDATE_VERSION])
    parser.add_argument('--profile', required=True, choices=['openrouter-glm'])
    parser.add_argument('--audit-dir', type=Path, required=True)
    args = parser.parse_args()
    try:
        asyncio.run(audit(args.codex, args.audit_dir, args.profile, args.candidate_version))
    except (bridge.CodexError, OSError, ValueError, KeyError, TimeoutError) as error:
        parser.exit(1, f'No-key model profile audit failed ({type(error).__name__}); inspect the sanitized audit report.\n')


if __name__ == '__main__':
    main()
