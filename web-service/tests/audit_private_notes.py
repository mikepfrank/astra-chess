"""Actual Codex CLI: explicit public chat and retained private assistant notes.

Three actions use the same persistent synthetic thread across process restarts.
Every provider response is mocked. No live games, real keys, paid requests or
private reasoning are inspected. The receipt contains structure and hashes;
disposable Codex homes contain only this file's synthetic fixtures.
"""
import argparse
import asyncio
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from astra_web import codex_bridge as bridge
from astra_web.config import Config
from astra_web.openrouter_gateway import COMMENT_REMINDER, OpenRouterGateway
from astra_web.player_profiles import new_player_binding
from tests.audit_tool_visibility import checkout


GAME_ID = 'synthetic-private-notes'
LEGACY_PUBLIC_RULE = 'Only public assistant messages and chess_comment reach your opponent.'
REASONING_SENTINEL = 'Synthetic hidden reasoning fixture; never a host assistant note.'


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def private_text(action, final=False):
    if final:
        return f'Synthetic private final note for action {action}; the opponent cannot see this.'
    return (f'Synthetic private ordinary note for action {action}. '
            + 'Keep this ordinary assistant text in this game history. ' * 120
            + f'END-PRIVATE-NOTE-{action}')


def public_text(action):
    return f'Synthetic explicit public comment for action {action}.'


def response_stream(serial, action, step):
    if step == 1:
        items = [
            {'type': 'reasoning', 'id': f'rs-private-notes-{serial}',
             'summary': [{'type': 'summary_text', 'text': REASONING_SENTINEL}]},
            {'type': 'message', 'id': f'msg-private-notes-{serial}', 'role': 'assistant',
             'phase': 'commentary', 'status': 'completed', 'content': [
                 {'type': 'output_text', 'text': private_text(action), 'annotations': []}]},
            {'type': 'function_call', 'id': f'fc-private-notes-{serial}', 'status': 'completed',
             'call_id': f'call-private-notes-{serial}', 'name': 'chess_status', 'arguments': '{}'}]
    elif step == 2 and action != 1:
        items = [{'type': 'function_call', 'id': f'fc-private-notes-{serial}',
                  'status': 'completed', 'call_id': f'call-private-notes-{serial}',
                  'name': 'chess_comment', 'arguments': json.dumps({'text': public_text(action)})}]
    else:
        items = [{'type': 'message', 'id': f'msg-private-notes-{serial}', 'role': 'assistant',
                  'phase': 'final_answer', 'status': 'completed', 'content': [
                      {'type': 'output_text', 'text': private_text(action, final=True), 'annotations': []}]}]
    response_id = f'resp-private-notes-{serial}'
    events = [{'type': 'response.created', 'response': {
        'id': response_id, 'model': 'z-ai/glm-5.3-flash', 'status': 'in_progress'}}]
    for index, item in enumerate(items):
        initial = dict(item)
        if item['type'] == 'function_call':
            initial.update(status='in_progress', arguments='')
        elif item['type'] == 'message':
            initial.update(status='in_progress', content=[])
        events.append({'type': 'response.output_item.added', 'output_index': index, 'item': initial})
        if item['type'] == 'function_call':
            events.append({'type': 'response.function_call_arguments.delta', 'item_id': item['id'],
                           'output_index': index, 'delta': item['arguments']})
        elif item['type'] == 'message':
            events.append({'type': 'response.output_text.delta', 'item_id': item['id'],
                           'output_index': index, 'content_index': 0,
                           'delta': item['content'][0]['text']})
        events.append({'type': 'response.output_item.done', 'output_index': index, 'item': item})
    events.append({'type': 'response.completed', 'response': {
        'id': response_id, 'model': 'z-ai/glm-5.3-flash', 'status': 'completed', 'output': items,
        'usage': {'input_tokens': 100, 'output_tokens': 1600 if step == 1 else 40,
                  'total_tokens': 1700 if step == 1 else 140,
                  'input_tokens_details': {'cached_tokens': 0},
                  'output_tokens_details': {'reasoning_tokens': 10 if step == 1 else 0}, 'cost': 0}}})
    return (''.join('event: ' + event['type'] + '\ndata: ' + json.dumps(event) + '\n\n'
                    for event in events) + 'data: [DONE]\n\n').encode('utf-8')


def role_texts(items, role):
    texts = []
    for item in items:
        if not isinstance(item, dict) or item.get('role') != role:
            continue
        content = item.get('content', [])
        if isinstance(content, str):
            texts.append(content)
        elif isinstance(content, list):
            texts.extend(part['text'] for part in content if isinstance(part, dict)
                         and isinstance(part.get('text'), str))
    return texts


