"""Loopback gateway tests with mocked inference and budget verification."""
import asyncio
from dataclasses import replace
import json
import unittest

import httpx

from astra_web.codex_bridge import dynamic_tools, TOOL_NAMES
from astra_web.openrouter_gateway import (OpenRouterGateway, MODEL, UPSTREAM_URL,
    MAX_REQUEST_BYTES, MAX_SSE_EVENT_BYTES, MAX_OUTPUT_TOKENS, COMMENT_REMINDER,
    GatewayError, _codex_wire_schema)
from astra_web.openrouter_setup import OpenRouterSetupError
from astra_web.player_profiles import get_profile


KEY = 'unit-test-private-openrouter-key'


def payload(effort='max'):
    functions = [{'type': 'function', 'name': item['name'], 'description': item['description'],
                  'parameters': item['inputSchema'], 'strict': False} for item in dynamic_tools()]
    return {'model': MODEL, 'stream': True, 'input': [{'role': 'user', 'content': 'Test.'}],
            'reasoning': {'effort': effort}, 'tool_choice': 'auto',
            'tools': [{'type': 'function', 'name': 'request_user_input', 'parameters': {}},
                      {'type': 'namespace', 'name': 'skills', 'tools': [
                          {'type': 'function', 'name': 'list'}, {'type': 'function', 'name': 'read'}]}] + functions}


def sse(model='z-ai/glm-5.3-flash', *, endpoint_model=None, requested=None):
    return ('event: response.completed\ndata: ' + json.dumps({'type': 'response.completed',
        'response': {'id': 'response-test', 'model': model, 'provider': 'Fixture Provider',
                     'usage': {'input_tokens': 12, 'output_tokens': 3, 'total_tokens': 15, 'cost': .001},
                     'openrouter_metadata': {'attempt': 1, 'is_byok': False,
                         **({'requested': requested} if requested is not None else {}),
                         'summary': 'Private routing summary.', 'pipeline': [{'data': 'Private pipeline.'}],
                         'endpoints': {'available': [
                             {'model': model if endpoint_model is None else endpoint_model,
                              'provider': 'Fixture Provider', 'selected': True},
                             {'model': 'unselected-model', 'provider': 'Other Provider', 'selected': False}]}},
                     'output': [{'type': 'message', 'role': 'assistant', 'content': [
                         {'type': 'output_text', 'text': 'Private model output excluded from telemetry.'}]}]}}) + '\n\n').encode()


class SlowStream(httpx.AsyncByteStream):
    def __init__(self):
        self.started, self.closed = asyncio.Event(), asyncio.Event()

    async def __aiter__(self):
        self.started.set()
        yield b'data: {"type":"response.created","response":{"model":"z-ai/glm-5.3-flash"}}\n\n'
        await asyncio.Event().wait()

    async def aclose(self):
        self.closed.set()


class GatewayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.calls, self.budgets = [], []

    def budget(self, key):
        self.budgets.append(key)
        return {'remaining_usd': 49}

    async def upstream(self, request):
        self.calls.append(request)
        return httpx.Response(200, content=sse(), headers={'content-type': 'text/event-stream'})

    def gateway(self, handler=None, budget=None, profile=None, **kwargs):
        return OpenRouterGateway(KEY, transport=httpx.MockTransport(handler or self.upstream),
                                 budget_check=budget or self.budget, profile=profile, **kwargs)

    def client(self, gateway):
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway), base_url='http://127.0.0.1',
                                headers={'Authorization': 'Bearer ' + gateway.token})

    async def test_reminder_is_last_developer_item_only_while_pending_and_not_during_compaction(self):
        pending = False
        request = payload()
        original = json.dumps(request, sort_keys=True)
        async with self.gateway(comment_reminder=lambda: pending) as gateway, self.client(gateway) as client:
            for enabled, compact in ((False, False), (True, False), (True, True), (True, False), (False, False)):
                pending = enabled
                current = dict(request, tools=[]) if compact else request
                self.assertEqual((await client.post('/v1/responses', json=current)).status_code, 200)
                sent = json.loads(self.calls[-1].content)
                expected = request['input'] + ([{'role': 'developer', 'content': [
                    {'type': 'input_text', 'text': COMMENT_REMINDER}]}] if enabled and not compact else [])
                self.assertEqual(sent['input'], expected)
                self.assertEqual(gateway.evidence[-1]['comment_reminder_added'], enabled and not compact)
            self.assertEqual(gateway.request_count, 5)
        self.assertEqual(json.dumps(request, sort_keys=True), original)

    async def test_reminder_does_not_bypass_request_byte_limit(self):
        from unittest.mock import patch
        request = payload()
        from astra_web.openrouter_gateway import _prepare_request
        ceiling = max(len(json.dumps(request).encode()),
                      len(json.dumps(_prepare_request(request, get_profile('openrouter-glm'))).encode())) + 10
        async with self.gateway(comment_reminder=lambda: True) as gateway, self.client(gateway) as client:
            with patch('astra_web.openrouter_gateway.MAX_REQUEST_BYTES', ceiling):
                response = await client.post('/v1/responses', json=request)
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()['error']['code'], 'request_too_large')
            self.assertEqual(gateway.request_count, 0)
            self.assertEqual(self.calls, [])

    async def test_actual_loopback_filters_tools_caps_output_and_records_only_metadata(self):
        async with self.gateway() as gateway:
            async with httpx.AsyncClient(trust_env=False) as client:
                request = payload()
                request['max_output_tokens'] = 100000
                response = await client.post(gateway.base_url + '/responses', json=request,
                    headers={'Authorization': 'Bearer ' + gateway.token})
            self.assertEqual(response.status_code, 200)
            upstream = self.calls[0]
            body = json.loads(upstream.content)
            self.assertEqual(str(upstream.url), UPSTREAM_URL)
            self.assertEqual(upstream.headers['authorization'], 'Bearer ' + KEY)
            self.assertEqual(upstream.headers['x-openrouter-metadata'], 'enabled')
            self.assertEqual({tool['name'] for tool in body['tools']}, TOOL_NAMES)
            self.assertEqual(len(body['tools']), 7)
            self.assertTrue(all(tool['type'] == 'function' for tool in body['tools']))
            self.assertEqual(body['max_output_tokens'], 32768)
            self.assertEqual(body['max_output_tokens'], MAX_OUTPUT_TOKENS)
            self.assertEqual(body['reasoning'], {'effort': 'max'})
            self.assertEqual((gateway.request_count, gateway.budget_check_count), (1, 1))
            self.assertEqual(gateway.evidence[0]['observed_model'], 'z-ai/glm-5.3-flash')
            self.assertEqual(gateway.evidence[0]['provider'], 'Fixture Provider')
            self.assertEqual(gateway.evidence[0]['usage']['cost'], .001)
            self.assertEqual(gateway.evidence[0]['routing'], {'attempt': 1, 'is_byok': False,
                'selected': [{'model': 'z-ai/glm-5.3-flash', 'provider': 'Fixture Provider'}]})
            self.assertTrue(gateway.evidence[0]['stream_complete'])
            self.assertEqual(gateway.evidence[0]['requested_reasoning'], 'max')
            self.assertEqual(gateway.evidence[0]['max_output_tokens'], 32768)
            self.assertEqual(gateway.evidence[0]['profile_version'], 4)

    async def test_new_profile_owns_output_allowance_even_with_a_smaller_client_default(self):
        async with self.gateway() as gateway, self.client(gateway) as client:
            for maximum in (None, 8192, 32768, 100000):
                request = payload()
                if maximum is not None:
                    request['max_output_tokens'] = maximum
                self.assertEqual((await client.post('/v1/responses', json=request)).status_code, 200)
        self.assertEqual(len(self.calls), 4)
        self.assertTrue(all(json.loads(request.content)['max_output_tokens'] == 32768 for request in self.calls))

    async def test_historical_high_requires_the_exact_trusted_host_profile(self):
        historical = replace(get_profile('openrouter-glm'), reasoning='high', version=3,
                             max_output_tokens=8192)
        async with self.gateway(profile=historical) as gateway, self.client(gateway) as client:
            self.assertEqual((await client.post('/v1/responses', json=payload())).status_code, 400)
            for tools in (payload()['tools'], []):
                request = {**payload('high'), 'tools': tools, 'max_output_tokens': 32768}
                self.assertEqual((await client.post('/v1/responses', json=request)).status_code, 200)
            self.assertEqual((gateway.request_count, gateway.budget_check_count), (2, 2))
            self.assertTrue(all(item['requested_reasoning'] == 'high' and item['max_output_tokens'] == 8192
                                and item['profile_version'] == 3 for item in gateway.evidence))
        self.assertTrue(all(json.loads(request.content)['max_output_tokens'] == 8192 for request in self.calls))
        async with self.gateway() as gateway, self.client(gateway) as client:
            self.assertEqual((await client.post('/v1/responses', json=payload('high'))).status_code, 400)
            self.assertEqual(gateway.request_count, 0)

    def test_untrusted_profiles_cannot_change_gateway_reasoning_or_output_policy(self):
        current = get_profile('openrouter-glm')
        for profile in (get_profile('astra'), {'reasoning': 'high'},
                        replace(current, max_output_tokens=8192),
                        replace(current, max_output_tokens=65536),
                        replace(current, reasoning='low'),
                        replace(current, provider='other-provider'),
                        replace(current, version=5)):
            with self.subTest(profile=profile), self.assertRaisesRegex(GatewayError, 'invalid_gateway_profile'):
                self.gateway(profile=profile)

    async def test_pinned_instructions_required_on_every_provider_request(self):
        instructions = 'Shared chess contract.\nPersona: Arcturus. 🐂'
        async with OpenRouterGateway(KEY, transport=httpx.MockTransport(self.upstream),
                budget_check=self.budget, expected_instructions=instructions) as gateway:
            async with self.client(gateway) as client:
                for actual in (None, 'Persona omitted.', instructions + '\nChanged.'):
                    request = payload()
                    if actual is not None:
                        request['instructions'] = actual
                    response = await client.post('/v1/responses', json=request)
                    self.assertEqual(response.status_code, 400)
                    self.assertEqual(response.json()['error']['code'], 'instructions_mismatch')
                self.assertFalse(self.calls)
                self.assertFalse(self.budgets)
                request = {**payload(), 'instructions': instructions}
                for _ in range(2):
                    self.assertEqual((await client.post('/v1/responses', json=request)).status_code, 200)
            self.assertEqual(len(self.calls), 2)
            self.assertTrue(all(row['instructions_verified'] for row in gateway.evidence))
            self.assertNotIn(instructions, json.dumps(gateway.evidence))
            self.assertNotIn('Private model output', json.dumps(gateway.evidence))
            self.assertNotIn('Private routing', json.dumps(gateway.evidence))
            self.assertNotIn('Private pipeline', json.dumps(gateway.evidence))
            self.assertNotIn(KEY, response.text + json.dumps(gateway.evidence))
        self.assertTrue(gateway._server_task.done())
        self.assertFalse(gateway._requests)

    async def test_text_only_compaction_retains_instructions_budget_and_output_cap(self):
        instructions = 'Pinned persona and shared chess contract.'
        async with OpenRouterGateway(KEY, transport=httpx.MockTransport(self.upstream),
                budget_check=self.budget, expected_instructions=instructions) as gateway, self.client(gateway) as client:
            for choice in ('auto', 'none'):
                request = {**payload(), 'instructions': instructions, 'tools': [],
                           'tool_choice': choice, 'max_output_tokens': 100000}
                response = await client.post('/v1/responses', json=request)
                self.assertNotIn('chess_gateway_upstream_interrupted', response.text)
            bad = {**request, 'instructions': 'Changed persona.'}
            self.assertEqual((await client.post('/v1/responses', json=bad)).json()['error']['code'], 'instructions_mismatch')
            self.assertEqual((gateway.request_count, gateway.budget_check_count), (2, 2))
            self.assertTrue(all(item['request_kind'] == 'compaction' and item['stream_complete']
                                and item['instructions_verified'] for item in gateway.evidence))
        for request in self.calls:
            body = json.loads(request.content)
            self.assertEqual(body['tools'], [])
            self.assertEqual(body['instructions'], instructions)
            self.assertEqual(body['max_output_tokens'], 32768)
            self.assertEqual(body['model'], MODEL)
            self.assertEqual(body['reasoning'], {'effort': 'max'})

    async def test_compaction_requires_exact_empty_list_and_non_tool_choice(self):
        bad = []
        for tools in (None, {}, payload()['tools'][:2]):
            bad.append({**payload(), 'tools': tools})
        missing = payload()
        del missing['tools']
        bad.append(missing)
        for choice in ('required', {'type': 'function', 'name': 'chess_status'}):
            bad.append({**payload(), 'tools': [], 'tool_choice': choice})
        async with self.gateway() as gateway, self.client(gateway) as client:
            for request in bad:
                self.assertEqual((await client.post('/v1/responses', json=request)).status_code, 400)
        self.assertFalse(self.calls)
        self.assertFalse(self.budgets)

    async def test_compaction_cannot_return_tool_calls(self):
        for event in (
            {'type': 'response.output_item.added', 'item': {'type': 'function_call', 'name': 'chess_choose', 'arguments': 'private'}},
            {'type': 'response.function_call_arguments.delta', 'delta': 'private'},
            {'type': 'response.completed', 'response': {'model': 'z-ai/glm-5.3-flash',
                'output': [{'type': 'function_call', 'name': 'chess_status', 'arguments': 'private'}]}},
        ):
            async def tool_response(request):
                return httpx.Response(200, content=('data: ' + json.dumps(event) + '\n\n').encode(),
                                      headers={'content-type': 'text/event-stream'})
            async with self.gateway(handler=tool_response) as gateway, self.client(gateway) as client:
                response = await client.post('/v1/responses', json={**payload(), 'tools': []})
                self.assertIn('chess_gateway_upstream_interrupted', response.text)
                self.assertNotIn('private', response.text)
                self.assertFalse(gateway.evidence[0]['stream_complete'])
                self.assertEqual(gateway.evidence[0]['output_rejection'], 'compaction_tool_output')

    async def test_nonce_and_route_are_required_before_budget_or_inference(self):
        async with self.gateway() as gateway, self.client(gateway) as client:
            for headers in ({'Authorization': 'Bearer wrong'}, {'Authorization': 'Bearer ' + KEY}):
                response = await client.post('/v1/responses', json=payload(), headers=headers)
                self.assertEqual(response.status_code, 401)
            self.assertEqual((await client.get('/v1/responses')).status_code, 404)
            self.assertEqual((await client.post('/v1/other', json=payload())).status_code, 404)
            self.assertEqual((await client.post('/v1/responses?alternate=1', json=payload())).status_code, 404)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.budgets, [])

    async def test_audited_codex_schema_normalization_is_accepted_and_bounds_restored(self):
        request = payload()
        for tool in request['tools']:
            if tool.get('name') in TOOL_NAMES:
                tool['parameters'] = _codex_wire_schema(tool['parameters'])
        async with self.gateway() as gateway, self.client(gateway) as client:
            self.assertEqual((await client.post('/v1/responses', json=request)).status_code, 200)
        forwarded = {tool['name']: tool for tool in json.loads(self.calls[0].content)['tools']}
        self.assertEqual(forwarded['chess_query']['parameters']['properties']['seconds']['maximum'], 180)
        self.assertEqual(forwarded['chess_candidate']['parameters']['properties']['concern']['maxLength'], 2000)

    async def test_invalid_model_schema_and_unaudited_tools_fail_without_sending(self):
        bad = []
        for name, value in (('model', 'other-model'), ('stream', False), ('max_output_tokens', True),
                            ('provider', {'sort': 'price'}), ('models', ['other-model']), ('route', 'fallback'),
                            ('plugins', []), ('reasoning', {'effort': 'low'}),
                            ('reasoning', {'effort': 'high'}),
                            ('reasoning', {'effort': 'max', 'max_tokens': 1024}),
                            ('max_output_tokens', 0), ('max_output_tokens', -1), ('max_output_tokens', 8192.0),
                            ('tool_choice', {'type': 'function', 'name': 'skills'})):
            request = payload()
            request[name] = value
            bad.append(request)
        request = payload()
        request['tools'].append({'type': 'function', 'name': 'shell', 'parameters': {}})
        bad.append(request)
        request = payload()
        request['tools'][1]['tools'].append({'type': 'function', 'name': 'write'})
        bad.append(request)
        request = payload()
        request['tools'][-1]['parameters'] = {}
        bad.append(request)
        request = payload()
        request['tools'].pop()
        bad.append(request)
        async with self.gateway() as gateway, self.client(gateway) as client:
            for request in bad:
                with self.subTest(request_kind=request.get('model')):
                    self.assertEqual((await client.post('/v1/responses', json=request)).status_code, 400)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.budgets, [])

    async def test_size_and_compression_bounds_precede_upstream(self):
        async with self.gateway() as gateway, self.client(gateway) as client:
            oversized = {**payload(), 'input': [{'role': 'user', 'content': 'x' * MAX_REQUEST_BYTES}]}
            response = await client.post('/v1/responses', json=oversized)
            self.assertEqual(response.status_code, 413)
            response = await client.post('/v1/responses', content=b'compressed', headers={'Content-Encoding': 'gzip'})
            self.assertEqual(response.status_code, 415)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.budgets, [])

    async def test_large_unicode_context_survives_json_escaping_above_old_request_cap(self):
        # 250,000 Unicode units exercise actual serialized context overhead.
        # This is a byte-bound regression, not a claim about tokenizer counts.
        content = '\U0001d51e ' * 250_000
        request = {**payload(), 'input': [{'role': 'user', 'content': content}],
                   'max_output_tokens': 100000}
        serialized = json.dumps(request, ensure_ascii=True).encode('utf-8')
        self.assertGreater(len(serialized), 2 * 1024 * 1024)
        self.assertLess(len(serialized), MAX_REQUEST_BYTES)
        async with self.gateway() as gateway, self.client(gateway) as client:
            response = await client.post('/v1/responses', content=serialized,
                                         headers={'Content-Type': 'application/json'})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(gateway.evidence[0]['stream_complete'])
        forwarded = json.loads(self.calls[0].content)
        self.assertEqual(forwarded['input'][0]['content'], content)
        self.assertEqual(forwarded['max_output_tokens'], 32768)
        self.assertEqual(len(self.budgets), 1)

    async def test_stream_event_keeps_smaller_two_mib_bound(self):
        event = {'type': 'response.output_text.delta', 'delta': 'x' * MAX_SSE_EVENT_BYTES}
        wire = ('data: ' + json.dumps(event) + '\n\n').encode('utf-8')
        self.assertGreater(len(wire), MAX_SSE_EVENT_BYTES)
        self.assertLess(len(wire), MAX_REQUEST_BYTES)
        async def oversized_event(request):
            return httpx.Response(200, content=wire, headers={'content-type': 'text/event-stream'})
        async with self.gateway(handler=oversized_event) as gateway, self.client(gateway) as client:
            response = await client.post('/v1/responses', json=payload())
            self.assertIn('chess_gateway_upstream_interrupted', response.text)
            self.assertNotIn('response.output_text.delta', response.text)
            self.assertFalse(gateway.evidence[0]['stream_complete'])

    async def test_budget_denial_blocks_every_model_request(self):
        def deny(key):
            self.budgets.append(key)
            raise OpenRouterSetupError('budget_low')
        async with self.gateway(budget=deny) as gateway, self.client(gateway) as client:
            response = await client.post('/v1/responses', json=payload())
            self.assertEqual(response.status_code, 402)
            self.assertEqual(response.json()['error']['reason'], 'budget_low')
            self.assertEqual(gateway.request_count, 0)
        self.assertEqual(self.calls, [])
        self.assertEqual(len(self.budgets), 1)

    async def test_budget_checked_again_for_each_round_without_paid_retries(self):
        async def failed(request):
            self.calls.append(request)
            return httpx.Response(429, text=KEY)
        async with self.gateway(handler=failed) as gateway, self.client(gateway) as client:
            for _ in range(2):
                response = await client.post('/v1/responses', json=payload())
                self.assertEqual(response.status_code, 429)
                self.assertNotIn(KEY, response.text)
            self.assertEqual((gateway.request_count, gateway.budget_check_count), (2, 2))
        self.assertEqual(len(self.calls), 2)

    async def test_output_limit_is_an_explicit_terminal_error_with_usage_and_no_retry(self):
        for event_type in ('response.incomplete', 'response.completed'):
            for tools in (payload()['tools'], []):
                with self.subTest(event_type=event_type, compaction=tools == []):
                    async def truncated(request):
                        self.calls.append(request)
                        event = {'type': event_type, 'response': {
                            'model': 'z-ai/glm-5.3-flash', 'status': 'incomplete',
                            'incomplete_details': {'reason': 'max_output_tokens', 'private': 'provider detail'},
                            'usage': {'input_tokens': 100, 'output_tokens': 32768, 'total_tokens': 32868},
                            'output': [{'type': 'reasoning', 'text': 'Private incomplete reasoning.'}]}}
                        return httpx.Response(200, content=('data: ' + json.dumps(event) + '\n\n').encode(),
                                              headers={'content-type': 'text/event-stream'})
                    async with self.gateway(handler=truncated) as gateway, self.client(gateway) as client:
                        response = await client.post('/v1/responses', json={**payload(), 'tools': tools})
                        self.assertIn('chess_gateway_output_limit', response.text)
                        self.assertIn('output token limit before completion', response.text)
                        self.assertNotIn('Private incomplete reasoning', response.text)
                        self.assertNotIn('provider detail', response.text + json.dumps(gateway.evidence))
                        self.assertNotIn(event_type, response.text)
                        self.assertEqual((gateway.request_count, gateway.budget_check_count), (1, 1))
                        self.assertFalse(gateway.evidence[0]['stream_complete'])
                        self.assertEqual(gateway.evidence[0]['incomplete_reason'], 'max_output_tokens')
                        self.assertEqual(gateway.evidence[0]['usage']['output_tokens'], 32768)
        self.assertEqual(len(self.calls), 4)

    async def test_other_incomplete_reasons_are_sanitized_and_not_misreported_as_length(self):
        async def incomplete(request):
            self.calls.append(request)
            event = {'type': 'response.incomplete', 'response': {
                'model': 'z-ai/glm-5.3-flash', 'status': 'incomplete',
                'incomplete_details': {'reason': 'Private provider failure detail.'}}}
            return httpx.Response(200, content=('data: ' + json.dumps(event) + '\n\n').encode(),
                                  headers={'content-type': 'text/event-stream'})
        async with self.gateway(handler=incomplete) as gateway, self.client(gateway) as client:
            response = await client.post('/v1/responses', json=payload())
            self.assertIn('chess_gateway_upstream_incomplete', response.text)
            self.assertNotIn('chess_gateway_output_limit', response.text)
            self.assertNotIn('Private provider failure', response.text + json.dumps(gateway.evidence))
            self.assertEqual(gateway.evidence[0]['incomplete_reason'], 'other')
            self.assertFalse(gateway.evidence[0]['stream_complete'])
            self.assertEqual((gateway.request_count, gateway.budget_check_count), (1, 1))

    async def test_redirect_is_not_followed_and_response_headers_are_not_forwarded(self):
        async def redirect(request):
            self.calls.append(request)
            return httpx.Response(307, headers={'Location': 'https://example.invalid/' + KEY}, text=KEY)
        async with self.gateway(handler=redirect) as gateway, self.client(gateway) as client:
            response = await client.post('/v1/responses', json=payload())
            self.assertEqual(response.status_code, 502)
            self.assertNotIn('location', response.headers)
            self.assertNotIn(KEY, response.text)
        self.assertEqual(len(self.calls), 1)

    async def test_model_mismatch_is_stopped_before_its_event_reaches_codex(self):
        async def changed(request):
            self.calls.append(request)
            return httpx.Response(200, content=sse('unrequested-model'), headers={'content-type': 'text/event-stream'})
        async with self.gateway(handler=changed) as gateway, self.client(gateway) as client:
            response = await client.post('/v1/responses', json=payload())
            self.assertNotIn('unrequested-model', response.text)
            self.assertIn('chess_gateway_upstream_interrupted', response.text)
            self.assertTrue(gateway.evidence[0]['model_mismatch'])
            self.assertFalse(gateway.evidence[0]['stream_complete'])
            self.assertEqual(gateway.evidence[0]['model_mismatch_field'], 'response.model')
            self.assertEqual(gateway.evidence[0]['mismatched_model'], 'unrequested-model')

    async def test_verified_dated_endpoint_keeps_strict_response_model_and_completes(self):
        async def dated(request):
            return httpx.Response(200, content=sse(endpoint_model='z-ai/glm-5.3-flash-20260826', requested=MODEL),
                                  headers={'content-type': 'text/event-stream'})
        async with self.gateway(handler=dated) as gateway, self.client(gateway) as client:
            response = await client.post('/v1/responses', json=payload())
            self.assertNotIn('chess_gateway_upstream_interrupted', response.text)
            self.assertIn('response.completed', response.text)
            evidence = gateway.evidence[0]
            self.assertEqual(evidence['observed_model'], 'z-ai/glm-5.3-flash')
            self.assertEqual(evidence['routing']['requested'], MODEL)
            self.assertEqual(evidence['routing']['selected'][0]['model'], 'z-ai/glm-5.3-flash-20260826')
            self.assertTrue(evidence['stream_complete'])

    async def test_dated_endpoint_does_not_expand_response_model_allowlist(self):
        async def changed(request):
            return httpx.Response(200, content=sse('z-ai/glm-5.3-flash-20260826'),
                                  headers={'content-type': 'text/event-stream'})
        async with self.gateway(handler=changed) as gateway, self.client(gateway) as client:
            response = await client.post('/v1/responses', json=payload())
            self.assertNotIn('response.completed', response.text)
            self.assertEqual(gateway.evidence[0]['model_mismatch_field'], 'response.model')
            self.assertFalse(gateway.evidence[0]['stream_complete'])

    async def test_unrequested_metadata_or_unknown_endpoint_fails_before_completion(self):
        for field, options, identifier in (
            ('routing.requested', {'requested': 'unrequested-model'}, 'unrequested-model'),
            ('routing.requested', {'requested': 'z-ai/glm-5.3-flash'}, 'z-ai/glm-5.3-flash'),
            ('routing.selected.model', {'endpoint_model': 'unrequested-model'}, 'unrequested-model'),
            ('routing.selected.model', {'endpoint_model': 'z-ai/glm-5.3-flash-20990101'},
             'z-ai/glm-5.3-flash-20990101'),
        ):
            with self.subTest(field=field, identifier=identifier):
                async def changed(request):
                    return httpx.Response(200, content=sse(**options), headers={'content-type': 'text/event-stream'})
                async with self.gateway(handler=changed) as gateway, self.client(gateway) as client:
                    response = await client.post('/v1/responses', json=payload())
                    self.assertNotIn('response.completed', response.text)
                    self.assertIn('chess_gateway_upstream_interrupted', response.text)
                    self.assertEqual(gateway.evidence[0]['observed_model'], 'z-ai/glm-5.3-flash')
                    self.assertEqual(gateway.evidence[0]['model_mismatch_field'], field)
                    self.assertEqual(gateway.evidence[0]['mismatched_model'], identifier)
                    self.assertFalse(gateway.evidence[0]['stream_complete'])

    async def test_late_invalid_metadata_revokes_completion_and_omits_arbitrary_identifier(self):
        unsafe_identifier = 'Private arbitrary text.\n' + 'x' * 250
        async def changed(request):
            terminal = {'openrouter_metadata': {'requested': unsafe_identifier}}
            body = sse() + ('data: ' + json.dumps(terminal) + '\n\n').encode()
            return httpx.Response(200, content=body, headers={'content-type': 'text/event-stream'})
        async with self.gateway(handler=changed) as gateway, self.client(gateway) as client:
            response = await client.post('/v1/responses', json=payload())
            self.assertIn('chess_gateway_upstream_interrupted', response.text)
            evidence = gateway.evidence[0]
            self.assertFalse(evidence['stream_complete'])
            self.assertTrue(evidence['model_mismatch'])
            self.assertNotIn('mismatched_model', evidence)
            self.assertNotIn('Private arbitrary text', json.dumps(evidence) + response.text)

    async def test_only_one_active_request_and_cancellation_closes_upstream(self):
        stream = SlowStream()
        async def slow(request):
            self.calls.append(request)
            return httpx.Response(200, stream=stream, headers={'content-type': 'text/event-stream'})
        async with self.gateway(handler=slow) as gateway, self.client(gateway) as client:
            first = asyncio.create_task(client.post('/v1/responses', json=payload()))
            await asyncio.wait_for(stream.started.wait(), 2)
            response = await client.post('/v1/responses', json=payload())
            self.assertEqual(response.status_code, 409)
            first.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await first
            await asyncio.wait_for(stream.closed.wait(), 2)
            self.assertFalse(gateway._busy)
            self.assertEqual((gateway.request_count, gateway.budget_check_count), (1, 1))
        self.assertFalse(gateway._requests)

    async def test_context_exit_cancels_active_request(self):
        stream = SlowStream()
        async def slow(request):
            return httpx.Response(200, stream=stream, headers={'content-type': 'text/event-stream'})
        async with self.gateway(handler=slow) as gateway:
            async with self.client(gateway) as client:
                task = asyncio.create_task(client.post('/v1/responses', json=payload()))
                await asyncio.wait_for(stream.started.wait(), 2)
                await gateway.close()
                self.assertTrue(task.cancelled())
                self.assertTrue(stream.closed.is_set())
        self.assertFalse(gateway._requests)


if __name__ == '__main__':
    unittest.main()
