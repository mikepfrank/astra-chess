"""Pure, fail-closed planner for an explicitly authorized historical game repair.

This module opens no files or databases. The caller must establish the exact
authorized game, acquire its maintenance gate, back up durable data, and compare
the original version/state before applying the returned document. Native source
rows are evidence of routing only: hidden reasoning, tool traces, and content
wording are never classification evidence.
"""
import copy
import json

from astra_web.chat_export import _transcript_buckets


class ReclassificationError(ValueError):
    """The supplied evidence does not prove a unique, lossless reclassification."""


def _source_events(rows):
    events = []
    seen_ids = {}
    calls = {}
    completed_calls = set()
    duplicates = 0

    def duplicate(item):
        nonlocal duplicates
        item_id = item.get('id')
        if not isinstance(item_id, str) or not item_id:
            return False
        if item_id not in seen_ids:
            seen_ids[item_id] = item
            return False
        if seen_ids[item_id] != item:
            raise ReclassificationError('A native item ID has conflicting source payloads.')
        duplicates += 1
        return True

    for row_index, row in enumerate(rows):
        if not isinstance(row, dict) or row.get('type') != 'response_item':
            continue
        item = row.get('payload')
        if not isinstance(item, dict):
            raise ReclassificationError('A response item has no object payload.')
        kind = item.get('type')
        if kind == 'message':
            if item.get('role') != 'assistant' or item.get('phase') not in (None, 'commentary', 'final_answer'):
                continue
            if duplicate(item):
                continue
            content = item.get('content')
            if not isinstance(content, list):
                raise ReclassificationError('An ordinary assistant item has invalid content.')
            blocks = []
            for block in content:
                if isinstance(block, dict) and block.get('type') in ('output_text', 'text'):
                    if not isinstance(block.get('text'), str):
                        raise ReclassificationError('An ordinary assistant text block is invalid.')
                    blocks.append(block['text'])
            text = '\n'.join(blocks).strip()
            if not text:
                continue
            if not isinstance(item.get('id'), str) or not item['id']:
                raise ReclassificationError('An ordinary assistant source lacks a native item ID.')
            events.append(dict(kind='ordinary', text=text, phase=item.get('phase'),
                               native_item_id=item['id'], row_index=row_index))
        elif kind == 'function_call' and item.get('name') == 'chess_comment':
            if duplicate(item):
                continue
            call_id = item.get('call_id')
            if not isinstance(call_id, str) or not call_id or call_id in calls:
                raise ReclassificationError('A chess_comment call ID is missing or repeated.')
            event = dict(kind='tool', text=None, native_item_id=item.get('id'),
                         row_index=row_index, sent=False)
            calls[call_id] = (item, event)
            events.append(event)
        elif (kind == 'function_call_output' and isinstance(item.get('call_id'), str)
              and item['call_id'] in calls):
            if duplicate(item):
                continue
            call_id = item['call_id']
            if call_id in completed_calls:
                raise ReclassificationError('A chess_comment call has multiple distinct outputs.')
            completed_calls.add(call_id)
            call, event = calls[call_id]
            try:
                output = json.loads(item['output'])
            except (KeyError, TypeError, ValueError):
                # An invalid/partial output cannot prove that a comment was sent.
                continue
            if not isinstance(output, dict) or output.get('sent') is not True:
                continue
            try:
                arguments = json.loads(call['arguments'])
            except (KeyError, TypeError, ValueError):
                raise ReclassificationError('A successful chess_comment call has invalid arguments.') from None
            if not isinstance(arguments, dict) or not isinstance(arguments.get('text'), str):
                raise ReclassificationError('A successful chess_comment call has no text argument.')
            text = arguments['text'].strip()
            if not text or not isinstance(event['native_item_id'], str) or not event['native_item_id']:
                raise ReclassificationError('A successful chess_comment source lacks text or native item ID.')
            event.update(text=text, sent=True)
    return [event for event in events if event['kind'] == 'ordinary' or event['sent']], duplicates


def _unique_alignment(messages, sources):
    """Count ordered subsequence alignments, capping at two (ambiguous)."""
    count = [[1] * (len(sources) + 1)]
    for message in messages:
        row = [0]
        text = message['text'].strip()
        for index, source in enumerate(sources):
            row.append(min(2, row[-1] + (count[-1][index] if text == source['text'] else 0)))
        count.append(row)
    if not count[-1][-1]:
        raise ReclassificationError('Stored AI messages do not match an ordered source subsequence.')
    if count[-1][-1] != 1:
        raise ReclassificationError('Stored AI messages have multiple source subsequence alignments.')
    result = []
    message_index, source_index = len(messages), len(sources)
    while message_index:
        if (messages[message_index - 1]['text'].strip() == sources[source_index - 1]['text']
                and count[message_index - 1][source_index - 1]):
            result.append((messages[message_index - 1], sources[source_index - 1]))
            message_index -= 1
        source_index -= 1
    return list(reversed(result))


