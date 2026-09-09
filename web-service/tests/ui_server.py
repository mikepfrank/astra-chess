"""Disposable LOCAL UI test fixture. This is explicitly NOT the Astra opponent.

Run from web-service: .venv/Scripts/python.exe tests/ui_server.py
Uses only temporary data and binds 127.0.0.1:8789. No API key or model is used.
"""
from pathlib import Path
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from astra_web.app import create_app
from astra_web.config import Config
from astra_web import chess_game as game
import uvicorn


class ScriptedFixture:
    def __init__(self, config):
        pass

    async def run(self, game_id, snapshot, tool, emit, thread_id=None):
        await tool('_thread', {'thread_id': 'fixture-' + game_id})
        if snapshot['draw_offer'] == 'human':
            await tool('chess_choose', {'action': 'accept_draw', 'note': 'Scripted UI test agreement.'})
        elif game.Position.from_fen(snapshot['fen']).turn == (0 if snapshot['astra_side'] == 'white' else 1):
            move = snapshot['legal_moves'][0]
            await tool('chess_candidate', {'move': move, 'concern': 'Scripted UI test fixture; not model deliberation.'})
            await tool('chess_query', {'seconds': .2, 'depth': 2, 'candidates': 1})
            await tool('chess_choose', {'action': 'move', 'move': move, 'note': 'Deterministic first legal move for interface testing only.'})
        await emit('Scripted UI fixture: this response is for interface testing, not Astra play.')
        return {'usage_tokens': 0, 'thread_id': 'fixture-' + game_id}

    async def close(self):
        pass


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='astra-ui-test-') as data:
        config = Config(data_dir=Path(data), origin='http://127.0.0.1:8789', player_mode='test')
        uvicorn.run(create_app(config, player_factory=ScriptedFixture), host='127.0.0.1', port=8789, access_log=False)
