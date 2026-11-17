#!/usr/bin/env python3
"""One synthetic 16-token GPT-2 turn behind the public generation gate.

Generation is submitted once over loopback; SSE is consumed through actual
certificate-verified public HTTPS/Caddy. No browser chat is accessed. Default
only checks health. --run-authorized also requires a fresh private evidence
directory; request intent and bearer job ID are retained there without stdout.
"""
from pathlib import Path
import argparse
import copy
import datetime
import http.client
import json
import os
import re
import time

MAX_BODY = 5 * 1024 * 1024
MAX_FRAME = 1024 * 1024


def require(value, message):
    if not value:
        raise RuntimeError(message)


def normalized(value):
    result = copy.deepcopy(value)
    result.pop('exported_at', None)
    return result


def read_events(response, deadline):
    frame = []
    size = 0
    while time.monotonic() < deadline:
        line = response.readline(MAX_FRAME + 1)
        if not line:
            return
        size += len(line)
        require(size <= MAX_FRAME, 'SSE frame too large')
        if line.rstrip(b'\r\n'):
            frame.append(line.decode('utf-8'))
            continue
        fields = {}
        data = []
        for item in frame:
            if item.startswith(':'):
                continue
            key, _, value = item.rstrip('\r\n').partition(':')
            value = value.removeprefix(' ')
            if key == 'data':
                data.append(value)
            elif key in ('event', 'id'):
                fields[key] = value
        frame, size = [], 0
        if data:
            yield fields.get('event'), fields.get('id'), json.loads('\n'.join(data))
    raise RuntimeError('SSE overall deadline exceeded')


def request(path, body=None, expected=200):
    connection = http.client.HTTPConnection('127.0.0.1', 8899, timeout=15)
    headers = {'Host': 'gpt2-chat.com', 'Origin': 'https://gpt2-chat.com',
               'Content-Type': 'application/json'}
    try:
        connection.request('GET' if body is None else 'POST', path,
                           body=None if body is None else json.dumps(body), headers=headers)
        response = connection.getresponse()
        require(response.status == expected, 'Unexpected loopback API status')
        data = response.read(MAX_BODY + 1)
        require(len(data) <= MAX_BODY, 'API response too large')
        result = json.loads(data)
        require(isinstance(result, dict), 'API response must be an object')
        return result
    finally:
        connection.close()


def health():
    value = request('/api/health')
    require(value['status'] == 'ready' and value['queue'] == {'waiting': 0, 'running': False},
            'Public service must be ready and idle')
    model = value['model']
    require(model['id'] == 'openai-community/gpt2-xl'
            and model['revision'] == '15ea56dee5df4983c59b2538573817e1667135e2'
            and model['precision'] == 'FP32' and model['device'] == 'cpu'
            and model['context_tokens'] == 1024, 'Unexpected GPT-2 model baseline')
    require(value['capabilities']['streaming'] is True, 'Streaming must be enabled')
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-authorized', action='store_true')
    parser.add_argument('--evidence-dir', type=Path)
    args = parser.parse_args()
    before = health()
    if not args.run_authorized:
        print(json.dumps({'ready': True, 'generation_posts': 0, 'max_new_tokens': 16}))
        return
    require(args.evidence_dir and args.evidence_dir.is_absolute()
            and args.evidence_dir.parent.resolve() == Path('/var/lib/gpt2-codex-ops'),
            'Use a fresh evidence directory directly under /var/lib/gpt2-codex-ops')
    os.umask(0o077)
    args.evidence_dir.mkdir(mode=0o700)
    evidence = {'started_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'generation_posts': 0, 'job_id': None}
    def save():
        (args.evidence_dir / 'private-evidence.json').write_text(json.dumps(evidence, indent=2))
    save()
    controls = {'temperature': 0, 'max_new_tokens': 16, 'seed': '42'}
    initial = request('/api/new', {'example_rounds': 0,
                                  'date': datetime.date.today().isoformat(),
                                  'settings': controls})
    require(not initial['chat']['blocks'] and not initial['turns'], 'Expected fresh synthetic chat')
    original = copy.deepcopy(initial['chat'])
    body = {'chat': original, 'message': 'Please describe a chessboard.', 'settings': controls}
    preview = request('/api/preview', body)
    started = time.monotonic()
    deadline = started + 180
    # Intent is durable before POST. Never repeat an uncertain generation POST.
    evidence['generation_posts'] = 1
    save()
    ack = request('/api/message', body, 202)
    identifier = ack.get('job_id')
    require(isinstance(identifier, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,64}', identifier), 'Invalid job acknowledgement')
    evidence['job_id'] = identifier
    save()
    cursor = -1
    tokens = 0
    prefix = ''
    events = []
    completed = False
    for _ in range(3):
        connection = http.client.HTTPSConnection('gpt2-chat.com', timeout=15)
        try:
            headers = {'Accept': 'text/event-stream'}
            if cursor >= 0:
                headers['Last-Event-ID'] = str(cursor)
            connection.request('GET', '/api/jobs/' + identifier + '/events', headers=headers)
            response = connection.getresponse()
            require(response.status == 200 and response.getheader('Content-Type', '').startswith('text/event-stream'),
                    'Caddy HTTPS SSE response failed')
            for kind, serial, payload in read_events(response, deadline):
                require(payload['version'] == 1 and str(payload['seq']) == serial and payload['seq'] >= cursor,
                        'Invalid SSE sequence')
                cursor = payload['seq']
                events.append(kind)
                if kind in ('complete', 'failed'):
                    require(kind == 'complete', 'Synthetic generation failed')
                    completed = True
                    break
                require(kind == 'progress' and tokens <= payload['generated_tokens'] <= 16
                        and payload['reply_text'].startswith(prefix), 'Invalid cumulative stream progress')
                tokens, prefix = payload['generated_tokens'], payload['reply_text']
            if completed:
                break
        finally:
            connection.close()
    require(completed, 'SSE did not complete within its bounded subscriptions')
    result = request('/api/jobs/' + identifier)
    require(result['status'] == 'complete', 'Canonical result is not complete')
    state = result['state']
    generation = state['last_generation']
    require(len(state['turns']) == 1 and len(state['chat']['blocks']) == 2,
            'Expected exactly one completed turn')
    require(generation['max_new_tokens'] == 16 and 0 <= generation['output_tokens'] <= 16
            and generation['prompt_text'] == preview['context_text'], 'Generation cap or prompt changed')
    require(original == initial['chat'], 'Original archive changed')
    time.sleep(1.1)
    require(request('/api/jobs/' + identifier) == result, 'Repeated canonical result changed')
    exported = request('/api/export', {'chat': state['chat']})
    imported = request('/api/import', {'chat': exported})
    require(normalized(imported['chat']) == normalized(exported), 'Export/import round trip failed')
    after = health()
    summary = {'passed': True, 'generation_posts': 1, 'max_new_tokens': 16,
               'output_tokens': generation['output_tokens'], 'sse_through_public_https': True,
               'sse_event_types': events, 'repeat_result_unchanged': True, 'export_import_roundtrip': True,
               'queue_after': after['queue'], 'elapsed_seconds': round(time.monotonic() - started, 3)}
    evidence.update(summary=summary, final_job=result)
    save()
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'passed': False, 'error_type': type(error).__name__,
                          'detail': str(error) if type(error) is RuntimeError else 'Inspect private on-host evidence'}))
        raise SystemExit(1)
