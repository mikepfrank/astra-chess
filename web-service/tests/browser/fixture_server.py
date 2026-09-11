"""Disposable loopback HTTP fixture for browser QA; never calls a model.

All storage lives under ignored web-service/var/browser-qa. The database and
authentication file are removed on normal shutdown. Bind address and port are
deliberately fixed so mutating browser checks cannot target a live deployment.
"""
import json
from pathlib import Path
import secrets
import socket
import sys
import tempfile
import time

APP_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP_ROOT))
from astra_web.app import create_app
from astra_web.config import Config
from astra_web import chess_game as game
import uvicorn

ORIGIN = 'http://127.0.0.1:8793'
OUTPUT = APP_ROOT / 'var' / 'browser-qa'


class NoPlayer:
    def __init__(self, config):
        pass

    async def run(self, *args, **kwargs):
        raise RuntimeError('Browser fixture must never start a model or search')

    async def close(self):
        pass


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Reserve the listener before writing access information for this fixture.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(('127.0.0.1', 8793))
        listener.listen(128)
        listener.setblocking(False)
        with tempfile.TemporaryDirectory(prefix='fixture-', dir=OUTPUT) as directory:
            config = Config(data_dir=Path(directory), origin=ORIGIN,
                            player_mode='test', secure_cookies=False,
                            smtp_host='', smtp_from='')
            app = create_app(config, player_factory=NoPlayer)
            fixture_id = 'browser-qa-' + secrets.token_hex(16)

            @app.get('/api/browser-qa/fixture')
            def marker():
                return {'fixture_id': fixture_id, 'model_calls_allowed': False}

            token = app.state.identity.register('Replay QA player')
            user = app.state.identity.user_for_token(token)
            state = game.new_game(user, 'white', config)
            game.message(state, 'human', 'PRIVATE_CHAT_SENTINEL: Hello before the first move!')
            for uci, actor in [('f2f3', 'human'), ('e7e5', 'astra'),
                               ('g2g4', 'human'), ('d8h4', 'astra')]:
                game.apply_move(state, uci, actor)
                game.message(state, actor, 'After ' + state['moves'][-1]['san'])
            game.message(state, 'human', 'POSTGAME_SENTINEL: That was quick! </script><script>window.XSS=true</script>')
            state['updated_at'] = time.time()
            app.state.store.create(state)
            identity = app.state.identity.state(token)
            access_path = OUTPUT / 'replay-ui-access.json'
            access_path.write_text(json.dumps({'origin': ORIGIN, 'fixture_id': fixture_id,
                'cookie': token, 'csrf': identity['csrf_token'], 'game': state['id']}), encoding='utf-8')
            access_path.chmod(0o600)
            emoji = game.snapshot(game.new_game({'id': 'emoji-qa', 'name': 'Emoji preview'}, 'white', config))
            emoji['id'] = 'emoji-qa'
            (OUTPUT / 'emoji-game.json').write_text(json.dumps(emoji), encoding='utf-8')
            print(f'Disposable browser QA: {ORIGIN}; stop with Ctrl+C. No model calls.', flush=True)
            try:
                uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=8793,
                                             access_log=False)).run(sockets=[listener])
            finally:
                access_path.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
