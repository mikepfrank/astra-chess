"""Manual post-game UI fixture: isolated data, no engine/model/credentials."""
import asyncio
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from astra_web.app import create_app
from astra_web.config import Config
import uvicorn


class ReplyFixture:
    def __init__(self, config):
        pass

    async def run(self, game_id, snapshot, tool, emit, thread_id=None):
        current = await tool('chess_status', {})
        assert current['status'] == 'finished'
        await tool('_thread', {'thread_id': thread_id or 'fixture-' + game_id})
        await asyncio.sleep(2)
        await emit('Post-game UI fixture: we can discuss the completed game here. The final board and clock stay fixed.')
        return {'usage_tokens': 0}

    async def close(self):
        pass


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='astra-postgame-ui-') as folder:
        config = Config(data_dir=Path(folder), origin='http://localhost:8791', player_mode='test',
                        secure_cookies=False, smtp_host='', smtp_from='')
        uvicorn.run(create_app(config, player_factory=ReplyFixture), host='127.0.0.1', port=8791, access_log=False)
