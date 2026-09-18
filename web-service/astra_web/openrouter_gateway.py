"""Private loopback adapter for the audited Codex/OpenRouter experiment.

Codex receives an ephemeral local token, never the OpenRouter credential. The
adapter removes the two observed built-in tool declarations and forwards only
the seven canonical chess functions. Every provider request has a fresh budget
check, one fixed model, an output ceiling, and no HTTP retries or redirects.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
import hmac
import hashlib
import json
import math
import re
import secrets
import socket

import httpx
import uvicorn

from .openrouter_setup import OpenRouterSetupError, require_budget


UPSTREAM_URL = 'https://openrouter.ai/api/v1/responses'
MODEL = 'z-ai/glm-5.3-flash:nitro'
# Public catalog verified 2026-09-13: https://openrouter.ai/api/v1/models
# id z-ai/glm-5.3-flash has canonical_slug z-ai/glm-5.3-flash-20260826.
# Routing metadata may use that dated identifier. Response.model remains
# separately restricted to its two previously audited API response slugs.
ENDPOINT_MODELS = (MODEL, 'z-ai/glm-5.3-flash', 'z-ai/glm-5.3-flash-20260826')
# Long conversation JSON needs room for escaping and tool-history overhead.
# This byte ceiling is separate from the model's context/token accounting.
MAX_REQUEST_BYTES = 8 * 1024 * 1024
MAX_SSE_EVENT_BYTES = 2 * 1024 * 1024
MAX_OUTPUT_TOKENS = 32768
COMMENT_REMINDER = (
    'Note: Only messages sent using chess_comment() will be displayed to the human player '
    'in the sidebar chat. Ordinary assistant text is saved as internal notes. '
    'Use chess_comment() if you intend to reply to the human.')


class GatewayError(ValueError):
    """Classification only; no model input, HTTP response or credential text."""


def _codex_wire_schema(schema):
    """Exact constraint removal observed in the audited alpha's wire output.

    The gateway restores the canonical bounds before forwarding to OpenRouter.
    The chess host independently validates them when executing a tool.
    """
    omitted = {'pattern', 'maxLength', 'maxItems', 'minimum', 'maximum', 'exclusiveMinimum'}
    if isinstance(schema, dict):
        return {key: _codex_wire_schema(value) for key, value in schema.items() if key not in omitted}
    if isinstance(schema, list):
        return [_codex_wire_schema(value) for value in schema]
    return schema


def _prepare_request(payload, profile):
    # Lazy import avoids a bridge/gateway import cycle.
    from .codex_bridge import dynamic_tools
    specs = {tool['name']: tool for tool in dynamic_tools()}
    if (not isinstance(payload, dict) or payload.get('model') != MODEL
            or payload.get('stream') is not True
            or {'provider', 'models', 'route', 'plugins'} & payload.keys()
            or payload.get('reasoning') != {'effort': profile.reasoning}):
        raise GatewayError('invalid_request')
    incoming = payload.get('tools')
    if not isinstance(incoming, list):
        raise GatewayError('invalid_tools')
    seen, forwarded = set(), []
    for tool in incoming:
        if not isinstance(tool, dict) or not isinstance(tool.get('name'), str):
            raise GatewayError('invalid_tools')
        name, kind = tool['name'], tool.get('type')
        if name in seen:
            raise GatewayError('invalid_tools')
        seen.add(name)
        if name == 'request_user_input' and kind == 'function':
            continue
        if name == 'skills' and kind == 'namespace':
            children = tool.get('tools')
            if (not isinstance(children, list) or len(children) != 2
                    or any(not isinstance(child, dict) or child.get('type') != 'function' for child in children)
                    or {child.get('name') for child in children} != {'list', 'read'}):
                raise GatewayError('invalid_tools')
            continue
        if name not in specs or kind != 'function':
            raise GatewayError('invalid_tools')
        schema = specs[name]['inputSchema']
        if tool.get('parameters') not in (schema, _codex_wire_schema(schema)):
            raise GatewayError('invalid_tools')
        forwarded.append({'type': 'function', 'name': name,
            'description': specs[name]['description'], 'parameters': specs[name]['inputSchema'], 'strict': False})
    # Codex's audited local compaction uses the same pinned instructions and
    # model with exactly tools: []. Missing tools and partial/extra tool sets
    # remain invalid. This grants no model-callable host capability.
    compaction = incoming == []
    if not compaction and {tool['name'] for tool in forwarded} != set(specs):
        raise GatewayError('invalid_tools')
    choice = payload.get('tool_choice', 'auto')
    if compaction:
        if choice not in ('auto', 'none'):
            raise GatewayError('invalid_tool_choice')
    elif isinstance(choice, dict):
        if set(choice) != {'type', 'name'} or choice.get('type') != 'function' or choice.get('name') not in specs:
            raise GatewayError('invalid_tool_choice')
    elif choice not in ('auto', 'none', 'required'):
        raise GatewayError('invalid_tool_choice')
    maximum = payload.get('max_output_tokens', profile.max_output_tokens)
    if type(maximum) is not int or maximum <= 0:
        raise GatewayError('invalid_output_limit')
    # The :nitro suffix already selects throughput routing. Do not add another
    # provider policy that could conflict with the recorded experiment profile.
    # The trusted per-game profile owns the allowance. A smaller client default
    # must not silently retain the former 8K limit for a new Max game. Historical
    # High games select their exact old profile through the host, never the wire.
    return {**payload, 'tools': forwarded, 'max_output_tokens': profile.max_output_tokens}


class _LoopbackServer(uvicorn.Server):
    @contextmanager
    def capture_signals(self):
        # The containing chess service owns process signals.
        yield


class OpenRouterGateway:
    """Use ``async with OpenRouterGateway(key)``; pass base_url/token to Codex.

    ``transport`` and ``budget_check`` permit tests without external requests.
    The production default checks the worktree-wide experiment budget each time.
    """
    def __init__(self, api_key, *, transport=None, budget_check=None, expected_instructions=None,
                 profile=None, comment_reminder=None):
        if not isinstance(api_key, str) or not api_key or '\r' in api_key or '\n' in api_key:
            raise GatewayError('invalid_credential')
        self._api_key = api_key
        from .player_profiles import get_profile, trusted_runtime_profile
        profile = get_profile('openrouter-glm') if profile is None else profile
        if not trusted_runtime_profile(profile) or profile.name != 'openrouter-glm':
            raise GatewayError('invalid_gateway_profile')
        self.profile = profile
        if expected_instructions is not None and (not isinstance(expected_instructions, str) or not expected_instructions.strip()):
            raise GatewayError('invalid_expected_instructions')
        self._expected_instructions = expected_instructions
        # Host-owned publication state, never inferred from model tool arguments.
        self._comment_reminder = comment_reminder
        self._transport = transport
        self._budget_check = budget_check or require_budget
        self.token = secrets.token_urlsafe(32)
        self.base_url = None
        self._client = self._socket = self._server = self._server_task = None
        self._requests = set()
        self._busy = False
        self._closing = False
        self.request_count = 0
        self.budget_check_count = 0
        self.evidence = []
        self.rejections = []

    async def __aenter__(self):
        if self._client is not None or self._closing:
            raise GatewayError('gateway_already_used')
        self._client = httpx.AsyncClient(transport=self._transport, trust_env=False,
            follow_redirects=False, timeout=httpx.Timeout(60, connect=10, write=10, pool=10),
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=1))
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            self._socket.bind(('127.0.0.1', 0))
            self._socket.listen(8)
            self._socket.setblocking(False)
            self.base_url = f'http://127.0.0.1:{self._socket.getsockname()[1]}/v1'
            config = uvicorn.Config(self, host='127.0.0.1', port=0, lifespan='off',
                ws='none', proxy_headers=False, access_log=False, log_config=None,
                log_level='critical', server_header=False, date_header=False,
                timeout_keep_alive=1, timeout_graceful_shutdown=1)
            self._server = _LoopbackServer(config)
            self._server_task = asyncio.create_task(self._server.serve(sockets=[self._socket]))
            async with asyncio.timeout(5):
                while not self._server.started:
                    if self._server_task.done():
                        raise GatewayError('gateway_start_failed')
                    await asyncio.sleep(.01)
            return self
        except BaseException:
            await self.close()
            raise

    async def __aexit__(self, *exc):
        await self.close()

    async def close(self):
        self._closing = True
        tasks = [task for task in self._requests if task is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self._server:
            self._server.should_exit = True
        if self._server_task:
            try:
                await asyncio.wait_for(self._server_task, 2)
            except (TimeoutError, asyncio.CancelledError):
                self._server_task.cancel()
                await asyncio.gather(self._server_task, return_exceptions=True)
        if self._client:
            await self._client.aclose()
            self._client = None
        if self._socket:
            self._socket.close()
            self._socket = None

    async def _error(self, send, status, code, **safe_fields):
        if len(self.rejections) < 64:
            self.rejections.append({'status': status, 'code': code, **safe_fields})
        body = json.dumps({'error': {'type': 'chess_gateway_error', 'code': code, **safe_fields}}).encode('utf-8')
        await send({'type': 'http.response.start', 'status': status,
                    'headers': [(b'content-type', b'application/json'), (b'cache-control', b'no-store')]})
        await send({'type': 'http.response.body', 'body': body})

    async def _forward(self, payload, send, *, comment_reminder_added=False):
        try:
            self.budget_check_count += 1
            await asyncio.to_thread(self._budget_check, self._api_key)
        except OpenRouterSetupError as error:
            await self._error(send, 402, 'budget_denied', reason=error.code)
            return
        except Exception:
            await self._error(send, 503, 'budget_unavailable')
            return
        started = False
        evidence = {'requested_model': MODEL, 'observed_model': None,
                    'requested_reasoning': self.profile.reasoning,
                    'max_output_tokens': self.profile.max_output_tokens,
                    'profile_version': self.profile.version,
                    'request_kind': 'compaction' if payload['tools'] == [] else 'chess',
                    'comment_reminder_added': comment_reminder_added,
                    'response_id': None, 'provider': None, 'usage': {}, 'stream_complete': False}
        if self._expected_instructions is not None:
            evidence['instructions_verified'] = True
            evidence['instructions_sha256'] = hashlib.sha256(self._expected_instructions.encode('utf-8')).hexdigest()
        try:
            self.request_count += 1
            self.evidence.append(evidence)
            async with self._client.stream('POST', UPSTREAM_URL, json=payload,
                    headers={'Authorization': 'Bearer ' + self._api_key,
                             'Accept': 'text/event-stream', 'Accept-Encoding': 'identity',
                             'X-OpenRouter-Metadata': 'enabled'}) as upstream:
                evidence['upstream_status'] = upstream.status_code
                if upstream.status_code != 200:
                    await self._error(send, upstream.status_code if 400 <= upstream.status_code <= 599 else 502,
                                      'upstream_http_error', upstream_status=upstream.status_code)
                    return
                if not upstream.headers.get('content-type', '').lower().startswith('text/event-stream'):
                    await self._error(send, 502, 'unexpected_upstream_content')
                    return
                await send({'type': 'http.response.start', 'status': 200,
                    'headers': [(b'content-type', b'text/event-stream'), (b'cache-control', b'no-store')]})
                started = True
                frame, size = [], 0
                async for line in upstream.aiter_lines():
                    size += len(line.encode('utf-8')) + 1
                    if size > MAX_SSE_EVENT_BYTES:
                        raise GatewayError('upstream_event_too_large')
                    if line:
                        frame.append(line)
                    elif frame:
                        self._observe_frame(frame, evidence)
                        await send({'type': 'http.response.body',
                                    'body': ('\n'.join(frame) + '\n\n').encode('utf-8'), 'more_body': True})
                        frame, size = [], 0
                if frame:
                    self._observe_frame(frame, evidence)
                    await send({'type': 'http.response.body',
                                'body': ('\n'.join(frame) + '\n\n').encode('utf-8'), 'more_body': True})
                await send({'type': 'http.response.body', 'body': b''})
        except Exception as error:
            evidence['interrupted'] = True
            evidence['stream_complete'] = False
            if started:
                output_limit = isinstance(error, GatewayError) and str(error) == 'upstream_output_limit'
                incomplete = isinstance(error, GatewayError) and str(error) == 'upstream_incomplete'
                if output_limit:
                    code = 'chess_gateway_output_limit'
                    message = 'Provider response reached its output token limit before completion.'
                elif incomplete:
                    code = 'chess_gateway_upstream_incomplete'
                    message = 'Provider response ended before completion.'
                else:
                    code = 'chess_gateway_upstream_interrupted'
                    message = 'Provider stream interrupted.'
                body = 'event: error\ndata: ' + json.dumps({'type': 'error', 'code': code,
                    'message': message}) + '\n\n'
                await send({'type': 'http.response.body', 'body': body.encode('utf-8')})
            else:
                await self._error(send, 502, 'upstream_unavailable')

    def _observe_frame(self, frame, evidence):
        """Inspect only response metadata; never save text, reasoning or tool arguments."""
        joined = '\n'.join(frame)
        if self._api_key in joined:
            raise GatewayError('credential_in_upstream')
        data = '\n'.join(line[5:].lstrip() for line in frame if line.startswith('data:'))
        if not data or data == '[DONE]':
            return
        try:
            event = json.loads(data)
        except ValueError:
            raise GatewayError('invalid_upstream_event') from None
        if not isinstance(event, dict):
            raise GatewayError('invalid_upstream_event')
        if evidence.get('request_kind') == 'compaction':
            # A summary response may contain reasoning and assistant text, but
            # never tool calls, even if a provider ignores the empty tool list.
            response_items = (event.get('response') or {}).get('output', []) if isinstance(event.get('response'), dict) else []
            items = [event['item']] if isinstance(event.get('item'), dict) else []
            if isinstance(response_items, list):
                items += response_items
            event_type = event.get('type', '')
            if ((isinstance(event_type, str) and event_type.startswith(
                    ('response.function_call', 'response.custom_tool_call')))
                    or any(not isinstance(item, dict) or item.get('type') not in ('message', 'reasoning')
                           for item in items)):
                evidence['output_rejection'] = 'compaction_tool_output'
                raise GatewayError('compaction_tool_output')

        def reject_model(field, value):
            evidence['model_mismatch'] = True
            evidence['model_mismatch_field'] = field
            # Keep only a bounded model identifier, never arbitrary event data.
            if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9._:/-]{1,200}', value):
                evidence['mismatched_model'] = value
            raise GatewayError('upstream_model_mismatch')

        response = event.get('response')
        if not isinstance(response, dict):
            response = event
        model = response.get('model')
        if model is not None:
            if model not in (MODEL, 'z-ai/glm-5.3-flash'):
                reject_model('response.model', model)
            evidence['observed_model'] = model
        for source, target in (('id', 'response_id'), ('provider', 'provider'), ('provider_name', 'provider')):
            value = response.get(source)
            if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9 ._:/-]{1,200}', value):
                evidence[target] = value
        usage = response.get('usage')
        if isinstance(usage, dict):
            for name in ('input_tokens', 'output_tokens', 'total_tokens', 'cost'):
                value = usage.get(name)
                if type(value) in (int, float) and math.isfinite(value) and value >= 0:
                    evidence['usage'][name] = value
        # Documented opt-in Responses metadata can be on the terminal event or
        # response object. Cache hits may omit it. Never retain pipeline/summary.
        metadata = event.get('openrouter_metadata', response.get('openrouter_metadata'))
        if isinstance(metadata, dict):
            routing = {}
            if 'requested' in metadata:
                if metadata['requested'] != MODEL:
                    reject_model('routing.requested', metadata['requested'])
                routing['requested'] = metadata['requested']
            if type(metadata.get('attempt')) is int and metadata['attempt'] >= 0:
                routing['attempt'] = metadata['attempt']
            if type(metadata.get('is_byok')) is bool:
                routing['is_byok'] = metadata['is_byok']
            endpoints = metadata.get('endpoints')
            available = endpoints.get('available') if isinstance(endpoints, dict) else None
            if isinstance(available, list):
                selected = []
                for endpoint in available:
                    if not isinstance(endpoint, dict) or endpoint.get('selected') is not True:
                        continue
                    model, provider = endpoint.get('model'), endpoint.get('provider')
                    if model not in ENDPOINT_MODELS:
                        reject_model('routing.selected.model', model)
                    if isinstance(provider, str) and re.fullmatch(r'[A-Za-z0-9 ._:/-]{1,200}', provider):
                        selected.append({'model': model, 'provider': provider})
                routing['selected'] = selected
                if len(selected) == 1:
                    evidence['provider'] = selected[0]['provider']
            evidence['routing'] = routing
        if event.get('type') == 'response.incomplete' or response.get('status') == 'incomplete':
            details = response.get('incomplete_details')
            reason = details.get('reason') if isinstance(details, dict) else None
            # Do not forward the incomplete terminal payload or save arbitrary
            # provider text. Keep usage above for cost accounting; report a
            # specific terminal error so a length cutoff cannot look like idle.
            evidence['incomplete_reason'] = reason if reason in ('max_output_tokens', 'content_filter') else 'other'
            if reason == 'max_output_tokens':
                raise GatewayError('upstream_output_limit')
            raise GatewayError('upstream_incomplete')
        if event.get('type') == 'response.completed':
            evidence['stream_complete'] = True

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return
        current = asyncio.current_task()
        self._requests.add(current)
        operation = disconnected = None
        admitted = False
        try:
            if scope.get('path') != '/v1/responses' or scope.get('method') != 'POST' or scope.get('query_string'):
                await self._error(send, 404, 'unknown_route')
                return
            headers = scope.get('headers', [])
            authorization = [value for key, value in headers if key.lower() == b'authorization']
            expected = ('Bearer ' + self.token).encode('ascii')
            if len(authorization) != 1 or not hmac.compare_digest(authorization[0], expected):
                await self._error(send, 401, 'unauthorized')
                return
            if self._closing or self._client is None:
                await self._error(send, 503, 'gateway_closed')
                return
            if any(key.lower() == b'content-encoding' and value.lower() != b'identity' for key, value in headers):
                await self._error(send, 415, 'unsupported_encoding')
                return
            body = bytearray()
            try:
                async with asyncio.timeout(10):
                    while True:
                        message = await receive()
                        if message['type'] == 'http.disconnect':
                            return
                        body.extend(message.get('body', b''))
                        if len(body) > MAX_REQUEST_BYTES:
                            await self._error(send, 413, 'request_too_large')
                            return
                        if not message.get('more_body', False):
                            break
                payload = _prepare_request(json.loads(body), self.profile)
                if self._expected_instructions is not None and payload.get('instructions') != self._expected_instructions:
                    raise GatewayError('instructions_mismatch')
                reminded = bool(payload['tools'] and self._comment_reminder
                                and self._comment_reminder() is True)
                if reminded:
                    items = payload.get('input')
                    if isinstance(items, str):
                        items = [{'role': 'user', 'content': items}]
                    if not isinstance(items, list):
                        raise GatewayError('invalid_input')
                    # Append only on the outgoing request: do not accumulate
                    # copies in native history or interfere with compaction.
                    payload['input'] = [*items, {'role': 'developer', 'content': [
                        {'type': 'input_text', 'text': COMMENT_REMINDER}]}]
                if len(json.dumps(payload, allow_nan=False).encode('utf-8')) > MAX_REQUEST_BYTES:
                    raise GatewayError('request_too_large')
            except GatewayError as error:
                await self._error(send, 400, str(error))
                return
            except (ValueError, TypeError, TimeoutError):
                await self._error(send, 400, 'invalid_request')
                return
            if self._busy:
                await self._error(send, 409, 'request_already_active')
                return
            self._busy = admitted = True

            async def watch_disconnect():
                while (await receive())['type'] != 'http.disconnect':
                    pass

            operation = asyncio.create_task(self._forward(payload, send, comment_reminder_added=reminded))
            disconnected = asyncio.create_task(watch_disconnect())
            done, _ = await asyncio.wait({operation, disconnected}, return_when=asyncio.FIRST_COMPLETED)
            if operation in done:
                await operation
        finally:
            for task in (operation, disconnected):
                if task and not task.done():
                    task.cancel()
            await asyncio.gather(*(task for task in (operation, disconnected) if task), return_exceptions=True)
            if admitted:
                self._busy = False
            self._requests.discard(current)


Gateway = OpenRouterGateway
