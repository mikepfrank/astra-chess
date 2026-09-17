"""Literal, complete and privately owned rich-text transcript downloads."""
from contextlib import ExitStack, closing
import copy
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from astra_web.app import create_app
from astra_web import chess_game as game
from astra_web.chat_export import _rtf_text, transcript_rtf
from astra_web.config import Config


def plain_rtf(raw):
    """Independent small reader for the generated text/control vocabulary.

    It deliberately leaves font-table text in the result; tests match transcript
    content rather than claiming to replace an actual word-processor renderer.
    """
    source = raw.decode('ascii') if isinstance(raw, bytes) else raw
    chars = []
    pos = 0
    while pos < len(source):
        char = source[pos]
        pos += 1
        if char in '{}\r\n':
            continue
        if char != '\\':
            chars.append(char)
            continue
        if source[pos] in '\\{}':
            chars.append(source[pos])
            pos += 1
            continue
        match = re.match(r'([a-z]+)(-?\d+)? ?', source[pos:])
        if not match:
            raise AssertionError('Unexpected RTF control syntax')
        word, number = match.groups()
        pos += len(match[0])
        if word == 'u':
            chars.append(chr(int(number) % 65536))
            if source[pos:pos + 1] != '?':
                raise AssertionError('Missing Unicode fallback character')
            pos += 1
        elif word in ('line', 'par'):
            chars.append('\n')
        elif word == 'tab':
            chars.append('\t')
    return ''.join(chars).encode('utf-16-le', 'surrogatepass').decode('utf-16-le', 'replace')


def fixture():
    return dict(name='Dr. Thanos', human_side='white', astra_side='black',
                player_persona={'display_name': 'Arcturus'},
                created_at=0, status='finished', result='0-1', termination='checkmate',
                moves=[{'san': 'e4', 'actor': 'human', 'at': 100},
                       {'san': 'e5', 'actor': 'astra', 'at': 200}],
                messages=[{'author': 'human', 'text': 'Before we start.', 'ply': 0, 'created_at': 90},
                          {'author': 'astra', 'text': 'Reply after White.', 'ply': 1, 'created_at': 110},
                          {'author': 'human', 'text': 'Question after Black.', 'ply': 2, 'created_at': 210},
                          {'author': 'astra', 'text': 'Post-game reply.', 'ply': 2, 'created_at': 220}])


