"""Historical HTML routes preserve archives and expose no repository directory."""
import base64
import hashlib
from html.parser import HTMLParser
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from astra_web.experiment_library import (
    EXPERIMENTS, INDEX_SOURCE, install_experiment_library,
)


class Document(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.game_links, self.links, self.script_texts = [], [], []
        self._script = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'a':
            self.links.append(attrs.get('href'))
            if 'game' in attrs.get('class', '').split():
                self.game_links.append(attrs.get('href'))
        if tag == 'script':
            self._script = []

    def handle_data(self, value):
        if self._script is not None:
            self._script.append(value)

    def handle_endtag(self, tag):
        if tag == 'script' and self._script is not None:
            self.script_texts.append(''.join(self._script))
            self._script = None


class ExperimentLibraryTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        install_experiment_library(app)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def test_collection_keeps_all_ten_historical_entries_with_local_links(self):
        before = INDEX_SOURCE.read_bytes()
        original = Document(before.decode('utf-8'))
        response = self.client.get('/experiments/')
        self.assertEqual(response.status_code, 200)
        hosted = Document(response.text)
        self.assertEqual(len(original.game_links), 10)
        self.assertEqual(len(hosted.game_links), 10)
        self.assertEqual(hosted.game_links,
                         [f'/experiments/{entry.filename}' for entry in EXPERIMENTS])
        self.assertEqual(original.game_links, [entry.original_url for entry in EXPERIMENTS])
        for url in hosted.game_links:
            self.assertEqual(self.client.get(url).status_code, 200, url)
            self.assertFalse(url.startswith('http'))
        self.assertNotIn('.netlify.app', response.text)
        self.assertIn('/games/', hosted.links)
        self.assertIn('/', hosted.links)
        self.assertIn('Ten recorded games', response.text)
        self.assertEqual(INDEX_SOURCE.read_bytes(), before)

    def test_all_standalone_replays_are_served_without_changing_history(self):
        for entry in EXPERIMENTS:
            with self.subTest(replay=entry.filename):
                before = entry.source.read_bytes()
                response = self.client.get(f'/experiments/{entry.filename}')
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.headers['content-type'].startswith('text/html'))
                self.assertEqual(response.text, entry.source.read_text(encoding='utf-8'))
                self.assertEqual(entry.source.read_bytes(), before)
                self.assertGreaterEqual(len(Document(response.text).script_texts), 2)

    def test_index_alias_and_trailing_slash(self):
        canonical = self.client.get('/experiments/')
        self.assertEqual(self.client.get('/experiments/index.html').text, canonical.text)
        self.assertEqual(self.client.get('/experiments').text, canonical.text)

    def test_nonallowlisted_files_and_traversal_do_not_expose_repository(self):
        for path in (
            '/experiments/replay-metadata.json', '/experiments/game.pgn',
            '/experiments/README.md', '/experiments/unknown.html',
            '/experiments/replay.html', '/experiments/../HANDOFF.md',
            '/experiments/%2e%2e%2fHANDOFF.md',
            '/experiments/%2e%2e%5cHANDOFF.md',
            '/experiments/%252e%252e%252fHANDOFF.md',
            '/experiments/../web-service/var/astra.sqlite3',
            '/experiments/C:%5cWindows%5cwin.ini',
        ):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)

    def test_script_policy_hashes_match_each_served_page(self):
        for entry in EXPERIMENTS:
            with self.subTest(replay=entry.filename):
                response = self.client.get(f'/experiments/{entry.filename}')
                policy = response.headers['content-security-policy']
                script_policy = next(rule.strip() for rule in policy.split(';')
                                     if rule.strip().startswith('script-src '))
                self.assertNotIn("'unsafe-inline'", script_policy)
                self.assertNotIn("'unsafe-eval'", script_policy)
                self.assertIn("connect-src 'none'", policy)
                self.assertIn("frame-ancestors 'none'", policy)
                scripts = Document(response.text).script_texts
                # Hash all inline blocks, including inert JSON data, so scripts
                # remain deterministic even if a browser treats that type oddly.
                for script in scripts:
                    digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
                    self.assertIn(f"'sha256-{digest}'", script_policy)


if __name__ == '__main__':
    unittest.main()
