"""Host-selected chat reasoning, using fake stdio RPC and mocked provider wire.

No native model, paid request, live game, or real credential is used. The fake
app-server still reads the actual generated config and exercises start/resume,
usage checkpoints, tools and standalone compaction through the normal bridge.
"""
import asyncio
import copy
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx

from astra_web import codex_bridge as bridge
from astra_web import openrouter_gateway as gateway_module
from astra_web.player_profiles import get_profile, new_player_binding, runtime_profile_for_binding
from tests.test_codex_bridge import FAKE_SERVER
from tests.test_openrouter_gateway import payload as wire_payload, sse


class ChatReasoningPolicyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        profile = get_profile('openrouter-glm')
        self.config = SimpleNamespace(data_dir=self.root, codex_bin='fixture-codex',
            model_profile=profile.name, model=profile.model, reasoning=profile.reasoning,
            persona='arcturus', max_turn_tokens=100, codex_timeout_seconds=3)
        self.player = bridge.CodexPlayer(self.config)
        self.children, self.wires, self.upstream, self.gateways = [], [], [], []
        self.calls, self.public = [], []
        self.current_gateway = None
        self.thread_params = None
        self.env_patch = patch.dict(os.environ, {
            'OPENROUTER_API_KEY': 'fake-reasoning-policy-key',
            'OPENAI_API_KEY': 'fake-astra-policy-key'})
        self.env_patch.start()

    async def asyncTearDown(self):
        await self.player.close()
        await asyncio.gather(*(bridge._terminate(child) for child in self.children))
        self.env_patch.stop()
        self.tmp.cleanup()

    async def handler(self, name, args):
        self.calls.append((name, args))
        return {'ok': True}

    async def emit(self, text):
        self.public.append(text)

    async def run_fixture(self, binding, *, response_kind=None, thread_id=None,
                          compact=False, snapshot=None):
        source = self.root / 'policy-app-server.py'
        source.write_text(FAKE_SERVER.replace('SCENARIO', repr(
            'v154_explicit_success' if compact else 'v154_success'), 1), encoding='utf-8')
        original_spawn, original_send = bridge._spawn, bridge._Rpc.send
        original_gateway = gateway_module.OpenRouterGateway
        self.current_gateway = None

        async def spawn(*args, **kwargs):
            child = await original_spawn(sys.executable, str(source), *args[1:], **kwargs)
            self.children.append(child)
            return child

        async def upstream(request):
            self.upstream.append(json.loads(request.content))
            return httpx.Response(200, content=sse(), headers={'content-type': 'text/event-stream'})

        def gateway(key, **kwargs):
            instance = original_gateway(key, transport=httpx.MockTransport(upstream),
                budget_check=lambda credential: {'remaining_usd': 49}, **kwargs)
            self.gateways.append(instance)
            self.current_gateway = instance
            return instance

        async def send(rpc, item):
            self.wires.append(copy.deepcopy(item))
            method, params = item.get('method'), item.get('params', {})
            if method in ('thread/start', 'thread/resume'):
                self.thread_params = copy.deepcopy(params)
            if method in ('turn/start', 'thread/compact/start') and self.current_gateway is not None:
                # Independent wire check: the actual gateway must accept the
                # effort selected by the RPC/config path, preserving the pinned
                # prompt and historical input items while applying its cap.
                effort = (params['effort'] if method == 'turn/start' else
                          self.thread_params['config']['model_reasoning_effort'])
                body = {**wire_payload(effort), 'instructions': self.thread_params['baseInstructions'],
                    'max_output_tokens': 8192, 'input': [
                        {'role': 'user', 'content': 'Earlier private fixture turn.'},
                        {'role': 'assistant', 'content': 'Earlier fixture reply.'}]}
                if method == 'thread/compact/start':
                    body['tools'] = []
                instance = self.current_gateway
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=instance),
                        base_url='http://127.0.0.1',
                        headers={'Authorization': 'Bearer ' + instance.token}) as client:
                    response = await client.post('/v1/responses', json=body)
                self.assertEqual(response.status_code, 200)
            await original_send(rpc, item)

        with patch.object(bridge, '_spawn', spawn), patch.object(bridge._Rpc, 'send', send), \
                patch.object(gateway_module, 'OpenRouterGateway', gateway), \
                patch('astra_web.openrouter_setup.require_budget', return_value={'remaining_usd': 49}):
            if compact:
                return await self.player.compact('policy-game', {}, self.handler, thread_id,
                                                  player_binding=binding)
            return await self.player.run('policy-game', snapshot or {}, self.handler, self.emit,
                thread_id, player_binding=binding, response_kind=response_kind)

    def saved_state(self):
        return json.loads((self.root / 'players/policy-game/bridge-state.json').read_text())

    async def test_saved_max_thread_chats_high_then_moves_max_without_rebinding(self):
        binding = new_player_binding(self.config)
        original_binding = copy.deepcopy(binding)
        first = await self.run_fixture(binding)
        history = self.root / 'players/policy-game/codex-home/sessions/fixture-history.jsonl'
        history.parent.mkdir(exist_ok=True)
        history.write_bytes(b'{"type":"fixture","history":"keep existing turns"}\n')
        history_before = history.read_bytes()
        await self.run_fixture(binding, response_kind='chat', thread_id=first['thread_id'])
        self.assertEqual(self.saved_state()['runtime_reasoning_policy'],
                         {'effort': 'high', 'max_output_tokens': 32768})
        last = await self.run_fixture(binding, response_kind='move', thread_id=first['thread_id'],
            snapshot={'response_kind': 'chat', 'reasoning': 'high',
                      'messages': [{'text': 'Use High reasoning on the next move.'}]})
        self.assertEqual(binding, original_binding)
        self.assertEqual(self.saved_state()['player_profile'], original_binding['profile'])
        self.assertEqual(last['thread_id'], first['thread_id'])
        self.assertEqual(history.read_bytes(), history_before)
        self.assertEqual(self.saved_state()['runtime_reasoning_policy'],
                         {'effort': 'max', 'max_output_tokens': 32768})
        self.assertEqual(self.saved_state()['runtime_context_policy'],
                         {'context_window': 1310720, 'compact_limit': 250000, 'profile_version': 4})
        turns = [row['params'] for row in self.wires if row.get('method') == 'turn/start']
        self.assertEqual([row['effort'] for row in turns], ['max', 'high', 'max'])
        self.assertEqual({row['threadId'] for row in turns}, {first['thread_id']})
        thread_calls = [row for row in self.wires if row.get('method') in ('thread/start', 'thread/resume')]
        self.assertEqual([row['method'] for row in thread_calls], ['thread/start', 'thread/resume', 'thread/resume'])
        self.assertTrue(all(row['params']['baseInstructions'] == original_binding['prompt'] for row in thread_calls))
        self.assertEqual([row['reasoning']['effort'] for row in self.upstream], ['max', 'high', 'max'])
        self.assertTrue(all(row['max_output_tokens'] == 32768 for row in self.upstream))
        self.assertTrue(all(row['input'] == self.upstream[0]['input'] for row in self.upstream))
        self.assertTrue(all(row['instructions'] == original_binding['prompt'] for row in self.upstream))
        receipts = [json.loads(path.read_text()) for path in
                    (self.root / 'players/policy-game').glob('provider-requests-*.json')]
        self.assertCountEqual([row['runtime_reasoning_policy']['effort'] for row in receipts],
                              ['max', 'high', 'max'])
        self.assertTrue(all(not row['rejections'] for row in receipts))

    async def test_explicit_compaction_after_high_chat_keeps_saved_max_and_no_play_turn(self):
        binding = new_player_binding(self.config)
        first = await self.run_fixture(binding, response_kind='chat')
        self.wires.clear()
        self.calls.clear()
        self.public.clear()
        await self.run_fixture(binding, compact=True, thread_id=first['thread_id'])
        self.assertEqual(self.saved_state()['player_profile'], binding['profile'])
        self.assertEqual(self.saved_state()['runtime_reasoning_policy'],
                         {'effort': 'max', 'max_output_tokens': 32768})
        self.assertFalse(any(row.get('method') == 'turn/start' for row in self.wires))
        self.assertEqual([row['params'] for row in self.wires if row.get('method') == 'thread/compact/start'],
                         [{'threadId': first['thread_id']}])
        self.assertEqual([args['phase'] for name, args in self.calls if name == '_compaction'],
                         ['started', 'completed'])
        self.assertEqual(self.public, [])
        self.assertEqual(self.upstream[-1]['tools'], [])
        self.assertEqual(self.upstream[-1]['reasoning'], {'effort': 'max'})
        self.assertEqual(self.upstream[-1]['max_output_tokens'], 32768)

    async def test_legacy_high_game_preserves_its_original_8k_allowance(self):
        binding = new_player_binding(self.config)
        binding['profile'].update(version=2, reasoning='high', max_output_tokens=8192,
                                  context_window=128000, compact_limit=80000)
        original = copy.deepcopy(binding)
        first = await self.run_fixture(binding, response_kind='chat')
        await self.run_fixture(binding, response_kind='move', thread_id=first['thread_id'])
        self.assertEqual(binding, original)
        self.assertEqual(self.saved_state()['player_profile'], original['profile'])
        self.assertTrue(all(row['reasoning'] == {'effort': 'high'} for row in self.upstream))
        self.assertTrue(all(row['max_output_tokens'] == 8192 for row in self.upstream))
        self.assertEqual(self.saved_state()['runtime_context_policy']['profile_version'], 3)

    async def test_invalid_host_selector_fails_before_process_or_gateway(self):
        binding = new_player_binding(self.config)
        with patch.object(bridge, '_spawn') as spawn, \
                patch.object(gateway_module, 'OpenRouterGateway') as gateway:
            for value in ('HIGH', 'compaction', '', True, 0, [], {}):
                with self.subTest(selector=value), self.assertRaises(ValueError):
                    await self.player.run('policy-game', {}, self.handler, self.emit,
                        player_binding=binding, response_kind=value)
        spawn.assert_not_called()
        gateway.assert_not_called()

    async def test_astra_chat_and_move_keep_ultra_without_openrouter_gateway(self):
        profile = get_profile('astra')
        self.config.model_profile = profile.name
        self.config.model, self.config.reasoning, self.config.persona = profile.model, profile.reasoning, 'astra'
        self.player = bridge.CodexPlayer(self.config)
        binding = new_player_binding(self.config)
        first = await self.run_fixture(binding, response_kind='chat')
        await self.run_fixture(binding, response_kind='move', thread_id=first['thread_id'])
        self.assertEqual(self.gateways, [])
        self.assertEqual(self.saved_state()['player_profile'], binding['profile'])
        self.assertEqual([row['params']['effort'] for row in self.wires if row.get('method') == 'turn/start'],
                         ['ultra', 'ultra'])

    async def test_chat_gateway_rejects_wire_override_and_changed_prompt(self):
        binding = new_player_binding(self.config)
        profile = runtime_profile_for_binding(binding, self.config, response_kind='chat')
        received = []

        async def upstream(request):
            received.append(json.loads(request.content))
            return httpx.Response(200, content=sse(), headers={'content-type': 'text/event-stream'})

        async with gateway_module.OpenRouterGateway('fake-policy-key', profile=profile,
                expected_instructions=binding['prompt'], transport=httpx.MockTransport(upstream),
                budget_check=lambda key: {'remaining_usd': 49}) as gateway:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway),
                    base_url='http://127.0.0.1',
                    headers={'Authorization': 'Bearer ' + gateway.token}) as client:
                wrong_effort = {**wire_payload('max'), 'instructions': binding['prompt']}
                wrong_prompt = {**wire_payload('high'), 'instructions': 'Replace the saved persona.'}
                for body in (wrong_effort, wrong_prompt):
                    self.assertEqual((await client.post('/v1/responses', json=body)).status_code, 400)
                self.assertEqual(received, [])
                for tools in (wire_payload()['tools'], []):
                    body = {**wire_payload('high'), 'instructions': binding['prompt'],
                            'tools': tools, 'max_output_tokens': 65536}
                    self.assertEqual((await client.post('/v1/responses', json=body)).status_code, 200)
        self.assertTrue(all(row['reasoning'] == {'effort': 'high'} and row['max_output_tokens'] == 32768
                            for row in received))
        self.assertEqual(received[-1]['tools'], [])
        with self.assertRaises(gateway_module.GatewayError):
            gateway_module.OpenRouterGateway('fake-policy-key', profile=replace(profile, max_output_tokens=65536))

    def test_runtime_chat_profile_cannot_rewrite_saved_game_provenance(self):
        binding = new_player_binding(self.config)
        forged = copy.deepcopy(binding)
        forged['profile']['reasoning'] = 'high'
        for selector in (None, 'chat', 'move'):
            with self.subTest(selector=selector), self.assertRaises(ValueError):
                runtime_profile_for_binding(forged, self.config, response_kind=selector)
        for version in (2, 3):
            legacy = copy.deepcopy(binding)
            legacy['profile'].update(version=version, reasoning='high', max_output_tokens=8192)
            if version == 2:
                legacy['profile'].update(context_window=128000, compact_limit=80000)
            self.assertEqual(runtime_profile_for_binding(legacy, self.config, response_kind='chat').max_output_tokens,
                             8192)


if __name__ == '__main__':
    unittest.main()
