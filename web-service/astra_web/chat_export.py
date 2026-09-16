"""Owner-downloadable, read-only rich-text transcript of public game events."""
from datetime import datetime, timezone
import math

from .player_profiles import saved_player_name


def _rtf_text(value):
    """Quote literal text, using RTF's signed UTF-16 units for all Unicode.

    In particular, user text can never create a group, field, or control word.
    Unsupported C0 controls are made visible as replacement characters; line
    breaks and tabs retain their ordinary text meaning.
    """
    text = str(value).replace('\r\n', '\n').replace('\r', '\n')
    result = []
    for char in text:
        if char in '\\{}':
            result.append('\\' + char)
        elif char == '\n':
            result.append('\\line ')
        elif char == '\t':
            result.append('\\tab ')
        elif 32 <= ord(char) < 127:
            result.append(char)
        else:
            if ord(char) < 32 or ord(char) == 127:
                char = '\ufffd'
            encoded = char.encode('utf-16-le', errors='surrogatepass')
            for offset in range(0, len(encoded), 2):
                unit = int.from_bytes(encoded[offset:offset + 2], 'little')
                result.append('\\u' + str(unit if unit < 32768 else unit - 65536) + '?')
    return ''.join(result)


def _timestamp(value):
    if type(value) not in (int, float):
        return None
    try:
        if not math.isfinite(value):
            return None
        return datetime.fromtimestamp(value, timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None


def _when(value):
    timestamp = _timestamp(value)
    return timestamp.strftime('%Y-%m-%d %H:%M:%S UTC') if timestamp else 'Time unavailable'


def _message_ply(message, moves):
    """Prefer the committed position; infer only for old/malformed ply values.

    A timestamp tie belongs after its move. With a backwards wall clock, use
    the latest qualifying move in authoritative move order, not timestamp sort.
    An undated legacy message goes after the last move rather than disappearing.
    """
    ply = message.get('ply')
    if type(ply) is int and 0 <= ply <= len(moves):
        return ply
    stamp = _timestamp(message.get('created_at'))
    if stamp is None:
        return len(moves)
    return max((index + 1 for index, move in enumerate(moves)
                if (move_stamp := _timestamp(move.get('at'))) is not None
                and move_stamp <= stamp), default=0)


def transcript_rtf(state):
    """Return an RTF snapshot using only public participant/move/chat fields.

    No stored data is changed, and no tool traces, prompts or private identifiers
    enter the document. Source message text is literal, including any Markdown.
    """
    human = state['name']
    ai = saved_player_name(state)
    people = {'human': human, 'astra': ai}
    sides = {state['human_side']: human, state['astra_side']: ai}
    moves = state['moves']
    messages = state['messages']
    buckets = [[] for _ in range(len(moves) + 1)]
    for message in messages:
        buckets[_message_ply(message, moves)].append(message)

    # All interpolated data passes through _rtf_text; the controls below are
    # fixed document formatting. ASCII output avoids code-page ambiguity.
    parts = [r'{\rtf1\ansi\ansicpg1252\deff0\uc1',
             r'{\fonttbl{\f0\fswiss Arial;}{\f1\froman Cambria;}}',
             r'{\colortbl;\red28\green47\blue58;\red25\green99\blue107;'
             r'\red92\green103\blue112;}',
             r'\viewkind4\paperw12240\paperh15840\margl1080\margr1080'
             r'\margt1080\margb1080\widowctrl\f0\fs22\cf1',
             r'\pard\sa120\f1\fs36\b ' + _rtf_text(f'{human} vs. {ai}') + r'\b0\par',
             r'\pard\sa220\f0\fs24\cf2 Chess game and chat transcript\cf1\par']

    def paragraph(text, *, before=0, after=80, color=1, bold=False):
        parts.append(fr'\pard\sb{before}\sa{after}\f0\fs22\cf{color} '
                     + (r'\b ' if bold else '') + _rtf_text(text)
                     + (r'\b0' if bold else '') + r'\par')

    paragraph(f"White: {sides['white']}    Black: {sides['black']}")
    paragraph(f"Started: {_when(state.get('created_at'))}")
    status = {'active': 'In progress', 'suspended': 'Suspended',
              'finished': 'Finished'}.get(state.get('status'), 'Unknown')
    result = state.get('result', '*')
    result_text = {'*': 'Not decided', '1-0': f"1-0 ({sides['white']} won)",
                   '0-1': f"0-1 ({sides['black']} won)",
                   '1/2-1/2': '1/2-1/2 (Draw)'}.get(result, str(result))
    paragraph(f'Status: {status}    Result: {result_text}')
    if state.get('termination'):
        paragraph('Ending: ' + str(state['termination']).replace('_', ' '))
    if any(type(message.get('ply')) is not int or not 0 <= message['ply'] <= len(moves)
           for message in messages):
        paragraph('Some older messages lack a recorded move position. Their placement is inferred '
                  'from timestamps; undated messages appear at the end.', color=3)
    paragraph('Moves and conversation', before=240, after=160, bold=True)

    def chat(message):
        speaker = people.get(message.get('author'), 'Chat')
        parts.append(r'\pard\keepn\sb100\sa40\f0\fs22\cf1\b '
                     + _rtf_text(speaker) + r'\b0\cf3  | '
                     + _rtf_text(_when(message.get('created_at'))) + r'\cf1\par')
        parts.append(r'\pard\li240\sa160\f0\fs22\cf1 '
                     + _rtf_text(message.get('text', '')) + r'\par')

    for message in buckets[0]:
        chat(message)
    for index, move in enumerate(moves):
        color = 'White' if index % 2 == 0 else 'Black'
        notation = str(index // 2 + 1) + ('.' if index % 2 == 0 else '...') + move['san']
        speaker = sides[color.lower()]
        parts.append(r'\pard\sb100\sa120\f0\fs22\cf2\b '
                     + _rtf_text(f'{notation}  |  {speaker} ({color})')
                     + r'\b0\cf3  | ' + _rtf_text(_when(move.get('at'))) + r'\cf1\par')
        for message in buckets[index + 1]:
            chat(message)
    if not moves and not messages:
        paragraph('No moves or chat messages have been recorded yet.', color=3)
    paragraph(f'End of saved transcript: {len(moves)} plies, {len(messages)} chat messages.',
              before=200, color=3)
    parts.append('}')
    return '\n'.join(parts).encode('ascii')
