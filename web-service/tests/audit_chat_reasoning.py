"""Actual Codex CLI: selectable moves and fixed High chat on one mocked thread.

No real credentials, provider calls, chess moves or player records are used.
Only structural evidence is reported; retained protocol text is synthetic.
"""
import argparse
import asyncio
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from astra_web import codex_bridge as bridge
from astra_web.config import Config
from astra_web.openrouter_gateway import OpenRouterGateway
from astra_web.player_profiles import new_player_binding
from tests.audit_reasoning_roundtrip import stream_response


async def audit(codex, output):
    output.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='chat-reasoning-', dir=output)).resolve()
    config = Config(data_dir=root, codex_bin=codex, model_profile='openrouter-glm', persona='arcturus')
    config.validate()
    binding = new_player_binding(config)
    original = copy.deepcopy(binding)
    move_policy = (bridge.PROMPT_ROOT / 'move-deliberation-policy.md').read_text(encoding='utf-8')
    assert move_policy.startswith('## Bounded initial deliberation')
    assert 'On your own move turns, strategize independently first, but not indefinitely.' in move_policy
    report = {'success': False, 'external_provider_contacted': False,
              'real_credentials_used': False, 'actions': [], 'requests': []}
    gateways = []
    active_kind = None
    active_effort = None

    class FixtureGateway(OpenRouterGateway):
        def __init__(self, key, **kwargs):
            assert key == 'synthetic-chat-reasoning-key'
            self.fixture_count = 0
            assert kwargs['profile'].reasoning == active_effort
            assert kwargs['expected_instructions'] == original['prompt']
            super().__init__(key, **kwargs, transport=httpx.MockTransport(self.upstream),
                             budget_check=lambda _: {'remaining_usd': 49})
            gateways.append(self)

        async def upstream(self, request):
            self.fixture_count += 1
            assert self.fixture_count <= 2
            payload = json.loads(request.content)
            assert payload['reasoning'] == {'effort': active_effort}
            assert payload['max_output_tokens'] == 32768
            assert payload['model'] == original['profile']['model']
            assert payload['instructions'] == original['prompt']
            assert {tool['name'] for tool in payload['tools']} == bridge.TOOL_NAMES
            items = payload.get('input', [])
            assert isinstance(items, list)
            developer_texts = []
            for item in items:
                if not isinstance(item, dict) or item.get('role') != 'developer':
                    continue
                content = item.get('content', [])
                if isinstance(content, str):
                    developer_texts.append(content)
                elif isinstance(content, list):
                    developer_texts.extend(part['text'] for part in content
                        if isinstance(part, dict) and isinstance(part.get('text'), str))
            assert any(move_policy in text for text in developer_texts), \
                'Move deliberation policy missing from provider developer input'
            report['requests'].append({'kind': active_kind, 'effort': active_effort,
                'max_output_tokens': payload['max_output_tokens'], 'tool_count': len(payload['tools']),
                'move_deliberation_policy_on_wire': True})
            return httpx.Response(200, headers={'content-type': 'text/event-stream'},
                content=stream_response(len(report['requests']), 'summary', self.fixture_count == 1))

    async def handler(name, args):
        if name == 'chess_status':
            return {'fixture': True, 'ply': 0, 'remaining_turn_seconds': 600,
                    'messages': [{'text': 'Synthetic opponent text cannot choose a reasoning level.'}]}
        if name == '_assistant_note':
            notes.append(args)
        else:
            assert name in {'_thread', '_usage', '_compaction'}
        return {}

    public = []
    notes = []
    async def emit(text):
        public.append(text)

    thread_id = None
    player = bridge.CodexPlayer(config)
    try:
        with patch.dict(os.environ, {'OPENROUTER_API_KEY': 'synthetic-chat-reasoning-key'}), \
                patch('astra_web.openrouter_setup.require_budget', return_value={'remaining_usd': 49}), \
                patch('astra_web.openrouter_gateway.OpenRouterGateway', FixtureGateway):
            for active_kind, preference, active_effort in [
                    ('move', 'max', 'max'), ('move', 'high', 'high'),
                    ('chat', 'max', 'high'), ('move', 'max', 'max')]:
                async with asyncio.timeout(40):
                    result = await player.run('synthetic-chat-policy', {'ply': 0, 'hard_response_seconds': 600},
                        handler, emit, thread_id, player_binding=binding, response_kind=active_kind,
                        move_reasoning=preference)
                if thread_id is not None:
                    assert result['thread_id'] == thread_id
                thread_id = result['thread_id']
                assert result['reasoning'] == active_effort
                state = json.loads((root / 'players/synthetic-chat-policy/bridge-state.json').read_text())
                assert state['player_profile'] == original['profile']
                assert state['runtime_reasoning_policy']['effort'] == active_effort
                assert state['runtime_reasoning_policy']['max_output_tokens'] == 32768
                assert state['runtime_context_policy']['compact_limit'] == 250000
                assert not player._processes and not player._active_games
                report['actions'].append({'kind': active_kind, 'effort': active_effort, 'move_preference': preference,
                    'same_thread': state['thread_id'] == thread_id, 'original_identity_preserved': True,
                    'process_reaped': True})
        assert binding == original
        assert not public and len(notes) == 4 and len(report['requests']) == 8
        assert all(gateway.request_count == 2 and gateway.budget_check_count == 2
                   and not gateway.rejections and all(row.get('stream_complete') for row in gateway.evidence)
                   for gateway in gateways)
        report.update(success=True, cli_version=state['cli_version'],
                      immutable_binding_preserved=True, completed_actions=4,
                      move_deliberation_policy_verified=True)
    finally:
        await player.close()
        (root / 'audit.json').write_text(json.dumps(report, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(audit(args.codex, args.output)), indent=2))


if __name__ == '__main__':
    main()
