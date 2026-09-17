"""Fail-closed provenance alignment and lossless historical note conversion."""
import copy
import json
import unittest

from astra_web.chat_export import _transcript_buckets, transcript_rtf
from tests.test_chat_export import plain_rtf
from tools.ops.game_note_reclassification import plan, ReclassificationError


def row(payload):
    return {'type': 'response_item', 'payload': payload}


def ordinary(item_id, text, phase=None):
    payload = dict(type='message', id=item_id, role='assistant',
                   content=[dict(type='output_text', text=text)])
    if phase is not None:
        payload['phase'] = phase
    return row(payload)


def comment(item_id, text, *, sent=True):
    call_id = 'call-' + item_id
    return [row(dict(type='function_call', id=item_id, call_id=call_id,
                     name='chess_comment', arguments=json.dumps({'text': text}))),
            row(dict(type='function_call_output', id='output-' + item_id, call_id=call_id,
                     output=json.dumps({'sent': sent, 'resource_budget': {'private': 'not used'}})))]


def fixture():
    state = dict(id='authorized-fixture', user_id='owner', version=17, name='Human',
        human_side='white', astra_side='black', player_persona={'display_name': 'Arcturus'},
        created_at=0, status='finished', result='1/2-1/2', termination='agreement',
        moves=[dict(san='e4', actor='human', at=3), dict(san='e5', actor='astra', at=6)],
        messages=[
            dict(id='h0', author='human', text='Hello.', ply=0, created_at=1),
            dict(id='a0', author='astra', text='Ordinary preface.', ply=0, created_at=2),
            dict(id='h1', author='human', text='Your move.', ply=1, created_at=3),
            dict(id='a1', author='astra', text='Tool greeting.', ply=1, created_at=4),
            dict(id='a2', author='astra', text='Ordinary wrapup.', ply=2, created_at=7),
            dict(id='h2', author='human', text='Thanks.', ply=2, created_at=8),
            dict(id='a3', author='astra', text='Tool goodbye.', ply=2, created_at=9)],
        thread_id='saved-thread', player_prompt='saved prompt', player_profile={'version': 4},
        clock_used=101.5, worker={'state': 'idle'}, decisions=[{'private': 'unchanged'}],
        queries=[{'private': 'unchanged'}], result_metadata={'private': 'unchanged'})
    rows = [ordinary('unused-before', 'Not published before.'), ordinary('native-a0', 'Ordinary preface.'),
            *comment('native-a1', 'Tool greeting.'),
            ordinary('unused-mid', 'Not published between.'),
            ordinary('native-a2', 'Ordinary wrapup.', 'final_answer'),
            *comment('native-a3', 'Tool goodbye.'), ordinary('unused-after', 'Not published afterward.')]
    return state, rows


def transcript_items(state):
    return [(kind, ply, event['id'], event['text'])
            for ply, bucket in enumerate(_transcript_buckets(state['moves'], state['messages'],
                                                            state.get('assistant_notes', [])))
            for kind, event in bucket]