class ChatExportTests(unittest.TestCase):
    def test_full_interleaving_notation_names_dates_result_and_source_preserved(self):
        state = fixture()
        before = copy.deepcopy(state)
        raw = transcript_rtf(state)
        self.assertTrue(raw.startswith(b'{\\rtf1'))
        self.assertTrue(raw.endswith(b'}'))
        text = plain_rtf(raw)
        ordered = ['Before we start.', '1.e4  |  Dr. Thanos (White)',
                   'Reply after White.', '1...e5  |  Arcturus (Black)',
                   'Question after Black.', 'Post-game reply.']
        self.assertEqual(sorted(text.index(item) for item in ordered),
                         [text.index(item) for item in ordered])
        for item in ['Dr. Thanos vs. Arcturus', 'White: Dr. Thanos    Black: Arcturus',
                     '1970-01-01 00:00:00 UTC', '1970-01-01 00:03:40 UTC',
                     'Status: Finished    Result: 0-1 (Arcturus won)', 'Ending: checkmate']:
            self.assertIn(item, text)
        self.assertEqual(state, before)

    def test_committed_ply_and_append_order_override_ties_and_backwards_clocks(self):
        state = fixture()
        # Deliberately contradictory timestamps must not reorder accepted events.
        state['moves'][0]['at'] = 900
        state['moves'][1]['at'] = 100
        for index, message in enumerate(state['messages']):
            message['created_at'] = 900 if index < 2 else 1
        text = plain_rtf(transcript_rtf(state))
        ordered = ['Before we start.', '1.e4', 'Reply after White.', '1...e5',
                   'Question after Black.', 'Post-game reply.']
        self.assertEqual([text.index(item) for item in ordered],
                         sorted(text.index(item) for item in ordered))

    def test_human_black_ai_white_move_and_chat_names_follow_saved_sides(self):
        state = fixture()
        state.update(human_side='black', astra_side='white', result='1-0')
        state['moves'][0]['actor'] = 'astra'
        state['moves'][1]['actor'] = 'human'
        text = plain_rtf(transcript_rtf(state))
        self.assertIn('White: Arcturus    Black: Dr. Thanos', text)
        self.assertIn('1.e4  |  Arcturus (White)', text)
        self.assertIn('1...e5  |  Dr. Thanos (Black)', text)
        self.assertIn('Result: 1-0 (Arcturus won)', text)
        self.assertIn('Arcturus | 1970-01-01 00:01:50 UTC\nReply after White.', text)
        self.assertIn('Dr. Thanos | 1970-01-01 00:03:30 UTC\nQuestion after Black.', text)

    def test_legacy_missing_or_invalid_ply_uses_timestamp_without_dropping_messages(self):
        state = fixture()
        state['messages'] = [
            {'author': 'human', 'text': 'Legacy before', 'created_at': 50},
            {'author': 'human', 'text': 'Legacy tie', 'created_at': 100},
            {'author': 'astra', 'text': 'Legacy between', 'ply': '1', 'created_at': 150},
            {'author': 'human', 'text': 'Legacy after', 'ply': -5, 'created_at': 210},
            {'author': 'astra', 'text': 'Legacy undated', 'ply': 999},
        ]
        text = plain_rtf(transcript_rtf(state))
        ordered = ['Legacy before', '1.e4', 'Legacy tie', 'Legacy between',
                   '1...e5', 'Legacy after', 'Legacy undated']
        self.assertEqual([text.index(item) for item in ordered],
                         sorted(text.index(item) for item in ordered))
        self.assertIn('Time unavailable', text)
        self.assertIn('Their placement is inferred from timestamps', text)
        self.assertIn('5 chat messages.', text)

    def test_all_messages_including_large_unicode_postgame_comments_are_exported(self):
        state = fixture()
        comment = ('é — Ω 棋 🐂 ' * 220) + '\n**Literal Markdown**\nSecond paragraph.'
        state['messages'] = [{'author': 'human', 'text': f'Comment {index}: {comment}',
                              'ply': 2, 'created_at': 300 + index} for index in range(40)]
        text = plain_rtf(transcript_rtf(state))
        for message in state['messages']:
            self.assertIn(message['text'], text)
        self.assertIn('40 chat messages.', text)

    def test_unicode_escapes_surrogates_and_literal_rtf_injection(self):
        malicious = '{\\field{\\*\\fldinst INCLUDETEXT "secret"}}\\par\\object'
        literal = 'é — Ω 棋 🐂 ' + malicious + '\nLine two\tTabbed'
        encoded = _rtf_text(literal)
        self.assertEqual(plain_rtf(encoded), literal)
        self.assertIn('\\u-10179?\\u-9214?', encoded)  # U+1F402 ox, signed surrogate pair.
        self.assertIn('\\{\\\\field', encoded)
        encoded.encode('ascii')
        state = fixture()
        state['name'] = malicious
        state['messages'][0]['text'] = literal
        text = plain_rtf(transcript_rtf(state))
        self.assertIn(literal, text)
        self.assertIn(malicious + ' vs. Arcturus', text)

    def test_line_endings_and_control_characters_do_not_create_rtf_commands(self):
        self.assertEqual(plain_rtf(_rtf_text('A\r\nB\rC\x00D\x01E\x7fF')),
                         'A\nB\nC�D�E�F')

    def test_active_suspended_empty_and_historical_persona_metadata(self):
        state = fixture()
        state.update(moves=[], messages=[], status='active', result='*', termination='')
        for status, expected in (('active', 'In progress'), ('suspended', 'Suspended')):
            state['status'] = status
            text = plain_rtf(transcript_rtf(state))
            self.assertIn(f'Status: {expected}    Result: Not decided', text)
            self.assertIn('No moves or chat messages have been recorded yet.', text)
        state.pop('player_persona')
        state['player_profile'] = {'display_name': 'Earlier GLM persona'}
        self.assertIn('Dr. Thanos vs. Earlier GLM persona', plain_rtf(transcript_rtf(state)))
        state.pop('player_profile')
        self.assertIn('Dr. Thanos vs. Astra', plain_rtf(transcript_rtf(state)))

    def test_only_public_fields_reach_export(self):
        state = fixture()
        for field in ('user_id', 'thread_id', 'player_prompt', 'queries', 'decisions',
                      'candidates', 'clock_events', 'worker', 'model', 'engine_fingerprint'):
            state[field] = f'PRIVATE-{field}'
        state['moves'][0]['private_search'] = 'PRIVATE-move-search'
        state['messages'][0]['internal_trace'] = 'PRIVATE-message-trace'
        text = plain_rtf(transcript_rtf(state))
        self.assertNotIn('PRIVATE-', text)
        self.assertIn('Before we start.', text)

    def test_notes_require_opt_in_and_default_public_transcript_is_unchanged(self):
        state = fixture()
        public = transcript_rtf(state)
        state['assistant_notes'] = [dict(id='private-note-id', text='Saved ordinary assistant note.',
            phase='commentary', ply=2, created_at=215, after_message_id=None)]
        self.assertEqual(transcript_rtf(state), public)
        self.assertEqual(transcript_rtf(state, include_notes=False), public)
        included = plain_rtf(transcript_rtf(state, include_notes=True))
        self.assertIn('[AI internal note — not sent to sidebar]', included)
        self.assertIn('Saved ordinary assistant note.', included)
        self.assertIn('1 AI internal notes.', included)
        self.assertNotIn('private-note-id', included)
        # Earlier ordinary assistant messages already in the public stream stay public.
        self.assertIn('Post-game reply.', plain_rtf(public))

    def test_note_anchors_and_ply_interleave_without_timestamp_reordering(self):
        state = fixture()
        for index, message in enumerate(state['messages']):
            message['id'] = f'm{index}'
        state['assistant_notes'] = [
            dict(text='Note before any chat.', ply=0, created_at=999, after_message_id=None),
            dict(text='Note after pregame chat.', ply=0, created_at=1, after_message_id='m0'),
            dict(text='Note after White before reply.', ply=1, created_at=999, after_message_id='m0'),
            dict(text='Note after White reply.', ply=1, created_at=1, after_message_id='m1'),
            dict(text='Note after Black before question.', ply=2, created_at=999, after_message_id='m1'),
            dict(text='First note after question.', ply=2, created_at=219, after_message_id='m2'),
            dict(text='Second note after question.', ply=2, created_at=1, after_message_id='m2'),
            dict(text='Last postgame note.', ply=2, created_at=2, after_message_id='m3'),
        ]
        before = copy.deepcopy(state)
        text = plain_rtf(transcript_rtf(state, include_notes=True))
        ordered = ['Note before any chat.', 'Before we start.', 'Note after pregame chat.',
                   '1.e4', 'Note after White before reply.', 'Reply after White.',
                   'Note after White reply.', '1...e5', 'Note after Black before question.',
                   'Question after Black.', 'First note after question.',
                   'Second note after question.', 'Post-game reply.', 'Last postgame note.']
        self.assertEqual([text.index(item) for item in ordered],
                         sorted(text.index(item) for item in ordered))
        self.assertEqual(text.count('[AI internal note — not sent to sidebar]'), 8)
        self.assertEqual(state, before)

    def test_notes_with_missing_anchors_use_timestamp_fallback_without_dropping_text(self):
        state = fixture()
        for index, message in enumerate(state['messages']):
            message['id'] = f'm{index}'
        state['assistant_notes'] = [
            dict(text='Unknown anchor note.', ply=2, created_at=215, after_message_id='missing'),
            dict(text='Timestamp tie note.', ply=2, created_at=220),
            dict(text='Undated note.', ply=2),
            dict(text='Legacy missing-ply note.', created_at=150, after_message_id='m1'),
        ]
        text = plain_rtf(transcript_rtf(state, include_notes=True))
        ordered = ['Reply after White.', 'Legacy missing-ply note.', '1...e5',
                   'Question after Black.', 'Unknown anchor note.', 'Post-game reply.',
                   'Timestamp tie note.', 'Undated note.']
        self.assertEqual([text.index(item) for item in ordered],
                         sorted(text.index(item) for item in ordered))

    def test_internal_note_is_literal_unicode_and_no_extra_private_metadata_is_exported(self):
        state = fixture()
        text = '🐂 棋 Ω {\\field{\\*\\fldinst INCLUDETEXT "secret"}}\\par\\object\nSecond line.'
        state['assistant_notes'] = [dict(id='PRIVATE-note-id', text=text,
            phase='PRIVATE-phase', ply=2, created_at=215, after_message_id='PRIVATE-message-id',
            reasoning='PRIVATE-reasoning', model='PRIVATE-model', prompt='PRIVATE-prompt')]
        raw = transcript_rtf(state, include_notes=True)
        decoded = plain_rtf(raw)
        self.assertIn(text, decoded)
        self.assertNotIn('PRIVATE-', decoded)
        self.assertIn(r'\cf3\i ', raw.decode('ascii'))
        self.assertIn(r'\i0\cf1\par', raw.decode('ascii'))
        self.assertNotIn(text, plain_rtf(transcript_rtf(state)))

    def test_internal_notes_export_rejects_unfinished_games_and_accepts_legacy_absence(self):
        state = fixture()
        included = plain_rtf(transcript_rtf(state, include_notes=True))
        self.assertIn('0 AI internal notes.', included)
        self.assertIn('Earlier notes may not have been recorded.', included)
        for status in ('active', 'suspended'):
            state['status'] = status
            with self.assertRaisesRegex(ValueError, 'after the game has finished'):
                transcript_rtf(state, include_notes=True)
            self.assertIn('Post-game reply.', plain_rtf(transcript_rtf(state)))


class ChatExportApiTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        folder = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.config = Config(data_dir=Path(folder), origin='http://testserver',
            model_profile='openrouter-glm', persona='arcturus', player_mode='disabled',
            secure_cookies=False, smtp_host='', smtp_from='')
        self.app = create_app(self.config)
        self.client = self.stack.enter_context(TestClient(self.app))
        self.register(self.client, 'Export owner')
        response = self.client.post('/api/games', json={'side': 'white'})
        self.assertEqual(response.status_code, 201)
        self.game_id = response.json()['id']
        self.store = self.app.state.store
        self.url = f'/api/games/{self.game_id}/chat.rtf'

    def register(self, client, name):
        response = client.post('/api/auth/register', json={'name': name},
                               headers={'Origin': self.config.origin})
        self.assertEqual(response.status_code, 200)
        client.headers.update({'Origin': self.config.origin,
                               'X-CSRF-Token': response.json()['csrf_token']})

    def test_authenticated_download_is_private_attachment_with_no_state_or_worker_changes(self):
        self.store.mutate(self.game_id, lambda state: game.message(state, 'human', 'Owner-only comment.'))
        before = self.store.get(self.game_id)
        with self.store.connection() as db:
            events_before = db.execute('SELECT count(*) FROM events').fetchone()[0]
        with patch.object(self.app.state.supervisor, 'schedule') as schedule:
            first = self.client.get(self.url)
            second = self.client.get(self.url)
            schedule.assert_not_called()
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.content, second.content)
        self.assertEqual(first.headers['content-type'], 'application/rtf')
        self.assertEqual(first.headers['content-disposition'], 'attachment; filename="chess-chat.rtf"')
        self.assertEqual(first.headers['cache-control'], 'no-store')
        self.assertEqual(first.headers['x-content-type-options'], 'nosniff')
        self.assertIn('Owner-only comment.', plain_rtf(first.content))
        self.assertEqual(self.store.get(self.game_id), before)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM events').fetchone()[0], events_before)

    def test_unauthenticated_other_account_and_nonexistent_game_are_denied(self):
        with closing(TestClient(self.app)) as other:
            self.assertEqual(other.get(self.url).status_code, 401)
            self.register(other, 'Other owner')
            denied = other.get(self.url)
            self.assertEqual(denied.status_code, 404)
            self.assertNotIn('Export owner', denied.text)
        self.assertEqual(self.client.get('/api/games/missing/chat.rtf').status_code, 404)

    def test_finished_postgame_and_suspended_games_remain_exportable(self):
        self.store.mutate(self.game_id, lambda state: game.finish(state, '1/2-1/2', 'agreement'))
        self.store.mutate(self.game_id, lambda state: game.message(state, 'astra', 'Post-game discussion.'))
        result = self.client.get(self.url)
        self.assertEqual(result.status_code, 200)
        self.assertIn('Post-game discussion.', plain_rtf(result.content))
        self.assertIn('1/2-1/2 (Draw)', plain_rtf(result.content))
        self.store.mutate(self.game_id, lambda state: state.update(status='suspended', result='*', termination=''))
        result = self.client.get(self.url)
        self.assertEqual(result.status_code, 200)
        self.assertIn('Status: Suspended', plain_rtf(result.content))

    def test_internal_notes_opt_in_is_finished_only_owned_and_readonly(self):
        def set_notes(state):
            state['assistant_notes'] = [dict(id='note-id', text='PRIVATE-ORDINARY-NOTE',
                phase='commentary', ply=0, created_at=100, after_message_id=None)]
        self.store.mutate(self.game_id, set_notes)
        url = self.url + '?include_notes=true'
        for status in ('active', 'suspended'):
            self.store.mutate(self.game_id, lambda state: state.update(status=status))
            response = self.client.get(url)
            self.assertEqual(response.status_code, 409)
            self.assertIn('after the game has finished', response.json()['detail'])
            self.assertNotIn('PRIVATE-ORDINARY-NOTE', response.text)
            self.assertEqual(self.client.get(self.url + '?include_notes=false').status_code, 200)
        self.store.mutate(self.game_id, lambda state: game.finish(state, '1/2-1/2', 'agreement'))
        before = self.store.get(self.game_id)
        with self.store.connection() as db:
            events_before = db.execute('SELECT count(*) FROM events').fetchone()[0]
        with patch.object(self.app.state.supervisor, 'schedule') as schedule:
            response = self.client.get(url)
            public = self.client.get(self.url)
            explicit_public = self.client.get(self.url + '?include_notes=false')
            schedule.assert_not_called()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['content-type'], 'application/rtf')
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertIn('PRIVATE-ORDINARY-NOTE', plain_rtf(response.content))
        self.assertNotIn('PRIVATE-ORDINARY-NOTE', plain_rtf(public.content))
        self.assertEqual(public.content, explicit_public.content)
        self.assertEqual(self.store.get(self.game_id), before)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM events').fetchone()[0], events_before)
        with closing(TestClient(self.app)) as other:
            self.assertEqual(other.get(url).status_code, 401)
            self.register(other, 'Another owner')
            denied = other.get(url)
            self.assertEqual(denied.status_code, 404)
            self.assertNotIn('PRIVATE-ORDINARY-NOTE', denied.text)


if __name__ == '__main__':
    unittest.main()
