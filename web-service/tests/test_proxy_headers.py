"""Verify the entry point and real Uvicorn proxy middleware without a server."""
import os
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse
import uvicorn


RUN_SCRIPT = Path(__file__).resolve().parents[1] / 'run.py'


async def client_echo(scope, receive, send):
    request = Request(scope)
    await JSONResponse({'client': request.client.host, 'port': request.client.port,
                        'scheme': request.url.scheme, 'host': request.headers['host']})(scope, receive, send)


def startup_options(*arguments):
    # No credential file, database, socket or app lifespan is touched.
    with patch.dict(os.environ, {'ASTRA_ORIGIN': 'https://astraplayschess.com',
                                 'FORWARDED_ALLOW_IPS': '*'}, clear=True), \
            patch('sys.argv', [str(RUN_SCRIPT), *arguments]), \
            patch('astra_web.local_setup.load_local_environment'), \
            patch('astra_web.app.create_app', return_value=client_echo), \
            patch('uvicorn.run') as run:
        runpy.run_path(str(RUN_SCRIPT), run_name='__main__')
    run.assert_called_once()
    return run.call_args.kwargs


class ProxyHeaderTests(unittest.IsolatedAsyncioTestCase):
    async def request(self, options, peer, forwarded='198.51.100.42'):
        config = uvicorn.Config(client_echo, proxy_headers=options['proxy_headers'],
            forwarded_allow_ips=options['forwarded_allow_ips'], interface='asgi3',
            lifespan='off', log_config=None)
        config.load()
        transport = httpx.ASGITransport(app=config.loaded_app, client=(peer, 32123))
        async with httpx.AsyncClient(transport=transport, base_url='http://astraplayschess.com') as client:
            result = await client.get('/', headers={'X-Forwarded-For': forwarded,
                'X-Forwarded-Proto': 'https', 'X-Forwarded-Host': 'spoofed.invalid'})
        self.assertEqual(result.status_code, 200)
        return result.json()

    async def test_default_is_off_even_with_wildcard_environment_and_loopback_peer(self):
        options = startup_options()
        self.assertFalse(options['proxy_headers'])
        self.assertEqual(options['forwarded_allow_ips'], '127.0.0.1')
        self.assertEqual(options['host'], '127.0.0.1')
        result = await self.request(options, '127.0.0.1')
        self.assertEqual(result, {'client': '127.0.0.1', 'port': 32123,
                                 'scheme': 'http', 'host': 'astraplayschess.com'})

    async def test_opt_in_honors_loopback_proxy_client_and_scheme_without_changing_host(self):
        options = startup_options('--proxy-headers')
        self.assertTrue(options['proxy_headers'])
        self.assertEqual(options['forwarded_allow_ips'], '127.0.0.1')
        result = await self.request(options, '127.0.0.1')
        self.assertEqual(result, {'client': '198.51.100.42', 'port': 0,
                                 'scheme': 'https', 'host': 'astraplayschess.com'})

    async def test_nontrusted_peers_cannot_spoof_client_or_scheme(self):
        options = startup_options('--proxy-headers')
        for peer in ('203.0.113.15', '10.0.0.10', '::1'):
            with self.subTest(peer=peer):
                result = await self.request(options, peer)
                self.assertEqual(result, {'client': peer, 'port': 32123,
                                         'scheme': 'http', 'host': 'astraplayschess.com'})

    async def test_trusted_proxy_chain_uses_nearest_untrusted_client_not_spoofed_prefix(self):
        options = startup_options('--proxy-headers')
        result = await self.request(options, '127.0.0.1', '192.0.2.66, 198.51.100.42')
        self.assertEqual(result['client'], '198.51.100.42')


if __name__ == '__main__':
    unittest.main()
