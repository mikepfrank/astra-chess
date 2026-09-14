"""Explicit deployment aliases preserve host-only sessions and same-origin writes."""
from contextlib import closing
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from astra_web.app import create_app
from astra_web.config import Config, origin_host_authorities


CANONICAL = 'https://arcturuschess.com'
PREVIOUS = 'https://arcturus.astraplayschess.com'


class OriginConfigTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)

    def config(self, **fields):
        return Config(data_dir=self.folder, **fields)

    def test_default_remains_one_origin_and_aliases_are_explicit(self):
        config = self.config()
        config.validate()
        self.assertEqual(config.origin, 'http://127.0.0.1:8788')
        self.assertEqual(config.additional_origins, ())
        with patch.dict(os.environ, {'ASTRA_ORIGIN': CANONICAL,
                                      'ASTRA_ADDITIONAL_ORIGINS': PREVIOUS}):
            config = self.config()
        config.validate()
        self.assertEqual(config.origin, CANONICAL)
        self.assertEqual(config.additional_origins, (PREVIOUS,))
        self.assertTrue(config.secure_cookies)

    def test_invalid_origin_components_are_rejected_for_canonical_and_aliases(self):
        for origin in ('', '*', 'https://*.example.org', '//example.org',
                       'ftp://example.org', 'https://user@example.org',
                       'https://user:secret@example.org', 'https://example.org/path',
                       'https://example.org/', 'https://example.org?', 'https://example.org#',
                       'https://example.org?x=1', 'https://example.org#fragment',
                       'https://example.org:0', 'https://example.org:65536',
                       'https://example.org:', 'https://example.org:0443',
                       'https://example.org\\evil', 'https://example.org\n',
                       'https://example.org\x00', 'https://example.org,evil.org',
                       'https://example.org.', 'https://-example.org',
                       'https://example..org', 'https://éxample.org', None):
            with self.subTest(origin=origin):
                with self.assertRaises(ValueError):
                    self.config(origin=origin).validate()
                with self.assertRaises(ValueError):
                    self.config(origin=CANONICAL, additional_origins=(origin,)).validate()

    def test_alias_collection_rejects_duplicates_mixed_scheme_and_invalid_structure(self):
        for aliases in (PREVIOUS, [PREVIOUS], (CANONICAL,), (PREVIOUS, PREVIOUS),
                        ('http://arcturus.astraplayschess.com',),
                        tuple('https://host' + str(index) + '.example.org' for index in range(9))):
            with self.subTest(aliases=aliases), self.assertRaises(ValueError):
                self.config(origin=CANONICAL, additional_origins=aliases).validate()
        with patch.dict(os.environ, {'ASTRA_ADDITIONAL_ORIGINS': PREVIOUS + ','}):
            with self.assertRaises(ValueError):
                self.config(origin=CANONICAL).validate()

    def test_ports_and_ip_origins_have_unambiguous_host_authorities(self):
        self.assertEqual(origin_host_authorities(CANONICAL),
                         {'arcturuschess.com', 'arcturuschess.com:443'})
        self.assertEqual(origin_host_authorities('http://127.0.0.1:8788'), {'127.0.0.1:8788'})
        self.assertEqual(origin_host_authorities('http://[::1]:8788'), {'[::1]:8788'})


class OriginBoundaryTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)

    def config(self, origin=CANONICAL, additional_origins=(PREVIOUS,)):
        return Config(data_dir=self.folder, origin=origin, additional_origins=additional_origins,
                      secure_cookies=True, smtp_host='', smtp_from='')

    def test_old_passwordless_session_survives_origin_change_and_cookies_stay_host_only(self):
        previous_app = create_app(self.config(origin=PREVIOUS, additional_origins=()))
        with TestClient(previous_app, base_url=PREVIOUS) as previous_client:
            response = previous_client.post('/api/auth/register', json={'name': 'Existing visitor'},
                                            headers={'Origin': PREVIOUS})
            self.assertEqual(response.status_code, 200, response.text)
            existing = response.json()
            cookies = previous_client.cookies
        app = create_app(self.config())
        with TestClient(app, base_url=PREVIOUS, cookies=cookies) as old_client, \
                closing(TestClient(app, base_url=CANONICAL, cookies=cookies)) as new_client:
            self.assertEqual(old_client.get('/api/auth/me').json()['user'], existing['user'])
            self.assertIsNone(new_client.get('/api/auth/me').json()['user'])
            for client in (old_client, new_client):
                response = client.get('/', follow_redirects=False)
                self.assertEqual(response.status_code, 200)
                self.assertNotIn('location', response.headers)
                self.assertEqual(client.get('/api/config').json()['canonical_origin'], CANONICAL)
            self.assertEqual(app.state.config.origin, CANONICAL)
            response = new_client.post('/api/auth/register', json={'name': 'New visitor'},
                                       headers={'Origin': CANONICAL})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertNotIn('domain=', response.headers['set-cookie'].lower())
            self.assertIn('secure', response.headers['set-cookie'].lower())
            self.assertEqual(old_client.get('/api/auth/me').json()['user'], existing['user'])
            response = old_client.post('/api/auth/logout', json={},
                headers={'Origin': PREVIOUS, 'X-CSRF-Token': existing['csrf_token']})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(new_client.get('/api/auth/me').json()['user']['name'], 'New visitor')

    def test_allowed_alias_never_permits_cross_host_or_foreign_origin_writes(self):
        app = create_app(self.config())
        with TestClient(app, base_url=PREVIOUS) as client:
            response = client.post('/api/auth/register', json={'name': 'Alias visitor'},
                                   headers={'Origin': PREVIOUS})
            self.assertEqual(response.status_code, 200)
            csrf = response.json()['csrf_token']
            for origin in (CANONICAL, 'https://foreign.invalid', 'null', PREVIOUS + '/',
                           'http://arcturus.astraplayschess.com'):
                with self.subTest(origin=origin):
                    response = client.post('/api/auth/logout', json={},
                        headers={'Origin': origin, 'X-CSRF-Token': csrf})
                    self.assertEqual(response.status_code, 403)
            self.assertEqual(client.post('/api/auth/logout', json={},
                headers={'Origin': PREVIOUS, 'X-CSRF-Token': 'wrong'}).status_code, 403)
            self.assertEqual(client.post('/api/auth/logout', json={},
                headers={'X-CSRF-Token': csrf}).status_code, 403)
            self.assertEqual(client.post('/api/auth/logout', json={}, headers=[
                ('Origin', PREVIOUS), ('Origin', CANONICAL), ('X-CSRF-Token', csrf)]).status_code, 403)
            self.assertIsNotNone(client.get('/api/auth/me').json()['user'])
        with closing(TestClient(app, base_url=CANONICAL)) as client:
            self.assertEqual(client.post('/api/auth/register', json={'name': 'Cross host'},
                headers={'Origin': PREVIOUS}).status_code, 403)

    def test_hosts_ports_and_duplicate_headers_must_match_explicit_allowlist(self):
        app = create_app(self.config())
        with TestClient(app, base_url=CANONICAL) as client:
            for host in ('arcturuschess.com', 'arcturuschess.com:443',
                         'arcturus.astraplayschess.com', 'ARCTURUSCHESS.COM'):
                self.assertEqual(client.get('/health', headers={'Host': host}).status_code, 200)
            for host in ('evil.invalid', 'astraplayschess.com', 'arcturuschess.com:8443',
                         'arcturuschess.com:80', 'arcturuschess.com.evil.invalid',
                         'arcturuschess.com@evil.invalid', 'arcturuschess.com.', ''):
                with self.subTest(host=host):
                    self.assertEqual(client.get('/health', headers={'Host': host}).status_code, 400)
            self.assertEqual(client.get('/health', headers=[('Host', 'arcturuschess.com'),
                ('Host', 'arcturus.astraplayschess.com')]).status_code, 400)
            self.assertEqual(client.get('/health', headers={'Host': 'evil.invalid',
                'X-Forwarded-Host': 'arcturuschess.com'}).status_code, 400)

    def test_original_single_origin_defaults_do_not_accept_aliases(self):
        app = create_app(self.config(origin='https://astraplayschess.com', additional_origins=()))
        with TestClient(app, base_url='https://astraplayschess.com') as client:
            self.assertEqual(client.get('/health').status_code, 200)
            for host in ('arcturuschess.com', 'arcturus.astraplayschess.com'):
                self.assertEqual(client.get('/health', headers={'Host': host}).status_code, 400)


if __name__ == '__main__':
    unittest.main()
