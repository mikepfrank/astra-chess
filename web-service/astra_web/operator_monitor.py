"""Read-only, account-authorized inventory; never start or alter a game."""
import sqlite3

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from tools.ops.report_games import report
from .config import APP_ROOT
from .identity import require_user


GAME_FIELDS = (
    'game_id', 'name', 'human_side', 'status', 'result', 'human_outcome',
    'termination', 'ply', 'last_move', 'created_at', 'last_human_activity',
    'updated_at', 'worker_state', 'active_response', 'waiting_for',
)
REPLAY_FLAGS = ('saved', 'building', 'shared', 'listed')


def monitor_snapshot(config):
    """Allowlist output even if the private command-line report later grows."""
    source = report(config.data_dir, timezone_name='UTC')
    excluded = set(config.monitor_excluded_game_ids)
    games = []
    excluded_count = 0
    for row in source['games']:
        if row['game_id'] in excluded:
            excluded_count += 1
            continue
        item = {key: row[key] for key in GAME_FIELDS}
        item['replays'] = {
            variant: {flag: bool(row['replays'][variant][flag]) for flag in REPLAY_FLAGS}
            for variant in ('moves', 'chat')
        }
        games.append(item)
    finished = sum(row['status'] == 'finished' for row in games)
    budget = source['today_budget']
    return {
        'schema_version': 1, 'as_of': source['as_of'], 'timezone': 'UTC',
        'summary': {
            'total_games': len(games), 'player_games': len(games), 'qa_games': 0,
            'finished_player_games': finished, 'unfinished_player_games': len(games) - finished,
            'excluded_games': excluded_count,
        },
        # These operational totals deliberately cover the entire service, including
        # excluded fixtures. A filtered table must not imply workers are idle.
        'activity': {key: source['activity'][key] for key in (
            'active_responses', 'building_replays', 'reserved_tokens', 'idle_snapshot')},
        'today_budget': None if budget is None else {
            key: budget[key] for key in ('day', 'turns', 'tokens', 'reserved')},
        'max_daily_tokens': config.max_daily_tokens,
        'games': games,
    }


def install_operator_monitor(app, config):
    @app.get('/api/operator/games')
    def operator_games(request: Request):
        user = require_user(request)
        if not request.app.state.identity.is_operator(user):
            raise HTTPException(403, 'This page is available only to the configured site operator.')
        try:
            snapshot = monitor_snapshot(config)
        except (OSError, sqlite3.Error, ValueError, KeyError, TypeError):
            # Data corruption or a transient read problem must not expose paths,
            # raw saved state, SQL, or other internal exception details.
            raise HTTPException(503, 'The game inventory is temporarily unavailable. Please try again.') from None
        return JSONResponse(snapshot, headers={'Cache-Control': 'no-store'})

    @app.get('/monitor/')
    def monitor_page():
        # This shell contains no account, game, or operational data. Its API
        # independently authorizes every refresh against the current session.
        return FileResponse(APP_ROOT / 'static' / 'monitor.html', headers={'Cache-Control': 'no-store'})