async def audit(codex, version, output, *, commit=None):
    if version not in bridge.reviewed_versions('openrouter-glm'):
        raise bridge.CodexError('Private-note audit requires an audited CLI version')
    revision, clean = checkout()
    if commit is not None and (revision != commit or not clean):
        raise bridge.CodexError('Private-note receipt requires the requested clean checkout')
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='private-notes-', dir=output))
    config = Config(data_dir=root, codex_bin=codex, model_profile='openrouter-glm', persona='arcturus')
    config.validate()
    binding = new_player_binding(config)
    # Model an existing game whose saved prompt still describes the old public
    # assistant-message transport. Runtime developer policy must supersede it.
    if LEGACY_PUBLIC_RULE not in binding['prompt']:
        binding['prompt'] += '\nSaved historical delivery rule: ' + LEGACY_PUBLIC_RULE + '\n'
        binding['profile']['prompt_sha256'] = digest(binding['prompt'])
    original = copy.deepcopy(binding)
    schema_digest = digest(json.dumps(bridge.dynamic_tools(), sort_keys=True, separators=(',', ':')))
    report = {'success': False, 'commit': revision, 'checkout_clean': clean,
              'exact_commit': False, 'cli_version': version,
              'external_provider_contacted': False, 'real_credentials_used': False,
              'old_saved_prompt_preserved': False, 'actions': [], 'requests': []}
    gateways, notes, public, calls, action_notes = [], [], [], [], []
    active_action = 0
    saved_reminder_pending = False
    action_had_public_comment = False
    request_counts = {1: 2, 2: 3, 3: 3}
    expected_reminders = {(1, 1): False, (1, 2): True,
                          (2, 1): True, (2, 2): True, (2, 3): False,
                          (3, 1): False, (3, 2): True, (3, 3): False}

    class FixtureGateway(OpenRouterGateway):
        def __init__(self, key, **kwargs):
            assert key == 'synthetic-private-notes-key'
            assert kwargs['expected_instructions'] == original['prompt']
            self.fixture_count = 0
            super().__init__(key, **kwargs, transport=httpx.MockTransport(self.upstream),
                             budget_check=lambda _: {'remaining_usd': 49})
            gateways.append(self)

        async def upstream(self, request):
            self.fixture_count += 1
            assert self.fixture_count <= request_counts[active_action], 'Unexpected extra provider request'
            body = json.loads(request.content)
            assert body['model'] == original['profile']['model']
            assert body['reasoning'] == {'effort': 'high'}
            assert body['max_output_tokens'] == 32768
            assert body['instructions'] == original['prompt']
            assert {tool['name'] for tool in body['tools']} == bridge.TOOL_NAMES
            items = body.get('input', [])
            assert isinstance(items, list)
            developer = '\n'.join(role_texts(items, 'developer'))
            # The production policy is checked on the actual API wire, not
            # merely in the app-server request or locally generated config.
            policy = bridge._developer_instructions(original)
            assert 'Only text sent through chess_comment' in policy
            assert policy in developer, 'Runtime communication policy missing from provider input'
            reminder_expected = expected_reminders[(active_action, self.fixture_count)]
            reminders = [item for item in items
                         if COMMENT_REMINDER in role_texts([item], 'developer')]
            assert len(reminders) == int(reminder_expected), 'Conditional reminder presence is incorrect'
            if reminder_expected:
                assert reminders[0] is items[-1], 'Conditional reminder must be last in provider input'
                assert role_texts([items[-1]], 'developer') == [COMMENT_REMINDER]
            assistant = role_texts(items, 'assistant')
            if self.fixture_count >= 2:
                assert private_text(active_action) in assistant, 'Same-turn private text was not retained'
            for prior_action in range(1, active_action):
                assert private_text(prior_action) in assistant, 'Private note was not retained across process restart'
                assert private_text(prior_action, final=True) in assistant, 'Private final was not retained across restart'
            serial = len(report['requests']) + 1
            report['requests'].append({'action': active_action, 'request': self.fixture_count,
                'developer_policy_on_wire': True, 'developer_sha256': digest(developer),
                'conditional_reminder_expected': reminder_expected,
                'conditional_reminder_final_developer_item': reminder_expected,
                'conditional_reminder_verified': True,
                'saved_base_prompt_unchanged': True,
                'assistant_history_items': len(assistant),
                'current_private_note_retained': self.fixture_count >= 2,
                'previous_private_notes_retained': active_action > 1,
                'input_sha256': digest(json.dumps(items, sort_keys=True))})
            return httpx.Response(200, headers={'content-type': 'text/event-stream'},
                content=response_stream(serial, active_action, self.fixture_count))

    async def emit(text):
        public.append(text)

    async def handler(name, args):
        nonlocal saved_reminder_pending, action_had_public_comment
        if name == '_assistant_note':
            assert set(args) == {'id', 'text', 'phase'}
            assert isinstance(args['id'], str) and args['id']
            assert args['phase'] in (None, 'commentary', 'final_answer')
            assert args['text'] in (private_text(active_action), private_text(active_action, final=True))
            assert REASONING_SENTINEL not in args['text']
            notes.append(copy.deepcopy(args))
            action_notes.append(active_action)
            if not action_had_public_comment:
                saved_reminder_pending = True
            return {'recorded': True}
        if name == 'chess_status':
            calls.append(name)
            return {'fixture': True, 'ply': 0, 'remaining_turn_seconds': 600,
                    'messages': [{'author': 'human', 'text': 'Synthetic opponent message.'}]}
        if name == 'chess_comment':
            assert args == {'text': public_text(active_action)}
            calls.append(name)
            await emit(args['text'])
            action_had_public_comment = True
            saved_reminder_pending = False
            return {'sent': True}
        assert name in {'_thread', '_usage', '_compaction'}, 'Unexpected host callback'
        return {}

    player = bridge.CodexPlayer(config)
    thread_id = None
    try:
        with patch.dict(os.environ, {'OPENROUTER_API_KEY': 'synthetic-private-notes-key'}), \
                patch('astra_web.openrouter_setup.require_budget', return_value={'remaining_usd': 49}), \
                patch('astra_web.openrouter_gateway.OpenRouterGateway', FixtureGateway):
            for active_action in (1, 2, 3):
                action_had_public_comment = False
                assert saved_reminder_pending == (active_action == 2)
                async with asyncio.timeout(45):
                    result = await player.run(GAME_ID, {'ply': 0, 'hard_response_seconds': 600,
                        'comment_reminder_pending': saved_reminder_pending},
                        handler, emit, thread_id, player_binding=binding, response_kind='chat',
                        move_reasoning='max')
                if thread_id is not None:
                    assert result['thread_id'] == thread_id
                thread_id = result['thread_id']
                state = json.loads((root / 'players' / GAME_ID / 'bridge-state.json').read_text())
                assert state['player_profile'] == original['profile']
                assert state['cli_version'] == version
                assert not player._processes and not player._active_games
                report['actions'].append({'action': active_action, 'same_thread': state['thread_id'] == thread_id,
                    'immutable_identity_preserved': True, 'process_reaped': True,
                    'saved_reminder_pending': saved_reminder_pending})
        assert binding == original
        assert schema_digest == digest(json.dumps(bridge.dynamic_tools(), sort_keys=True, separators=(',', ':')))
        assert public == [public_text(2), public_text(3)]
        assert [note['text'] for note in notes] == [text for action in (1, 2, 3)
                                                  for text in (private_text(action), private_text(action, final=True))]
        assert action_notes == [1, 1, 2, 2, 3, 3]
        assert calls == ['chess_status', 'chess_status', 'chess_comment', 'chess_status', 'chess_comment']
        assert len(report['requests']) == 8
        assert not saved_reminder_pending, 'A final note after a public comment must not rearm the reminder'
        assert len(private_text(1)) > bridge.MAX_PUBLIC_TEXT
        assert all(gateway.request_count == request_counts[action]
                   and gateway.budget_check_count == request_counts[action]
                   and not gateway.rejections and all(row.get('stream_complete') for row in gateway.evidence)
                   for action, gateway in enumerate(gateways, start=1))
        final_revision, final_clean = checkout()
        exact = commit is not None and revision == final_revision == commit and clean and final_clean
        assert revision == final_revision and (commit is None or exact)
        report.update(success=True, checkout_clean=clean and final_clean, exact_commit=exact,
            old_saved_prompt_preserved=True, saved_prompt_sha256=digest(original['prompt']),
            dynamic_tool_schema_unchanged=True, public_comment_count=len(public),
            private_note_count=len(notes), reasoning_never_published_or_persisted_as_note=True,
            private_note_characters=[len(note['text']) for note in notes],
            private_note_sha256=[digest(note['text']) for note in notes],
            long_private_note_exceeds_public_limit=True, completed_actions=3,
            conditional_comment_reminder_verified=True,
            request_count=len(report['requests']), private_history_survived_restart=True)
    finally:
        await player.close()
        (output / 'private-notes.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex', required=True)
    parser.add_argument('--candidate-version', default='0.154.0')
    parser.add_argument('--audit-dir', type=Path, required=True)
    parser.add_argument('--receipt', type=Path)
    parser.add_argument('--commit')
    args = parser.parse_args(argv)
    if args.commit is not None and not re.fullmatch('[0-9a-f]{40}', args.commit):
        parser.error('--commit must be a full lowercase Git SHA')
    report = asyncio.run(audit(args.codex, args.candidate_version, args.audit_dir, commit=args.commit))
    if args.receipt is not None:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items() if key not in {'requests', 'actions'}}, indent=2))
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
