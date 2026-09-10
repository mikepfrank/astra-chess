"""Owner-created offline replays, unlisted links, and an opt-in public library.

Generation reuses the first hosted-game archive workflow: validated saved moves,
recorded evaluations, and optional public chat. It never invokes a player or an
engine. SQLite is authoritative for publication; files are immutable snapshots,
and the generated index is a rebuildable projection of the publication table.
"""
import asyncio
import base64
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from html import escape
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import secrets
import threading
import time

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse

from . import replay_archive


MAX_PENDING_BUILDS = 8
MAX_HTML_BYTES = 32_000_000
PAGE_SIZE = 50
TOKEN = re.compile(r'[0-9a-f]{32}')
INTERRUPTED = 'Replay construction was interrupted. Please construct it again.'
BUILD_ERROR = 'The replay could not be constructed. Your game is saved; please try again.'


class _Scripts(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.collecting = False
        self.parts = []
        self.hashes = []

    def handle_starttag(self, tag, attrs):
        if tag == 'script':
            if dict(attrs).get('src'):
                raise ValueError('Standalone replays cannot load external scripts.')
            self.collecting, self.parts = True, []

    def handle_data(self, data):
        if self.collecting:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == 'script' and self.collecting:
            digest = hashlib.sha256(''.join(self.parts).encode('utf-8')).digest()
            self.hashes.append("'sha256-" + base64.b64encode(digest).decode('ascii') + "'")
            self.collecting = False


def standalone_csp(page):
    """Allow only this artifact's inline scripts; block every network request.

    Inline styles are needed for the shared board animation and SVG pieces.
    Normalize line endings as the HTML parser does before hashing script text.
    """
    scripts = _Scripts()
    scripts.feed(page.replace('\r\n', '\n').replace('\r', '\n'))
    allowed = ' '.join(dict.fromkeys(scripts.hashes)) or "'none'"
    return ("default-src 'none'; script-src " + allowed + "; script-src-attr 'none'; "
            "style-src 'unsafe-inline'; img-src data:; font-src 'none'; connect-src 'none'; "
            "object-src 'none'; frame-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")


def standalone_response(page, *, filename=None):
    headers = {'Content-Security-Policy': standalone_csp(page), 'Cache-Control': 'no-store'}
    if filename is not None:
        # Filename is operator-authored, never taken from a player name.
        if not re.fullmatch(r'[a-zA-Z0-9_.-]+', filename):
            raise ValueError('Invalid replay download filename.')
        headers['Content-Disposition'] = f'attachment; filename="{filename}"'
    return HTMLResponse(page, headers=headers)


def _atomic_write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name('.' + path.name + '.' + secrets.token_hex(8) + '.tmp')
    try:
        temporary.write_text(content, encoding='utf-8')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class ReplayLibrary:
    def __init__(self, config, store):
        self.config, self.store = config, store
        self.private_dir = config.data_dir / 'replay-archives'
        self.public_dir = config.data_dir / 'public-replays'
        self.private_dir.mkdir(parents=True, exist_ok=True)
        self.public_dir.mkdir(parents=True, exist_ok=True)
        self.tasks = {}
        self.worker = asyncio.Semaphore(1)
        self.lock = threading.RLock()
        self.closing = False
        with store.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS replay_archives(
                    game_id TEXT PRIMARY KEY, archive_id TEXT NOT NULL UNIQUE,
                    state TEXT NOT NULL, include_commentary INTEGER NOT NULL,
                    generated_at REAL, error TEXT);
                CREATE TABLE IF NOT EXISTS replay_publications(
                    game_id TEXT PRIMARY KEY, token TEXT NOT NULL UNIQUE,
                    archive_id TEXT NOT NULL, include_commentary INTEGER NOT NULL,
                    published_at REAL NOT NULL, metadata TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS replay_unlisted(
                    game_id TEXT PRIMARY KEY, token TEXT NOT NULL UNIQUE,
                    archive_id TEXT NOT NULL, include_commentary INTEGER NOT NULL,
                    published_at REAL NOT NULL, metadata TEXT NOT NULL);
            ''')

    def recover(self):
        """Call under the service process lock; interrupted builds need a retry."""
        with self.lock, self.store.connection() as db:
            db.execute("UPDATE replay_archives SET state='error', error=? WHERE state='building'", (INTERRUPTED,))
        self._write_index()

    async def close(self):
        """Drain the bounded queue instead of abandoning live file writes."""
        self.closing = True
        if self.tasks:
            await asyncio.gather(*list(self.tasks.values()), return_exceptions=True)

    @staticmethod
    def _check_token(value):
        if not isinstance(value, str) or TOKEN.fullmatch(value) is None:
            raise HTTPException(404, 'Replay not found.')
        return value

    def _private_path(self, game_id, archive_id):
        return self.private_dir / self._check_token(game_id) / (self._check_token(archive_id) + '.html')

    def _public_path(self, token):
        return self.public_dir / (self._check_token(token) + '.html')

    @staticmethod
    def _shared(db, game_id):
        # Existing publications remain listed with no destructive migration.
        # Keep unlisted snapshots in a separate additive table so an older
        # application rollback cannot inadvertently put them in its public list.
        return db.execute('''SELECT *, 1 AS listed FROM replay_publications WHERE game_id=?
            UNION ALL SELECT *, 0 AS listed FROM replay_unlisted WHERE game_id=?''',
                          (game_id, game_id)).fetchone()

    def status(self, game_id):
        with self.store.connection() as db:
            row = db.execute('SELECT * FROM replay_archives WHERE game_id=?', (game_id,)).fetchone()
            shared = self._shared(db, game_id)
            legacy = db.execute('SELECT token FROM shares WHERE game_id=?', (game_id,)).fetchone()
        published = shared if shared is not None and shared['listed'] else None
        ready = row is not None and row['state'] == 'ready'
        return dict(state=row['state'] if row else 'none', archive_id=row['archive_id'] if row else None,
                    include_commentary=bool(row['include_commentary']) if row else None,
                    generated_at=row['generated_at'] if row else None, error=row['error'] if row else None,
                    download_url=f"/api/games/{game_id}/archive/download?archive_id={row['archive_id']}" if ready else None,
                    published=published is not None,
                    public_url=f"/games/{published['token']}.html" if published else None,
                    published_archive_id=published['archive_id'] if published else None,
                    public_include_commentary=bool(published['include_commentary']) if published else None,
                    shared=shared is not None, listed=published is not None,
                    share_url=f"/games/{shared['token']}.html" if shared else None,
                    shared_archive_id=shared['archive_id'] if shared else None,
                    shared_include_commentary=bool(shared['include_commentary']) if shared else None,
                    legacy_share_url=f"/replay/{legacy['token']}" if legacy else None)

    def start(self, state, include_commentary):
        if self.closing:
            raise HTTPException(503, 'Replay construction is shutting down. Please try again shortly.')
        if state['status'] != 'finished':
            raise HTTPException(409, 'Finish the game before constructing a replay.')
        game_id = self._check_token(state['id'])
        if game_id in self.tasks:
            raise HTTPException(409, 'A replay is already being constructed for this game.')
        if len(self.tasks) >= MAX_PENDING_BUILDS:
            raise HTTPException(503, 'Replay construction is busy. Please try again shortly.', headers={'Retry-After': '10'})
        archive_id = secrets.token_hex(16)
        snapshot = deepcopy(state)
        with self.lock, self.store.connection() as db:
            db.execute('''INSERT INTO replay_archives VALUES(?,?,'building',?,NULL,NULL)
                ON CONFLICT(game_id) DO UPDATE SET archive_id=excluded.archive_id, state='building',
                include_commentary=excluded.include_commentary, generated_at=NULL, error=NULL''',
                       (game_id, archive_id, int(include_commentary)))
        # Register before returning; no await separates admission from registration.
        self.tasks[game_id] = asyncio.create_task(self._build(snapshot, archive_id, include_commentary))
        return self.status(game_id)

    async def _build(self, snapshot, archive_id, include_commentary):
        game_id = snapshot['id']
        try:
            async with self.worker:
                await asyncio.to_thread(self._construct, snapshot, archive_id, include_commentary)
        except Exception:
            with self.store.connection() as db:
                db.execute("UPDATE replay_archives SET state='error', error=? WHERE game_id=? AND archive_id=?",
                           (BUILD_ERROR, game_id, archive_id))
        finally:
            self.tasks.pop(game_id, None)

    def _construct(self, snapshot, archive_id, include_commentary):
        game_id = snapshot['id']
        if not include_commentary:
            # Exclude chat before validation or serialization, including malformed
            # legacy chat that is irrelevant to a moves-only archive.
            snapshot['messages'] = []
        record = replay_archive.make_record(snapshot, self.config.data_dir)
        # The public artifact needs a stable opaque identity, not the private
        # application's game identifier or any account/authentication metadata.
        record['game']['id'] = archive_id
        output = self._private_path(game_id, archive_id)
        temporary = output.with_suffix('.building')
        try:
            replay_archive.build_archive(record, temporary)
            if temporary.stat().st_size > MAX_HTML_BYTES:
                raise ValueError('Replay is too large.')
            page = temporary.read_text(encoding='utf-8')
            standalone_csp(page)  # Fail before marking an unsupported artifact ready.
            temporary.replace(output)
            with self.lock, self.store.connection() as db:
                db.execute("UPDATE replay_archives SET state='ready', generated_at=?, error=NULL WHERE game_id=? AND archive_id=?",
                           (record['game']['exported_at'], game_id, archive_id))
            # Only the current private download is retained. Public copies have
            # their own paths and remain unchanged by this cleanup.
            for old in output.parent.glob('*.html'):
                if old != output:
                    old.unlink(missing_ok=True)
        finally:
            temporary.unlink(missing_ok=True)

    def _ready(self, db, game_id, archive_id):
        self._check_token(archive_id)
        row = db.execute('SELECT * FROM replay_archives WHERE game_id=?', (game_id,)).fetchone()
        if row is None or row['state'] != 'ready' or row['archive_id'] != archive_id:
            raise HTTPException(409, 'This replay revision is no longer ready. Refresh the replay dialog.')
        return row

    @staticmethod
    def _read_page(path):
        try:
            if path.stat().st_size > MAX_HTML_BYTES:
                raise HTTPException(503, 'The replay is unavailable. Please construct it again.')
            return path.read_text(encoding='utf-8')
        except FileNotFoundError:
            raise HTTPException(404, 'Replay not found. Please construct it again.') from None

    def download(self, game_id, archive_id):
        with self.lock, self.store.connection() as db:
            self._ready(db, game_id, archive_id)
            return self._read_page(self._private_path(game_id, archive_id))

    def publish(self, state, archive_id):
        """Compatibility for existing tabs: publishing explicitly lists a replay."""
        return self.share(state, archive_id, listed=True)

    @staticmethod
    def _set_link(db, values, *, listed):
        game_id = values[0]
        db.execute('DELETE FROM replay_publications WHERE game_id=?', (game_id,))
        db.execute('DELETE FROM replay_unlisted WHERE game_id=?', (game_id,))
        if listed:
            db.execute('INSERT INTO replay_publications VALUES(?,?,?,?,?,?)', values)
        else:
            db.execute('INSERT INTO replay_unlisted VALUES(?,?,?,?,?,?)', values)

    def share(self, state, archive_id, *, listed=False):
        """Share an exact snapshot; visibility toggles preserve its URL and bytes."""
        self._check_token(archive_id)
        if type(listed) is not bool:
            raise HTTPException(400, 'Choose whether to list the replay publicly.')
        game_id = state['id']
        previous_token = None
        with self.lock:
            with self.store.connection() as db:
                db.execute('BEGIN IMMEDIATE')
                previous = self._shared(db, game_id)
                if previous is not None and previous['archive_id'] == archive_id:
                    # This immutable snapshot can still be listed/unlisted after
                    # a newer private replay has been generated. Never substitute
                    # the newer replay's chat selection while changing visibility.
                    self._read_page(self._public_path(previous['token']))
                    values = tuple(previous[key] for key in ('game_id', 'token', 'archive_id',
                                   'include_commentary', 'published_at', 'metadata'))
                else:
                    archive = self._ready(db, game_id, archive_id)
                    # Explicitly sharing a new revision revokes the old link;
                    # changing visibility of this revision never rotates it.
                    token = secrets.token_hex(16)
                    page = self._read_page(self._private_path(game_id, archive_id))
                    _atomic_write(self._public_path(token), page)
                    metadata = dict(name=state['name'], human_side=state['human_side'], astra_side=state['astra_side'],
                                    result=state['result'], termination=state['termination'],
                                    created_at=state['created_at'], plies=len(state['moves']))
                    values = (game_id, token, archive_id, archive['include_commentary'], time.time(), json.dumps(metadata))
                    previous_token = previous['token'] if previous is not None else None
                self._set_link(db, values, listed=listed)
            if previous_token is not None:
                self._public_path(previous_token).unlink(missing_ok=True)
            self._write_index()
        return self.status(game_id)

    def unlist(self, game_id):
        """Remove discovery through the library while retaining the shared URL."""
        with self.lock:
            with self.store.connection() as db:
                db.execute('BEGIN IMMEDIATE')
                row = db.execute('SELECT * FROM replay_publications WHERE game_id=?', (game_id,)).fetchone()
                if row is not None:
                    self._set_link(db, tuple(row), listed=False)
            self._write_index()
        return self.status(game_id)

    def revoke(self, game_id):
        with self.lock:
            with self.store.connection() as db:
                db.execute('BEGIN IMMEDIATE')
                row = self._shared(db, game_id)
                db.execute('DELETE FROM replay_publications WHERE game_id=?', (game_id,))
                db.execute('DELETE FROM replay_unlisted WHERE game_id=?', (game_id,))
            if row is not None:
                self._public_path(row['token']).unlink(missing_ok=True)
            self._write_index()
        return self.status(game_id)

    def public_page(self, token, *, with_visibility=False):
        self._check_token(token)
        with self.lock, self.store.connection() as db:
            row = db.execute('''SELECT token, 1 AS listed FROM replay_publications WHERE token=?
                UNION ALL SELECT token, 0 AS listed FROM replay_unlisted WHERE token=?''', (token, token)).fetchone()
            if row is None:
                raise HTTPException(404, 'This replay is not publicly available.')
            page = self._read_page(self._public_path(token))
            return (page, bool(row['listed'])) if with_visibility else page

    def public_entries(self, page=1):
        if type(page) is not int or not 1 <= page <= 1_000_000:
            raise HTTPException(400, 'Invalid library page.')
        with self.store.connection() as db:
            total = db.execute('SELECT COUNT(*) FROM replay_publications').fetchone()[0]
            rows = db.execute('SELECT * FROM replay_publications ORDER BY published_at DESC, token LIMIT ? OFFSET ?',
                              (PAGE_SIZE, (page - 1) * PAGE_SIZE)).fetchall()
        entries = [dict(**json.loads(row['metadata']), include_commentary=bool(row['include_commentary']),
                        published_at=row['published_at'], public_url=f"/games/{row['token']}.html") for row in rows]
        return dict(games=entries, page=page, page_size=PAGE_SIZE, total=total)

    def _index(self, page=1):
        data = self.public_entries(page)
        rows = []
        for entry in data['games']:
            name = escape(entry['name'])
            date = datetime.fromtimestamp(entry['created_at'], timezone.utc).strftime('%b %d, %Y')
            white, black = (name, 'Astra') if entry['human_side'] == 'white' else ('Astra', name)
            rows.append(f'<li><a href="{entry["public_url"]}">{white} <span>vs.</span> {black}</a>'
                        f'<p>{date} UTC · {escape(entry["result"])} · {(entry["plies"] + 1) // 2} moves'
                        f' · {"Chat included" if entry["include_commentary"] else "Moves only"}</p></li>')
        navigation = []
        if page > 1:
            navigation.append(f'<a href="?page={page - 1}">← Newer games</a>')
        if page * PAGE_SIZE < data['total']:
            navigation.append(f'<a href="?page={page + 1}">Older games →</a>')
        return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Public game replays · Astra plays chess</title><style>
:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#0d171e;color:#e8eef0;font:17px/1.65 system-ui,sans-serif}
main{max-width:850px;margin:0 auto;padding:3rem 1.5rem}h1{font:2.5rem/1.15 Georgia,serif;margin:.6rem 0 1.4rem}
a{color:#81cec1;text-underline-offset:.2em}a:hover{color:#b5eee4}.eyebrow{font-size:.8rem;letter-spacing:.14em;color:#81cec1;text-transform:uppercase}
ul{list-style:none;padding:0}li{padding:1.2rem 0;border-bottom:1px solid #2c424e}li>a{font-size:1.2rem}p{color:#a9bdc7;margin:.3rem 0}
li span{color:#a9bdc7}nav{display:flex;gap:2rem;padding:1rem 0}footer{border-top:1px solid #2c424e;margin-top:2.5rem;padding-top:1.5rem}
</style><main><a href="/">← Play Astra</a><p class="eyebrow">Shared by the players</p><h1>Public game replays</h1>
<p>Explore completed games, move by move. Players choose whether to include their conversation and can remove their replay from this library.</p>''' + (
            '<ul>' + ''.join(rows) + '</ul>' if rows else '<p>No games have been published to this list yet.</p>') + (
            '<nav aria-label="Library pages">' + ''.join(navigation) + '</nav>' if navigation else '') + '''
<footer><a href="/experiments/">Explore Astra’s earlier chess experiments →</a></footer></main></html>'''

    def _write_index(self):
        with self.lock:
            _atomic_write(self.public_dir / 'index.html', self._index())

    def index_page(self, page=1):
        with self.lock:
            # Always consult durable publication state. Never serve an old
            # generated file after revocation or a partially completed restart.
            content = self._index(page)
            if page == 1:
                _atomic_write(self.public_dir / 'index.html', content)
            return content


def install_replay_library(app, config, store, owned, body):
    """Register after defining shared ownership/body helpers and before mounts."""
    library = ReplayLibrary(config, store)

    @app.get('/api/games/{game_id}/archive')
    async def archive_status(request: Request, game_id: str):
        owned(request, game_id)
        return library.status(game_id)

    @app.post('/api/games/{game_id}/archive', status_code=202)
    async def archive_create(request: Request, game_id: str):
        state = owned(request, game_id)
        data = await body(request)
        if set(data) != {'include_commentary'} or type(data['include_commentary']) is not bool:
            raise HTTPException(400, 'Choose whether to include the conversation.')
        return library.start(state, data['include_commentary'])

    @app.get('/api/games/{game_id}/archive/download')
    async def archive_download(request: Request, game_id: str, archive_id: str):
        owned(request, game_id)
        page = await asyncio.to_thread(library.download, game_id, archive_id)
        return standalone_response(page, filename=f'astra-replay-{archive_id}.html')

    @app.post('/api/games/{game_id}/archive/publish')
    async def archive_publish(request: Request, game_id: str):
        state = owned(request, game_id)
        if state['status'] != 'finished':
            raise HTTPException(409, 'Only finished games can be published.')
        data = await body(request)
        if set(data) != {'archive_id'} or not isinstance(data['archive_id'], str):
            raise HTTPException(400, 'Choose the ready replay revision to publish.')
        return await asyncio.to_thread(library.publish, state, data['archive_id'])

    @app.post('/api/games/{game_id}/archive/share')
    async def archive_share(request: Request, game_id: str):
        state = owned(request, game_id)
        if state['status'] != 'finished':
            raise HTTPException(409, 'Only finished games can be shared.')
        data = await body(request)
        if (set(data) - {'archive_id', 'listed'} or not isinstance(data.get('archive_id'), str)
                or type(data.get('listed', False)) is not bool):
            raise HTTPException(400, 'Choose a replay revision and whether to list it publicly.')
        return await asyncio.to_thread(library.share, state, data['archive_id'], listed=data.get('listed', False))

    @app.delete('/api/games/{game_id}/archive/listing')
    async def archive_unlist(request: Request, game_id: str):
        owned(request, game_id)
        return await asyncio.to_thread(library.unlist, game_id)

    @app.delete('/api/games/{game_id}/archive/publication')
    async def archive_revoke(request: Request, game_id: str):
        owned(request, game_id)
        return await asyncio.to_thread(library.revoke, game_id)

    @app.get('/games/')
    async def library_index(page: int = 1):
        content = await asyncio.to_thread(library.index_page, page)
        return standalone_response(content)

    @app.get('/api/public-replays')
    async def public_replays(page: int = 1):
        return library.public_entries(page)

    @app.get('/games/{token}.html')
    async def public_replay(token: str):
        page, listed = await asyncio.to_thread(library.public_page, token, with_visibility=True)
        response = standalone_response(page)
        # An unlisted URL is a bearer link, not an account-private resource.
        # Ask search engines not to index it even if someone links it elsewhere.
        if not listed:
            response.headers['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
        return response

    return library
