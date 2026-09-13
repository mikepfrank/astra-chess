"""Loopback gateway tests with mocked inference and budget verification."""
import asyncio
import json
import unittest

import httpx

from astra_web.codex_bridge import dynamic_tools, TOOL_NAMES
from astra_web.openrouter_gateway import OpenRouterGateway, MODEL, UPSTREAM_URL, MAX_REQUEST_BYTES, _codex_wire_schema
from astra_web.openrouter_setup import OpenRouterSetupError


KEY = 'unit-test-private-openrouter-key'


def payload():
    functions = [{'type': 'function', 'name': item['name'], 'description': item['description'],
                  'parameters': item['inputSchema'], 'strict': False} for item in dynamic_tools()]
    return {'model': MODEL, 'stream': True, 'input': [{'role': 'user', 'content': 'Test.'}],
            'reasoning': {'effort': 'high'}, 'tool_choice': 'auto',
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
                     'output': [{'text': 'Private model output excluded from telemetry.'}]}}) + '\n\n').encode()


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

    def gateway(self, handler=None, budget=None):
        return OpenRouterGateway(KEY, transport=httpx.MockTransport(handler or self.upstream),
                                 budget_check=budget or self.budget)

    def client(self, gateway):
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway), base_url='http://127.0.0.1',
                                headers={'Authorization': 'Bearer ' + gateway.token})

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
            self.assertEqual(body['max_output_tokens'], 8192)
            self.assertEqual(body['reasoning'], {'effort': 'high'})
            self.assertEqual((gateway.request_count, gateway.budget_check_count), (1, 1))
            self.assertEqual(gateway.evidence[0]['observed_model'], 'z-ai/glm-5.3-flash')
            self.assertEqual(gateway.evidence[0]['provider'], 'Fixture Provider')
            self.assertEqual(gateway.evidence[0]['usage']['cost'], .001)
            self.assertEqual(gateway.evidence[0]['routing'], {'attempt': 1, 'is_byok': False,
                'selected': [{'model': 'z-ai/glm-5.3-flash', 'provider': 'Fixture Provider'}]})
            self.assertTrue(gateway.evidence[0]['stream_complete'])

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
            response = await client.post('/v1/responses', content=b' ' * (MAX_REQUEST_BYTES + 1))
            self.assertEqual(response.status_code, 413)
            response = await client.post('/v1/responses', content=b'compressed', headers={'Content-Encoding': 'gzip'})
            self.assertEqual(response.status_code, 415)
        self.assertEqual(self.calls, [])

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
