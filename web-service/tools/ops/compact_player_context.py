"""Compact one existing OpenRouter game thread during stopped-service maintenance.

This spends a bounded model request and changes the saved Codex context. Back up
the data directory first. It never starts a chess turn or changes game/clock/chat
state. Run as the service account with its normal protected provider environment.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from astra_web import chess_game
from astra_web.codex_bridge import CodexPlayer
from astra_web.config import Config
from astra_web.player_profiles import game_player_binding
from astra_web.store import Store


def require_stopped(unit):
    if not re.fullmatch(r'[a-zA-Z0-9_-]+\.service', unit):
        raise ValueError('A concrete systemd service unit is required')
    result = subprocess.run(['systemctl', 'show', unit, '--property=LoadState',
        '--property=ActiveState', '--property=MainPID', '--property=ControlGroup'], capture_output=True, text=True, check=True)
    values = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    group = values.pop('ControlGroup', '')
    if values != {'LoadState': 'loaded', 'ActiveState': 'inactive', 'MainPID': '0'}:
        raise ValueError('Stop the application service and its workers before compaction')
    if group:
        root = Path('/sys/fs/cgroup')
        path = (root / group.lstrip('/')).resolve()
        if not path.is_relative_to(root):
            raise ValueError('Invalid service control group')
        if path.exists() and any(file.read_text().strip() for file in path.rglob('cgroup.procs')):
            raise ValueError('Application worker processes still exist')


def game_digest(state):
    return hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()


async def compact(config, game_id, expected_version, unit):
    require_stopped(unit)
    store = Store(config)
    games = store.list()
    if any(s.get('active_started') is not None or s.get('compaction_pause')
           or s['worker']['state'] in {'thinking', 'queued', 'calculating', 'compacting'} for s in games):
        raise ValueError('Saved worker activity must be reconciled before maintenance')
    state = store.get(game_id)
    binding = game_player_binding(state, config)
    if binding['profile']['name'] != 'openrouter-glm':
        raise ValueError('This maintenance command is limited to the experimental OpenRouter player')
    if state['version'] != expected_version or not state.get('thread_id'):
        raise ValueError('The game version or existing thread does not match the maintenance request')
    before = {s['id']: game_digest(s) for s in games}
    report = {'operation': 'operator_context_compaction', 'game_id': game_id,
        'expected_version': expected_version, 'thread_id': state['thread_id'],
        'started_at': time.time(), 'compaction_events': [], 'usage_tokens': None,
        'usage_complete': False, 'success': False}
    player = CodexPlayer(config)
    reservation = store.reserve()

    async def tool(name, args):
        if name == '_thread' and args == {'thread_id': state['thread_id']}:
            return {'accepted': True}
        if name == '_usage':
            value = args.get('tokens')
            if type(value) is not int or value < (report['usage_tokens'] or 0):
                raise ValueError('Invalid maintenance token accounting')
            report['usage_tokens'] = value
            return {'accepted': True}
        if name == '_compaction' and args.get('phase') in {'started', 'completed'}:
            report['compaction_events'].append({**args, 'at': time.time()})
            return {'accepted': True}
        raise ValueError('A chess action is forbidden during context maintenance')

    failure = None
    try:
        result = await player.compact(game_id, chess_game.model_snapshot(state), tool,
            thread_id=state['thread_id'], player_binding=binding)
        report['usage_tokens'] = result['usage_tokens']
        report['usage_complete'] = result['usage_tokens'] is not None
        if result['thread_id'] != state['thread_id']:
            raise ValueError('Maintenance changed the game thread')
        require_stopped(unit)
        if {s['id']: game_digest(s) for s in store.list()} != before:
            raise ValueError('Game state changed during maintenance; inspect before restarting')
        report.update(success=True, same_thread=result['thread_id'] == state['thread_id'],
            game_states_unchanged=True, model=result['model'], reasoning=result['reasoning'])
    except BaseException as error:
        report['error_type'] = type(error).__name__
        failure = error
    finally:
        try:
            await player.close()
        except BaseException as error:
            report.update(success=False, cleanup_error_type=type(error).__name__)
            failure = failure or error
        # A failed stream may have spent tokens after its last telemetry event.
        # Match normal Supervisor settlement: only a completed player operation
        # with known usage can replace the conservative reservation amount.
        charge = (report['usage_tokens'] if report['usage_complete'] else
                  max(reservation[1], report['usage_tokens'] or 0))
        store.settle(reservation, charge)
        report['charged_tokens'] = charge
        report['completed_at'] = time.time()
        with store.connection() as db:
            store._event(db, game_id, 'operator_context_compaction', report)
        output = config.data_dir / 'players' / game_id / f'context-maintenance-{time.time_ns()}.json'
        output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(report, indent=2))
    if failure:
        raise RuntimeError('Context maintenance failed; inspect its private receipt before restarting') from failure
    return report


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--game-id', required=True)
    parser.add_argument('--expected-version', type=int, required=True)
    parser.add_argument('--stopped-unit', required=True)
    parser.add_argument('--codex', required=True)
    args = parser.parse_args()
    data = args.data_dir.resolve(strict=True)
    if not (data / 'astra.sqlite3').is_file():
        parser.error('The existing game database is required')
    config = Config(data_dir=data, model_profile='openrouter-glm', persona='arcturus',
        player_mode='codex', codex_bin=args.codex)
    asyncio.run(compact(config, args.game_id, args.expected_version, args.stopped_unit))


if __name__ == '__main__':
    main()