def _flatten(state):
    """Use exactly the exporter's position/message ordering, including moves."""
    flattened = []
    for ply, bucket in enumerate(_transcript_buckets(state['moves'], state['messages'],
                                                   state.get('assistant_notes', []))):
        if ply:
            flattened.append(('move', ply - 1, state['moves'][ply - 1]))
        flattened.extend((kind, ply, item) for kind, item in bucket)
    return flattened


def plan(state, rollout_rows):
    """Return a revised copy and text-free summary, or raise without changing input.

    Every stored AI message must have exactly one complete sequence alignment to
    ordinary assistant items or successfully sent chess_comment calls. Only
    matched ordinary items move into notes. Unpublished source items are allowed;
    content wording, reasoning items, and failed tools cannot establish routing.
    """
    if not isinstance(state, dict) or state.get('status') != 'finished':
        raise ReclassificationError('Historical note reclassification requires a finished game.')
    if type(state.get('version')) is not int or state['version'] < 0:
        raise ReclassificationError('The saved game version is invalid.')
    if not isinstance(state.get('messages'), list) or not isinstance(state.get('moves'), list):
        raise ReclassificationError('The saved public transcript is invalid.')
    existing_notes = state.get('assistant_notes', [])
    if not isinstance(existing_notes, list):
        raise ReclassificationError('The saved internal note stream is invalid.')
    ids = set()
    for item in [*state['messages'], *existing_notes]:
        if (not isinstance(item, dict) or not isinstance(item.get('id'), str) or not item['id']
                or item['id'] in ids or not isinstance(item.get('text'), str)
                or 'created_at' not in item or 'ply' not in item):
            raise ReclassificationError('Transcript items require unique IDs and complete saved text/position/time.')
        ids.add(item['id'])
    if any(message.get('author') not in ('human', 'astra') for message in state['messages']):
        raise ReclassificationError('A public message has an unsupported author.')
    sources, duplicate_count = _source_events(rollout_rows)
    ai_messages = [message for message in state['messages'] if message['author'] == 'astra']
    aligned = _unique_alignment(ai_messages, sources)
    converted = {}
    for message, source in aligned:
        if source['kind'] != 'ordinary':
            continue
        note_id = 'historical-' + message['id']
        if note_id in ids:
            raise ReclassificationError('A deterministic migrated note ID already exists.')
        converted[message['id']] = dict(id=note_id, text=message['text'], phase=source['phase'],
            ply=message['ply'], created_at=message['created_at'],
            source_public_message_id=message['id'], source_native_item_id=source['native_item_id'])
    if not converted:
        raise ReclassificationError('No ordinary public messages remain to reclassify; no change is planned.')

    updated = copy.deepcopy(state)
    updated['messages'] = [copy.deepcopy(message) for message in state['messages']
                           if message['id'] not in converted]
    updated['assistant_notes'] = []
    expected = []
    latest_public_id = None
    for kind, ply, item in _flatten(state):
        if kind == 'move':
            expected.append((kind, ply, copy.deepcopy(item)))
        elif kind == 'chat' and item['id'] not in converted:
            latest_public_id = item['id']
            expected.append((kind, ply, copy.deepcopy(item)))
        else:
            note = copy.deepcopy(converted[item['id']] if kind == 'chat' else item)
            note['after_message_id'] = latest_public_id
            updated['assistant_notes'].append(note)
            expected.append(('note', ply, copy.deepcopy(note)))
    if _flatten(updated) != expected:
        raise ReclassificationError('The revised stream does not preserve exact transcript event order.')
    updated['version'] += 1
    allowed = {'messages', 'assistant_notes', 'version'}
    if ({key: value for key, value in state.items() if key not in allowed}
            != {key: value for key, value in updated.items() if key not in allowed}):
        raise ReclassificationError('The plan changed an unrelated saved game field.')
    summary = dict(
        version_before=state['version'], version_after=updated['version'],
        public_messages_before=len(state['messages']), public_messages_after=len(updated['messages']),
        human_messages=sum(message['author'] == 'human' for message in state['messages']),
        ai_messages_before=len(ai_messages), retained_explicit_comments=len(ai_messages) - len(converted),
        migrated_ordinary_messages=len(converted), existing_notes=len(existing_notes),
        total_notes=len(updated['assistant_notes']), source_events=len(sources),
        source_ordinary=sum(source['kind'] == 'ordinary' for source in sources),
        source_successful_comments=sum(source['kind'] == 'tool' for source in sources),
        unmatched_source_events=len(sources) - len(ai_messages), deduplicated_source_items=duplicate_count,
        transcript_events_preserved=len(expected), moves_preserved=len(state['moves']),
        unique_alignment=True, transcript_order_verified=True)
    return updated, summary
