"""Audit public Arcturus domains without credentials or authenticated writes.

All reads use verified HTTPS. The only POSTs are anonymous logout rejection
probes: no Cookie, Authorization or CSRF token is supplied or retained. They
must fail origin/CSRF validation. No games, accounts, model turns or emails are
created. Merely importing this module, or running --help, makes no requests.
"""
import argparse
from html.parser import HTMLParser
import http.client
import json
import re
import ssl
import sys


HOSTS = ('arcturuschess.com', 'arcturus.astraplayschess.com')
WWW_HOST = 'www.arcturuschess.com'
ORIGINAL_HOST = 'astraplayschess.com'
CANONICAL_ORIGIN = 'https://' + HOSTS[0]
MAX_RESPONSE_BYTES = 8 * 1024 * 1024


class AuditFailure(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise AuditFailure(message)


def request(host, path, *, timeout=12, method='GET', headers=None, body=None):
    # Keep this operator check deliberately narrower than a general HTTP client.
    require(host in (*HOSTS, WWW_HOST, ORIGINAL_HOST), 'Unexpected audit host')
    require(method == 'GET' or (method == 'POST' and path == '/api/auth/logout'),
            'Only public reads and anonymous logout rejection probes are allowed')
    require(not any(name.lower() in ('cookie', 'authorization', 'x-csrf-token')
                    for name in (headers or {})), 'This audit must remain unauthenticated')
    connection = http.client.HTTPSConnection(host, timeout=timeout,
                                             context=ssl.create_default_context())
    try:
        connection.request(method, path, headers=headers or {}, body=body)
        response = connection.getresponse()
        content = response.read(MAX_RESPONSE_BYTES + 1)
        require(len(content) <= MAX_RESPONSE_BYTES, 'Public response exceeded the audit size bound')
        return response.status, {name.lower(): value for name, value in response.getheaders()}, content
    finally:
        connection.close()


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = []

    def handle_starttag(self, tag, attrs):
        href = dict(attrs).get('href', '')
        if tag == 'a' and re.fullmatch(r'/games/[A-Za-z0-9_-]+\.html', href):
            if href not in self.paths:
                self.paths.append(href)


def audit(*, timeout=12, max_replays=20, expected_reasoning='max', allow_empty_library=False):
    require(0 < timeout <= 60, 'Timeout must be greater than zero and at most 60 seconds')
    require(type(max_replays) is int and 1 <= max_replays <= 100, 'Replay bound must be between 1 and 100')
    require(expected_reasoning in ('high', 'max'), 'Expected move reasoning must be high or max')
    configs, libraries, results = [], [], {}

    def fetch(host, path, **kwargs):
        return request(host, path, timeout=timeout, **kwargs)

    for host in HOSTS:
        status, _, content = fetch(host, '/health')
        require(status == 200 and json.loads(content) == {'ok': True}, host + ' health failed')
        status, _, content = fetch(host, '/api/config')
        require(status == 200, host + ' configuration request failed')
        config = json.loads(content)
        configs.append(config)
        require(config['canonical_origin'] == CANONICAL_ORIGIN, host + ' canonical origin differs')
        require(config['player_name'] == 'Arcturus' and config['reasoning'] == expected_reasoning,
                host + ' player name or default move reasoning differs')
        status, headers, content = fetch(host, '/')
        require(status == 200 and b'site-address-notice' in content, host + ' board/alias notice differs')
        require("frame-ancestors 'none'" in headers.get('content-security-policy', ''),
                host + ' frame protection is absent')
        status, _, content = fetch(host, '/games/')
        require(status == 200, host + ' public replay library request failed')
        libraries.append(content)
        cross = HOSTS[1] if host == HOSTS[0] else HOSTS[0]
        for origin in ('https://' + cross, 'https://foreign.invalid'):
            status, _, content = fetch(host, '/api/auth/logout', method='POST',
                headers={'Origin': origin, 'Content-Type': 'application/json'}, body='{}')
            require(status == 403 and json.loads(content)['detail'] == 'Origin is not allowed.',
                    host + ' accepted an unexpected cross-origin request')
        status, _, content = fetch(host, '/api/auth/logout', method='POST',
            headers={'Origin': 'https://' + host, 'Content-Type': 'application/json'}, body='{}')
        require(status == 403 and 'Session verification failed' in json.loads(content)['detail'],
                host + ' did not require session/CSRF verification')
        results[host] = dict(https_verified=True, healthy=True, config_verified=True,
            library_http_200=True, cross_host_and_foreign_origin_blocked=True, csrf_required=True)

    require(configs[0] == configs[1], 'Canonical and alias configuration differ')
    require(libraries[0] == libraries[1], 'Canonical and alias public libraries differ')
    links = Links()
    links.feed(libraries[0].decode('utf-8'))
    require(links.paths or allow_empty_library, 'No public replays found; use --allow-empty-library if expected')
    checked = links.paths[:max_replays]
    for path in checked:
        pages = [fetch(host, path) for host in HOSTS]
        require(all(page[0] == 200 for page in pages), 'Public replay request failed: ' + path)
        require(pages[0][2] == pages[1][2], 'Canonical and alias public replay differ: ' + path)
        require(b'Arcturus' in pages[0][2], 'Arcturus name missing from public replay: ' + path)
    status, headers, _ = fetch(WWW_HOST, '/games/?check=domain&value=two')
    require(status == 308 and headers.get('location') == CANONICAL_ORIGIN + '/games/?check=domain&value=two',
            'WWW redirect failed to preserve the requested URI')
    status, _, content = fetch(ORIGINAL_HOST, '/health')
    require(status == 200 and json.loads(content) == {'ok': True}, 'Original Astra health failed')
    return dict(hosts=results, public_replays_found=len(links.paths),
        shared_public_replay_count=len(checked), replay_check_limit=max_replays,
        checked_public_replays_identical_on_both_hosts=True, www_308_preserves_uri=True,
        original_astra_healthy=True, authenticated_requests=0, paid_model_calls=0, emails_sent=0)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--timeout', type=float, default=12, help='Per-request timeout in seconds (maximum 60)')
    parser.add_argument('--max-replays', type=int, default=20, help='Maximum public replay pages to compare (1-100)')
    parser.add_argument('--expect-reasoning', choices=('high', 'max'), default='max',
                        help='Expected public default move reasoning; independent of chat reasoning')
    parser.add_argument('--allow-empty-library', action='store_true', help='Permit a site with no published replays')
    args = parser.parse_args(argv)
    try:
        result = audit(timeout=args.timeout, max_replays=args.max_replays,
                       expected_reasoning=args.expect_reasoning, allow_empty_library=args.allow_empty_library)
    except (AuditFailure, OSError, http.client.HTTPException, KeyError, UnicodeError, json.JSONDecodeError) as error:
        print('Public Arcturus audit failed: ' + str(error), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
