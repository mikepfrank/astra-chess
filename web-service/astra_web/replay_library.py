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
                CREATE TABLE IF NOT EXISTS replay_versions(
                    game_id TEXT NOT NULL, archive_id TEXT NOT NULL UNIQUE,
                    state TEXT NOT NULL, include_commentary INTEGER NOT NULL,
                    generated_at REAL, error TEXT, created_at REAL NOT NULL,
                    PRIMARY KEY(game_id,include_commentary));
                CREATE TABLE IF NOT EXISTS replay_variant_jobs(
                    game_id TEXT NOT NULL, include_commentary INTEGER NOT NULL,
                    archive_id TEXT NOT NULL, state TEXT NOT NULL,
                    error TEXT, created_at REAL NOT NULL,
                    PRIMARY KEY(game_id,include_commentary));
                CREATE TABLE IF NOT EXISTS replay_variant_shares(
                    game_id TEXT NOT NULL, token TEXT NOT NULL UNIQUE,
                    archive_id TEXT NOT NULL, include_commentary INTEGER NOT NULL,
                    published_at REAL NOT NULL, metadata TEXT NOT NULL,
                    listed INTEGER NOT NULL,
                    PRIMARY KEY(game_id,include_commentary));
                CREATE TABLE IF NOT EXISTS replay_library_migrations(
                    name TEXT PRIMARY KEY, applied_at REAL NOT NULL);
            ''')

    @staticmethod
    def _variant(value):
        if value not in ('moves', 'chat'):
            raise HTTPException(400, 'Choose the moves or chat replay variant.')
        return value == 'chat'

    @staticmethod
    def _name(include_commentary):
        return 'chat' if include_commentary else 'moves'

    @staticmethod
    def _check_token(value):
        if not isinstance(value, str) or TOKEN.fullmatch(value) is None:
            raise HTTPException(404, 'Replay not found.')
        return value

    def _private_path(self, game_id, archive_id, include_commentary):
        return (self.private_dir / self._check_token(game_id) / self._name(include_commentary)
                / (self._check_token(archive_id) + '.html'))

    def _public_path(self, token):
        return self.public_dir / (self._check_token(token) + '.html')

    def _migrate_variants(self, db):
        if db.execute("SELECT 1 FROM replay_library_migrations WHERE name='independent-variants-v1'").fetchone():
            if any(db.execute('SELECT 1 FROM ' + table + ' LIMIT 1').fetchone() is not None
                   for table in ('replay_archives', 'replay_publications', 'replay_unlisted')):
                raise RuntimeError('Replay metadata was changed by an older service release after variant migration. '
                                   'Reconcile the retired replay tables before restarting; automatic import could restore revoked links.')
            return
        now = time.time()
        for row in db.execute('SELECT * FROM replay_archives').fetchall():
            game_id, archive_id, include = row['game_id'], row['archive_id'], bool(row['include_commentary'])
            old_path = self.private_dir / self._check_token(game_id) / (self._check_token(archive_id) + '.html')
            if row['state'] == 'ready' and old_path.is_file():
                _atomic_write(self._private_path(game_id, archive_id, include), self._read_page(old_path))
                db.execute('INSERT OR IGNORE INTO replay_versions VALUES(?,?,?,?,?,?,?)',
                           (game_id, archive_id, 'ready', int(include), row['generated_at'], None, row['generated_at'] or now))
            else:
                db.execute('INSERT OR IGNORE INTO replay_variant_jobs VALUES(?,?,?,?,?,?)',
                           (game_id, int(include), archive_id, 'error', row['error'] or INTERRUPTED, now))
        old_links = db.execute('''SELECT *,1 AS listed FROM replay_publications
            UNION ALL SELECT *,0 AS listed FROM replay_unlisted''').fetchall()
        for row in old_links:
            db.execute('INSERT OR IGNORE INTO replay_variant_shares VALUES(?,?,?,?,?,?,?)', tuple(row))
            game_id, archive_id, include = row['game_id'], row['archive_id'], bool(row['include_commentary'])
            current = db.execute('SELECT 1 FROM replay_versions WHERE game_id=? AND include_commentary=?',
                                 (game_id, int(include))).fetchone()
            if current is None and self._public_path(row['token']).is_file():
                # A previously shared opposite variant is still an owned replay.
                # Restore its private download from exactly those immutable bytes.
                _atomic_write(self._private_path(game_id, archive_id, include), self._read_page(self._public_path(row['token'])))
                db.execute('INSERT INTO replay_versions VALUES(?,?,?,?,?,?,?)',
                           (game_id, archive_id, 'ready', int(include), row['published_at'], None, row['published_at']))
        # Leave original file bytes intact, but retire old metadata atomically.
        # Prior-release rollback fails closed rather than resurrecting a link
        # that the owner subsequently revokes or deletes in this release.
        db.execute('DELETE FROM replay_archives')
        db.execute('DELETE FROM replay_publications')
        db.execute('DELETE FROM replay_unlisted')
        db.execute("INSERT INTO replay_library_migrations VALUES('independent-variants-v1',?)", (now,))

    def recover(self):
        # Run only while holding the service process lock.
        with self.lock, self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            self._migrate_variants(db)
            db.execute("UPDATE replay_variant_jobs SET state='error', error=? WHERE state='building'", (INTERRUPTED,))
        self._write_index()

    async def close(self):
        self.closing = True
        if self.tasks:
            await asyncio.gather(*list(self.tasks.values()), return_exceptions=True)

    @staticmethod
    def _scope(db, game_id, variant):
        if variant is not None:
            return ReplayLibrary._variant(variant)
        rows = db.execute('''SELECT include_commentary FROM replay_versions WHERE game_id=?
            UNION SELECT include_commentary FROM replay_variant_jobs WHERE game_id=?
            UNION SELECT include_commentary FROM replay_variant_shares WHERE game_id=?''',
                          (game_id, game_id, game_id)).fetchall()
        if len(rows) > 1:
            raise HTTPException(409, 'Choose which replay variant to change: moves or chat.')
        return bool(rows[0][0]) if rows else False

    def status(self, game_id, variant=None, *, strict_selection=False):
        if variant is not None:
            selected = self._variant(variant)
        with self.store.connection() as db:
            db.execute('BEGIN')
            versions = {bool(r['include_commentary']): r for r in db.execute('SELECT * FROM replay_versions WHERE game_id=?', (game_id,))}
            jobs = {bool(r['include_commentary']): r for r in db.execute('SELECT * FROM replay_variant_jobs WHERE game_id=?', (game_id,))}
            shares = {bool(r['include_commentary']): r for r in db.execute('SELECT * FROM replay_variant_shares WHERE game_id=?', (game_id,))}
            legacy = db.execute('SELECT token FROM shares WHERE game_id=?', (game_id,)).fetchone()
            if variant is None and strict_selection and len(set(versions) | set(jobs) | set(shares)) > 1:
                # Older clients carry only their visible chat checkbox and poll
                # without a variant. Never silently replace their selected ID
                # with an opposite variant generated in another browser tab.
                raise HTTPException(409, 'This game has multiple replay versions. Reload the page to choose Moves only or With chat.')
        if variant is None:
            activity = [(r['created_at'], k) for mapping in (versions, jobs) for k, r in mapping.items()]
            selected = max(activity)[1] if activity else next(iter(shares), False)
        variants = {}
        for include in (False, True):
            row, job, shared = versions.get(include), jobs.get(include), shares.get(include)
            ready = row is not None and row['state'] == 'ready'
            published = shared if shared is not None and shared['listed'] else None
            state = 'building' if job is not None and job['state'] == 'building' else 'ready' if ready else 'error' if job else 'none'
            variants[self._name(include)] = dict(
                variant=self._name(include), state=state,
                archive_id=row['archive_id'] if ready else job['archive_id'] if job else None,
                include_commentary=include, generated_at=row['generated_at'] if ready else None,
                error=job['error'] if job else None,
                pending_archive_id=job['archive_id'] if job is not None and job['state'] == 'building' else None,
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
        name = self._name(selected)
        return dict(variants[name], selected_variant=name, variants=variants)

    def start(self, state, include_commentary):
        if self.closing:
            raise HTTPException(503, 'Replay construction is shutting down. Please try again shortly.')
        if state['status'] != 'finished':
            raise HTTPException(409, 'Finish the game before constructing a replay.')
        game_id = self._check_token(state['id'])
        key = (game_id, bool(include_commentary))
        if key in self.tasks:
            raise HTTPException(409, 'This replay variant is already being constructed.')
        if len(self.tasks) >= MAX_PENDING_BUILDS:
            raise HTTPException(503, 'Replay construction is busy. Please try again shortly.', headers={'Retry-After': '10'})
        archive_id = secrets.token_hex(16)
        snapshot = deepcopy(state)
        with self.lock, self.store.connection() as db:
            db.execute('''INSERT INTO replay_variant_jobs VALUES(?,?,?,'building',NULL,?)
                ON CONFLICT(game_id,include_commentary) DO UPDATE SET archive_id=excluded.archive_id,
                state='building',error=NULL,created_at=excluded.created_at''',
                       (game_id, int(include_commentary), archive_id, time.time()))
        self.tasks[key] = asyncio.create_task(self._build(snapshot, archive_id, include_commentary))
        return self.status(game_id, self._name(include_commentary))

    async def _build(self, snapshot, archive_id, include_commentary):
        game_id = snapshot['id']
        try:
            async with self.worker:
                await asyncio.to_thread(self._construct, snapshot, archive_id, include_commentary)
        except Exception:
            with self.store.connection() as db:
                db.execute("UPDATE replay_variant_jobs SET state='error',error=? WHERE game_id=? AND archive_id=?",
                           (BUILD_ERROR, game_id, archive_id))
        finally:
            self.tasks.pop((game_id, bool(include_commentary)), None)

    def _construct(self, snapshot, archive_id, include_commentary):
        game_id = snapshot['id']
        if not include_commentary:
            snapshot['messages'] = []
        record = replay_archive.make_record(snapshot, self.config.data_dir)
        record['game']['id'] = archive_id
        output = self._private_path(game_id, archive_id, include_commentary)
        temporary = output.with_suffix('.building')
        try:
            replay_archive.build_archive(record, temporary)
            if temporary.stat().st_size > MAX_HTML_BYTES:
                raise ValueError('Replay is too large.')
            standalone_csp(temporary.read_text(encoding='utf-8'))
            with self.lock, self.store.connection() as db:
                db.execute('BEGIN IMMEDIATE')
                job = db.execute("SELECT * FROM replay_variant_jobs WHERE game_id=? AND include_commentary=? AND archive_id=? AND state='building'",
                                 (game_id, int(include_commentary), archive_id)).fetchone()
                if job is None:
                    raise ValueError('Replay construction no longer owns its pending revision.')
                temporary.replace(output)
                db.execute('''INSERT INTO replay_versions VALUES(?,?,'ready',?,?,NULL,?)
                    ON CONFLICT(game_id,include_commentary) DO UPDATE SET archive_id=excluded.archive_id,
                    state='ready',generated_at=excluded.generated_at,error=NULL,created_at=excluded.created_at''',
                           (game_id, archive_id, int(include_commentary), record['game']['exported_at'], job['created_at']))
                db.execute('DELETE FROM replay_variant_jobs WHERE game_id=? AND include_commentary=? AND archive_id=?',
                           (game_id, int(include_commentary), archive_id))
            # The directory belongs to this variant, never its opposite or a
            # shared snapshot. Delete superseded private bytes only after commit.
            for old in output.parent.glob('*.html'):
                if old != output:
                    old.unlink(missing_ok=True)
        finally:
            temporary.unlink(missing_ok=True)

    def _ready(self, db, game_id, archive_id):
        self._check_token(archive_id)
        row = db.execute("SELECT * FROM replay_versions WHERE game_id=? AND archive_id=? AND state='ready'", (game_id, archive_id)).fetchone()
        if row is None:
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
            row = self._ready(db, game_id, archive_id)
            return self._read_page(self._private_path(game_id, archive_id, bool(row['include_commentary'])))

    def publish(self, state, archive_id):
        return self.share(state, archive_id, listed=True)

    def share(self, state, archive_id, *, listed=False):
        self._check_token(archive_id)
        if type(listed) is not bool:
            raise HTTPException(400, 'Choose whether to list the replay publicly.')
        game_id, previous_token = state['id'], None
        with self.lock:
            with self.store.connection() as db:
                db.execute('BEGIN IMMEDIATE')
                existing = db.execute('SELECT * FROM replay_variant_shares WHERE game_id=? AND archive_id=?', (game_id, archive_id)).fetchone()
                if existing is not None:
                    include = bool(existing['include_commentary'])
                    self._read_page(self._public_path(existing['token']))
                    db.execute('UPDATE replay_variant_shares SET listed=? WHERE game_id=? AND include_commentary=?',
                               (int(listed), game_id, int(include)))
                else:
                    archive = self._ready(db, game_id, archive_id)
                    include = bool(archive['include_commentary'])
                    previous = db.execute('SELECT token FROM replay_variant_shares WHERE game_id=? AND include_commentary=?',
                                          (game_id, int(include))).fetchone()
                    token = secrets.token_hex(16)
                    page = self._read_page(self._private_path(game_id, archive_id, include))
                    _atomic_write(self._public_path(token), page)
                    metadata = dict(name=state['name'], human_side=state['human_side'], astra_side=state['astra_side'],
                                    result=state['result'], termination=state['termination'], created_at=state['created_at'], plies=len(state['moves']))
                    db.execute('''INSERT INTO replay_variant_shares VALUES(?,?,?,?,?,?,?)
                        ON CONFLICT(game_id,include_commentary) DO UPDATE SET token=excluded.token,
                        archive_id=excluded.archive_id,published_at=excluded.published_at,metadata=excluded.metadata,listed=excluded.listed''',
                               (game_id, token, archive_id, int(include), time.time(), json.dumps(metadata), int(listed)))
                    previous_token = previous['token'] if previous is not None else None
            if previous_token is not None:
                self._public_path(previous_token).unlink(missing_ok=True)
            self._write_index()
        return self.status(game_id, self._name(include))

    def unlist(self, game_id, variant=None):
        with self.lock:
            with self.store.connection() as db:
                db.execute('BEGIN IMMEDIATE')
                include = self._scope(db, game_id, variant)
                db.execute('UPDATE replay_variant_shares SET listed=0 WHERE game_id=? AND include_commentary=?', (game_id, int(include)))
            self._write_index()
        return self.status(game_id, self._name(include))

    def revoke(self, game_id, variant=None):
        with self.lock:
            with self.store.connection() as db:
                db.execute('BEGIN IMMEDIATE')
                include = self._scope(db, game_id, variant)
                row = db.execute('SELECT token FROM replay_variant_shares WHERE game_id=? AND include_commentary=?', (game_id, int(include))).fetchone()
                db.execute('DELETE FROM replay_variant_shares WHERE game_id=? AND include_commentary=?', (game_id, int(include)))
            if row is not None:
                self._public_path(row['token']).unlink(missing_ok=True)
            self._write_index()
        return self.status(game_id, self._name(include))

    def delete_variant(self, game_id, variant=None):
        with self.lock:
            with self.store.connection() as db:
                db.execute('BEGIN IMMEDIATE')
                include = self._scope(db, game_id, variant)
                job = db.execute('SELECT state FROM replay_variant_jobs WHERE game_id=? AND include_commentary=?', (game_id, int(include))).fetchone()
                if (game_id, include) in self.tasks or job is not None and job['state'] == 'building':
                    raise HTTPException(409, 'Wait for this replay variant to finish constructing before removing it.')
                row = db.execute('SELECT token FROM replay_variant_shares WHERE game_id=? AND include_commentary=?', (game_id, int(include))).fetchone()
                db.execute('DELETE FROM replay_variant_shares WHERE game_id=? AND include_commentary=?', (game_id, int(include)))
                db.execute('DELETE FROM replay_versions WHERE game_id=? AND include_commentary=?', (game_id, int(include)))
                db.execute('DELETE FROM replay_variant_jobs WHERE game_id=? AND include_commentary=?', (game_id, int(include)))
            if row is not None:
                self._public_path(row['token']).unlink(missing_ok=True)
            folder = self.private_dir / self._check_token(game_id) / self._name(include)
            for path in folder.glob('*.html'):
                path.unlink(missing_ok=True)
            self._write_index()
        return self.status(game_id, self._name(include))

    def public_page(self, token, *, with_visibility=False):
        self._check_token(token)
        with self.lock, self.store.connection() as db:
            row = db.execute('SELECT listed FROM replay_variant_shares WHERE token=?', (token,)).fetchone()
            if row is None:
                raise HTTPException(404, 'This replay is not publicly available.')
            page = self._read_page(self._public_path(token))
            return (page, bool(row['listed'])) if with_visibility else page

    def public_entries(self, page=1):
        if type(page) is not int or not 1 <= page <= 1_000_000:
            raise HTTPException(400, 'Invalid library page.')
        # Filter visibility before preferring chat. An unlisted chat variant
        # cannot hide or replace the owner's explicitly listed moves variant.
        selection = '''FROM replay_variant_shares AS candidate WHERE candidate.listed=1
            AND (candidate.include_commentary=1 OR NOT EXISTS(
                SELECT 1 FROM replay_variant_shares AS chat WHERE chat.game_id=candidate.game_id
                AND chat.include_commentary=1 AND chat.listed=1))'''
        with self.store.connection() as db:
            db.execute('BEGIN')
            total = db.execute('SELECT COUNT(*) ' + selection).fetchone()[0]
            rows = db.execute('SELECT candidate.* ' + selection + ' ORDER BY published_at DESC,token LIMIT ? OFFSET ?',
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
    async def archive_status(request: Request, game_id: str, variant: str | None = None):
        owned(request, game_id)
        return library.status(game_id, variant, strict_selection=True)

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
    async def archive_unlist(request: Request, game_id: str, variant: str | None = None):
        owned(request, game_id)
        return await asyncio.to_thread(library.unlist, game_id, variant)

    @app.delete('/api/games/{game_id}/archive/publication')
    async def archive_revoke(request: Request, game_id: str, variant: str | None = None):
        owned(request, game_id)
        return await asyncio.to_thread(library.revoke, game_id, variant)

    @app.delete('/api/games/{game_id}/archive')
    async def archive_delete(request: Request, game_id: str, variant: str | None = None):
        owned(request, game_id)
        return await asyncio.to_thread(library.delete_variant, game_id, variant)

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
