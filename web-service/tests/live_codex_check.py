"""Explicit operator-only live integration check. Never collected by unittest.

Runs real paid Codex actions with the production supervisor and tactical engine.
Evidence goes to a separately selected private data directory; no user game is touched.
"""
import argparse
import asyncio
import getpass
import json
import os
from pathlib import Path
import re
import sys
import warnings

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from astra_web import chess_game as game, codex_bridge as bridge
from astra_web.config import Config
from astra_web.identity import Identity
from astra_web.store import Store
from astra_web.supervisor import Supervisor
from astra_web.local_setup import load_local_environment


def safe_error(value):
    text = json.dumps(value, ensure_ascii=True)
    for variable in ('OPENAI_API_KEY', 'OPENROUTER_API_KEY'):
        key = os.environ.get(variable)
        if key:
            text = text.replace(key, '[redacted]')
    return re.sub(r'sk-[A-Za-z0-9_-]+', '[redacted]', text)[:2000]


async def run(args):
    config = Config(data_dir=args.data_dir.resolve(), player_mode='codex', codex_bin=args.codex_bin,
                    model_profile=getattr(args, 'profile', 'astra'))
    from astra_web.player_profiles import profile_for
    profile = profile_for(config)
    config.validate()
    store = Store(config)
    identity = Identity(config)
    supervisor = Supervisor(config, store, identity)
    # Show only protocol failures, never reasoning, credentials or raw tool output.
    original_read = bridge._Rpc.read
    async def read(rpc):
        payload = await original_read(rpc)
        if 'error' in payload:
            print('Protocol diagnostic:', safe_error(payload['error']), flush=True)
        if payload.get('method') == 'error':
            print('Turn diagnostic:', safe_error(payload.get('params')), flush=True)
        return payload
    bridge._Rpc.read = read
    state = game.new_game({'id':'operator-integration','name':'Local integration check'}, 'black', config)
    store.create(state)
    print('Private integration game:', state['id'], flush=True)
    try:
        for turn in range(args.turns):
            print('Starting', profile.display_name, 'action', turn + 1, flush=True)
            await supervisor._active_run(state['id'])
            state = store.get(state['id'])
            print(json.dumps({'ply':len(state['moves']), 'moves':[m['san'] for m in state['moves']],
                'thread_saved':bool(state.get('thread_id')), 'worker':state['worker'],
                'public_messages':len(state['messages'])}), flush=True)
            if game.side_to_move(state) != state['human_side'] or not state['moves']:
                raise RuntimeError('The live action did not accept an Astra move.')
            if turn + 1 < args.turns:
                pos = game.position(state)
                reply = next(iter(pos.legal_moves())).uci()
                state = store.mutate(state['id'], lambda s:game.apply_move(s, reply, 'human'))
                print('Deterministic test-opponent reply:', reply, flush=True)
        print('Live move and conversation checks passed.', flush=True)
    except Exception as error:
        print('Live check failed:', type(error).__name__, safe_error(str(error)), flush=True)
        return 1
    finally:
        bridge._Rpc.read = original_read
        await supervisor.close()
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', required=True, help='Authorize real paid model actions')
    parser.add_argument('--codex-bin', required=True)
    parser.add_argument('--data-dir', required=True, type=Path)
    parser.add_argument('--turns', type=int, choices=(1, 2), default=2)
    parser.add_argument('--profile', choices=('astra', 'openrouter-glm'), default='astra')
    args = parser.parse_args()
    if args.profile == 'openrouter-glm':
        from astra_web.openrouter_setup import load_openrouter_environment
        load_openrouter_environment(Path(__file__).resolve().parents[1])
        key_variable = 'OPENROUTER_API_KEY'
    else:
        load_local_environment(Path(__file__).resolve().parents[1])
        key_variable = 'OPENAI_API_KEY'
    if not os.environ.get(key_variable):
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            os.environ[key_variable] = getpass.getpass('Service API key (hidden): ').strip()
    raise SystemExit(asyncio.run(run(args)))
