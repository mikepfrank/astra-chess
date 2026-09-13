"""Loopback-only launch for the isolated GLM/Codex experiment."""
import argparse
import os
from pathlib import Path


def main():
    app_root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8790)
    parser.add_argument('--data-dir', type=Path, default=app_root / 'var' / 'openrouter-local')
    args = parser.parse_args()
    data_dir = args.data_dir.resolve()
    if not data_dir.is_relative_to((app_root / 'var').resolve()) or data_dir == (app_root / 'var').resolve():
        parser.error('Local experiments require a dedicated data directory below this worktree web-service/var.')
    from astra_web.openrouter_setup import load_openrouter_environment, OpenRouterSetupError
    try:
        load_openrouter_environment(Path(__file__).resolve().parent)
    except OpenRouterSetupError as error:
        parser.error(str(error))
    os.environ['ASTRA_MODEL_PROFILE'] = 'openrouter-glm'
    os.environ['ASTRA_ORIGIN'] = f'http://127.0.0.1:{args.port}'
    os.environ.setdefault('ASTRA_PLAYER', 'codex')
    # Do not accidentally inherit the original application's database location.
    os.environ['ASTRA_DATA_DIR'] = str(data_dir)
    import uvicorn
    from astra_web.app import create_app
    uvicorn.run(create_app(), host='127.0.0.1', port=args.port, workers=1,
                access_log=False, limit_concurrency=64, timeout_keep_alive=5)


if __name__ == '__main__':
    main()