class GameNoteReclassificationTests(unittest.TestCase):
    def test_unique_alignment_with_unpublished_sources_preserves_exact_data(self):
        state, rows = fixture()
        before_state, before_rows = copy.deepcopy(state), copy.deepcopy(rows)
        updated, summary = plan(state, iter(rows))
        self.assertEqual([message['id'] for message in updated['messages']], ['h0', 'h1', 'a1', 'h2', 'a3'])
        self.assertEqual([note['id'] for note in updated['assistant_notes']], ['historical-a0', 'historical-a2'])
        for note, message_id, native_id, anchor in zip(updated['assistant_notes'],
                ['a0', 'a2'], ['native-a0', 'native-a2'], ['h0', 'a1']):
            original = next(message for message in state['messages'] if message['id'] == message_id)
            self.assertEqual({key: note[key] for key in ('text', 'ply', 'created_at')},
                             {key: original[key] for key in ('text', 'ply', 'created_at')})
            self.assertEqual(note['source_public_message_id'], message_id)
            self.assertEqual(note['source_native_item_id'], native_id)
            self.assertEqual(note['after_message_id'], anchor)
        self.assertIsNone(updated['assistant_notes'][0]['phase'])
        self.assertEqual(updated['assistant_notes'][1]['phase'], 'final_answer')
        self.assertEqual(updated['version'], state['version'] + 1)
        for key in state:
            if key not in ('version', 'messages', 'assistant_notes'):
                self.assertEqual(updated[key], state[key], key)
        self.assertEqual(state, before_state)
        self.assertEqual(rows, before_rows)
        self.assertEqual(summary['migrated_ordinary_messages'], 2)
        self.assertEqual(summary['retained_explicit_comments'], 2)
        self.assertEqual(summary['unmatched_source_events'], 3)
        self.assertTrue(summary['unique_alignment'])
        for message in state['messages']:
            self.assertNotIn(message['text'], json.dumps(summary))

    def test_strip_normalization_only_and_supported_text_blocks_and_phases(self):
        state, rows = fixture()
        rows[1]['payload']['phase'] = 'commentary'
        rows[1]['payload']['content'] = [dict(type='output_text', text='  Ordinary'),
                                         dict(type='text', text='preface. \n')]
        state['messages'][1]['text'] = '\t Ordinary\npreface. '
        updated, _ = plan(state, rows)
        self.assertEqual(updated['assistant_notes'][0]['text'], '\t Ordinary\npreface. ')
        self.assertEqual(updated['assistant_notes'][0]['phase'], 'commentary')
        state['messages'][1]['text'] = 'Ordinary preface.'
        with self.assertRaisesRegex(ReclassificationError, 'do not match'):
            plan(state, rows)

    def test_ambiguous_duplicate_text_is_rejected_even_with_same_routing_class(self):
        state, rows = fixture()
        rows.insert(2, ordinary('another-native-id', 'Ordinary preface.'))
        with self.assertRaisesRegex(ReclassificationError, 'multiple source'):
            plan(state, rows)
        state, rows = fixture()
        rows[2:2] = comment('also-explicit', 'Ordinary preface.')
        with self.assertRaisesRegex(ReclassificationError, 'multiple source'):
            plan(state, rows)

    def test_identical_item_id_repetition_is_deduplicated_but_conflicts_abort(self):
        state, rows = fixture()
        rows.insert(2, copy.deepcopy(rows[1]))
        updated, summary = plan(state, rows)
        self.assertEqual(summary['deduplicated_source_items'], 1)
        self.assertEqual(len(updated['assistant_notes']), 2)
        rows[2]['payload']['content'][0]['text'] = 'Conflicting replacement.'
        with self.assertRaisesRegex(ReclassificationError, 'conflicting source'):
            plan(state, rows)

    def test_full_sequence_can_uniquely_disambiguate_repeated_text(self):
        state, rows = fixture()
        state['messages'][1]['text'] = 'Repeated text.'
        state['messages'][4]['text'] = 'Repeated text.'
        rows[1]['payload']['content'][0]['text'] = 'Repeated text.'
        rows[5]['payload']['content'][0]['text'] = 'Repeated text.'
        updated, summary = plan(state, rows)
        self.assertEqual(summary['migrated_ordinary_messages'], 2)
        self.assertEqual([note['source_native_item_id'] for note in updated['assistant_notes']],
                         ['native-a0', 'native-a2'])

    def test_failed_partial_and_unrelated_tools_do_not_establish_public_provenance(self):
        state, rows = fixture()
        rows[3]['payload']['output'] = json.dumps({'sent': False, 'text': 'Tool greeting.'})
        with self.assertRaisesRegex(ReclassificationError, 'do not match'):
            plan(state, rows)
        rows[3]['payload']['output'] = '{incomplete'
        with self.assertRaisesRegex(ReclassificationError, 'do not match'):
            plan(state, rows)
        rows[3]['payload']['output'] = json.dumps({'sent': 1})
        with self.assertRaisesRegex(ReclassificationError, 'do not match'):
            plan(state, rows)
        rows.pop(3)
        with self.assertRaisesRegex(ReclassificationError, 'do not match'):
            plan(state, rows)
        state, rows = fixture()
        rows[2]['payload']['name'] = 'chess_status'
        with self.assertRaisesRegex(ReclassificationError, 'do not match'):
            plan(state, rows)

    def test_reasoning_compaction_user_and_unknown_phase_content_are_never_sources(self):
        state, rows = fixture()
        original = rows.pop(1)
        excluded = [row(dict(type='reasoning', id='hidden', text='Ordinary preface.',
                             summary=[{'text': 'Ordinary preface.'}])),
                    {'type': 'compacted', 'payload': {'replacement_history': [original['payload']]}},
                    {'type': 'event_msg', 'payload': {'type': 'agent_message', 'message': 'Ordinary preface.'}}]
        for role, phase in [('user', None), ('assistant', 'analysis'), ('assistant', 'unknown')]:
            excluded_item = copy.deepcopy(original)
            excluded_item['payload'].update(role=role, phase=phase)
            excluded.append(excluded_item)
        with self.assertRaisesRegex(ReclassificationError, 'do not match'):
            plan(state, [*excluded, *rows])
        updated, _ = plan(state, [*excluded, original, *rows])
        self.assertEqual(len(updated['assistant_notes']), 2)

    def test_existing_notes_reanchor_and_merge_in_original_order_despite_clock_ties(self):
        state, rows = fixture()
        state['assistant_notes'] = [
            dict(id='n0', text='Before ordinary preface.', ply=0, created_at=90, phase='commentary', after_message_id='h0'),
            dict(id='n1', text='After ordinary preface.', ply=0, created_at=0, phase=None, after_message_id='a0'),
            dict(id='n2', text='Before ordinary wrapup.', ply=2, created_at=90, phase='final_answer', after_message_id='a1'),
            dict(id='n3', text='After ordinary wrapup.', ply=2, created_at=0, phase='commentary', after_message_id='a2')]
        for message in state['messages']:
            message['created_at'] = 5
        original = transcript_items(state)
        updated, summary = plan(state, rows)
        actual = transcript_items(updated)
        expected = [('note' if item_id in ('a0', 'a2') else kind, ply,
                     'historical-' + item_id if item_id in ('a0', 'a2') else item_id, text)
                    for kind, ply, item_id, text in original]
        self.assertEqual(actual, expected)
        self.assertEqual([note['id'] for note in updated['assistant_notes']],
                         ['n0', 'historical-a0', 'n1', 'n2', 'historical-a2', 'n3'])
        self.assertEqual([note['after_message_id'] for note in updated['assistant_notes']],
                         ['h0', 'h0', 'h0', 'a1', 'a1', 'a1'])
        self.assertEqual(summary['existing_notes'], 4)
        self.assertEqual(summary['total_notes'], 6)
        for note in state['assistant_notes']:
            revised = next(item for item in updated['assistant_notes'] if item['id'] == note['id'])
            self.assertEqual({k: v for k, v in revised.items() if k != 'after_message_id'},
                             {k: v for k, v in note.items() if k != 'after_message_id'})

    def test_rerun_and_id_collisions_abort_without_mutation(self):
        state, rows = fixture()
        updated, _ = plan(state, rows)
        before = copy.deepcopy(updated)
        with self.assertRaisesRegex(ReclassificationError, 'No ordinary public'):
            plan(updated, rows)
        self.assertEqual(updated, before)
        state['assistant_notes'] = [dict(id='historical-a0', text='Existing.', ply=0,
            created_at=0, after_message_id=None)]
        with self.assertRaisesRegex(ReclassificationError, 'already exists'):
            plan(state, rows)
        state.pop('assistant_notes')
        state['messages'][0]['id'] = state['messages'][1]['id']
        with self.assertRaisesRegex(ReclassificationError, 'unique IDs'):
            plan(state, rows)

    def test_unfinished_game_and_out_of_order_evidence_abort(self):
        state, rows = fixture()
        state['status'] = 'active'
        with self.assertRaisesRegex(ReclassificationError, 'finished game'):
            plan(state, rows)
        state['status'] = 'finished'
        rows[1], rows[5] = rows[5], rows[1]
        with self.assertRaisesRegex(ReclassificationError, 'do not match'):
            plan(state, rows)

    def test_export_public_only_vs_full_preserves_old_content_and_new_labels(self):
        state, rows = fixture()
        updated, _ = plan(state, rows)
        public = plain_rtf(transcript_rtf(updated))
        full = plain_rtf(transcript_rtf(updated, include_notes=True))
        self.assertNotIn('Ordinary preface.', public)
        self.assertNotIn('Ordinary wrapup.', public)
        for message in state['messages']:
            self.assertIn(message['text'], full)
            if message['id'] not in ('a0', 'a2'):
                self.assertIn(message['text'], public)
        ordered = ['Hello.', 'Ordinary preface.', '1.e4', 'Your move.', 'Tool greeting.',
                   '1...e5', 'Ordinary wrapup.', 'Thanks.', 'Tool goodbye.']
        self.assertEqual([full.index(text) for text in ordered],
                         sorted(full.index(text) for text in ordered))
        self.assertEqual(full.count('[AI internal note — not sent to sidebar]'), 2)
        for private in ('native-a0', 'historical-a0', 'saved prompt', 'saved-thread'):
            self.assertNotIn(private, full)


if __name__ == '__main__':
    unittest.main()
