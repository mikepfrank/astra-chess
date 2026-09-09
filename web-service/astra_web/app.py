"""Local-first web service. Run exactly one server process; SQLite owns durable state."""
import asyncio
from collections import defaultdict, deque
from contextlib import asynccontextmanager
import json
import time
from urllib.parse import urlsplit
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from .config import Config, APP_ROOT
from .identity import Identity, router as identity_router, require_user
from .store import Store, Conflict
from .supervisor import Supervisor
from . import chess_game as game


def create_app(config=None, player_factory=None):
    config = config or Config()
    config.validate()
    identity = Identity(config)
    store = Store(config)
    supervisor = Supervisor(config, store, identity, player_factory)

    @asynccontextmanager
    async def lifespan(app):
        # Prevent accidental multi-worker processes from independently scheduling the same game.
        from .process_lock import ProcessLock
        with ProcessLock(config.data_dir / 'service.lock'):
            supervisor.recover()
            async def maintain():
                while True:
                    await asyncio.sleep(60)
                    supervisor.suspend_inactive()
            sweeper = asyncio.create_task(maintain())
            try:
                yield
            finally:
                sweeper.cancel()
                await asyncio.gather(sweeper, return_exceptions=True)
                await supervisor.close()

    app = FastAPI(title='Astra Chess', docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.identity, app.state.store, app.state.supervisor, app.state.config = identity, store, supervisor, config
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[urlsplit(config.origin).hostname])
    rate = defaultdict(deque)
    auth_slots = asyncio.Semaphore(2)

    @app.middleware('http')
    async def boundary(request, call_next):
        path = request.url.path
        mutating = request.method not in {'GET', 'HEAD', 'OPTIONS'}
        ip = request.client.host if request.client else 'local'
        now = time.monotonic()
        category = 'auth' if path.startswith('/api/auth/') and mutating else 'write' if mutating else 'read'
        limit = 10 if category == 'auth' else 30 if category == 'write' else 240
        if len(rate) > 4096:
            for key in list(rate):
                if not rate[key] or rate[key][-1] < now - 60:
                    del rate[key]
            if len(rate) > 4096:
                return JSONResponse({'detail': 'The service is busy. Please try again later.'}, status_code=503)
        bucket = rate[(ip, category)]
        while bucket and bucket[0] < now - 60:
            bucket.popleft()
        if len(bucket) >= limit:
            return JSONResponse({'detail': 'Please wait a moment before trying again.'}, status_code=429, headers={'Retry-After':'60'})
        bucket.append(now)
        if mutating:
            if request.headers.get('origin') != config.origin:
                return JSONResponse({'detail': 'Origin is not allowed.'}, status_code=403)
            if request.headers.get('content-type', '').split(';')[0] != 'application/json' and request.method != 'DELETE':
                return JSONResponse({'detail': 'Use application/json.'}, status_code=415)
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 16_384:
                    return JSONResponse({'detail': 'Request is too large.'}, status_code=413)
            request._body = bytes(body)
            exempt = path in {'/api/auth/register', '/api/auth/login', '/api/auth/forgot', '/api/auth/reset'}
            if not exempt and not identity.csrf_valid(request.cookies.get('astra_session'), request.headers.get('x-csrf-token')):
                return JSONResponse({'detail': 'Session verification failed. Refresh the page.'}, status_code=403)
        if category == 'auth':
            async with auth_slots:
                response = await call_next(request)
        else:
            response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        response.headers['Cache-Control'] = 'no-store' if path.startswith('/api/') or path.startswith('/replay/') else 'no-cache'
        if config.secure_cookies:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        return response

    @app.exception_handler(Conflict)
    async def conflict(request, exc):
        return JSONResponse({'detail': str(exc)}, status_code=409)

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse({'detail': str(exc)}, status_code=400)

    @app.exception_handler(KeyError)
    async def missing(request, exc):
        return JSONResponse({'detail': 'Record not found.'}, status_code=404)

    app.include_router(identity_router)

    async def body(request):
        try:
            data = await request.json()
        except (ValueError, UnicodeError):
            raise HTTPException(400, 'Invalid JSON.')
        if not isinstance(data, dict):
            raise HTTPException(400, 'Expected an object.')
        return data

    def owned(request, game_id):
        user = require_user(request)
        state = store.get(game_id)
        if state['user_id'] != user['id']:
            raise HTTPException(404, 'Game not found.')
        return state

    @app.get('/api/config')
    async def public_config():
        return dict(player_available=supervisor.available, player_mode=config.player_mode,
                    model=config.model, reasoning=config.reasoning, suspend_hours=config.suspend_hours)

    @app.get('/api/games')
    async def games(request: Request):
        user = require_user(request)
        keys = ('id', 'human_side', 'status', 'result', 'updated_at')
        return {'games': [dict(**{k:s[k] for k in keys}, ply=len(s['moves'])) for s in store.list(user['id'])]}

    @app.post('/api/games', status_code=201)
    async def create_game(request: Request):
        user = require_user(request)
        data = await body(request)
        if set(data) != {'side'} or data['side'] not in ('white', 'black'):
            raise ValueError('Choose white or black.')
        state = game.new_game(user, data['side'], config)
        store.create(state)
        if state['astra_side'] == 'white':
            supervisor.schedule(state['id'])
        return game.snapshot(store.get(state['id']))

    @app.get('/api/games/{game_id}')
    async def get_game(request: Request, game_id: str):
        return game.snapshot(owned(request, game_id))

    @app.post('/api/games/{game_id}/actions')
    async def action(request: Request, game_id: str):
        owned(request, game_id)
        data = await body(request)
        if set(data) - {'action', 'move', 'text', 'version', 'request_id'}:
            raise ValueError('Unsupported action fields.')
        if type(data.get('version')) is not int or not isinstance(data.get('request_id'), str) or not 8 <= len(data['request_id']) <= 100:
            raise ValueError('Actions require a board version and a unique request ID.')
        act = data.get('action')
        if not isinstance(act, str):
            raise ValueError('A game action must be a string.')
        def apply(s):
            if s['status'] == 'finished' and act != 'message':
                raise ValueError('This game has finished.')
            if s['status'] == 'suspended' and act not in ('resume', 'resign'):
                raise ValueError('Resume the saved game first.')
            s['last_human_activity'] = time.time()
            if act == 'move':
                game.apply_move(s, data.get('move'), 'human')
            elif act == 'message':
                last = [m for m in s['messages'] if m['author'] == 'human' and m['created_at'] > time.time()-60]
                if len(last) >= config.max_messages_per_minute:
                    raise ValueError('Please give Astra a moment before sending another message.')
                if not isinstance(data.get('text'), str):
                    raise ValueError('Message text is required.')
                game.message(s, 'human', data['text'])
            elif act == 'resign':
                game.finish(s, '0-1' if s['human_side'] == 'white' else '1-0', 'resignation')
            elif act == 'offer_draw':
                if s['draw_offer']:
                    raise ValueError('A draw offer is already pending.')
                s['draw_offer'] = 'human'
            elif act == 'accept_draw':
                if s['draw_offer'] != 'astra':
                    raise ValueError('There is no Astra draw offer to accept.')
                game.finish(s, '1/2-1/2', 'agreement')
            elif act == 'decline_draw':
                if s['draw_offer'] != 'astra':
                    raise ValueError('There is no Astra draw offer to decline.')
                s['draw_offer'] = None
            elif act == 'claim_draw':
                if game.side_to_move(s) != s['human_side'] or not game.claimable(s, data.get('move')):
                    raise ValueError('No valid draw claim is available.')
                game.finish(s, '1/2-1/2', 'draw_claim')
            elif act in ('resume', 'retry'):
                if act == 'retry' and s['worker']['state'] not in ('error', 'disabled'):
                    raise ValueError('There is no interrupted Astra response to retry.')
                s['status'] = 'active'
            else:
                raise ValueError('Unsupported game action.')
        state, applied = store.mutate(game_id, apply, version=data['version'], request_id=data['request_id'], body=data, kind='human_action', return_applied=True)
        if not applied:
            return game.snapshot(state)
        if state['status'] == 'finished':
            await supervisor.cancel(game_id)
        elif act in {'move','message','offer_draw','retry'} or act == 'resume' and (game.side_to_move(state) == state['astra_side'] or state['draw_offer'] == 'human' or state['worker']['state'] in {'error','disabled'}):
            supervisor.schedule(game_id)
        return game.snapshot(store.get(game_id))

    @app.get('/api/games/{game_id}/pgn')
    async def download_pgn(request: Request, game_id: str):
        state = owned(request, game_id)
        return PlainTextResponse(game.pgn(state), media_type='application/x-chess-pgn', headers={'Content-Disposition': 'attachment; filename="astra-game.pgn"'})

    @app.post('/api/games/{game_id}/share')
    async def share(request: Request, game_id: str):
        state = owned(request, game_id)
        data = await body(request)
        if state['status'] != 'finished':
            raise ValueError('Only completed games can be shared.')
        if set(data) != {'include_commentary'} or type(data['include_commentary']) is not bool:
            raise ValueError('Explicitly choose whether to include commentary.')
        public = {k: state[k] for k in ('name','human_side','astra_side','result','termination','moves','model','reasoning','engine_fingerprint')}
        public.update(initial_fen=game.START_FEN, messages=state['messages'] if data['include_commentary'] else [])
        token = store.share(game_id, public)
        store.audit(game_id, 'replay_shared', {'include_commentary': data['include_commentary']})
        return {'url': config.origin + '/replay/' + token}

    @app.delete('/api/games/{game_id}/share')
    async def revoke_share(request: Request, game_id: str):
        owned(request, game_id)
        store.revoke_share(game_id)
        store.audit(game_id, 'replay_revoked', {})
        return {'revoked': True}

    @app.get('/api/replays/{token}')
    async def replay_data(token: str):
        return store.public_replay(token)

    @app.get('/replay/{token}')
    async def replay_page(token: str):
        store.public_replay(token)
        return FileResponse(APP_ROOT / 'static' / 'replay.html')

    @app.get('/')
    async def index():
        return FileResponse(APP_ROOT / 'static' / 'index.html')

    @app.get('/health')
    async def health():
        return {'ok': True}

    app.mount('/static', StaticFiles(directory=APP_ROOT / 'static'), name='static')
    return app
