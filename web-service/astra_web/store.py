"""Single-owner, transactional game records; user-controlled text is always data."""
import copy
import json
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone


class Conflict(ValueError):
    pass


class DailyResourceLimit(ValueError):
    """A known admission denial with a fixed, player-safe explanation."""
    code = 'daily_resource_limit'
    public_message = ('The chess player cannot start another response within the service’s daily resource allowance. '
                      'Your game is saved; please return later or ask the operator to increase the allowance.')

    def __init__(self):
        super().__init__(self.public_message)


def _matchup_identity(state):
    """Stable saved opponent identity, independent of current site defaults.

    Effort, persona revisions and runtime/profile upgrades do not create a new
    opponent. True pre-persona GLM games remain legacy-glm, not Arcturus.
    """
    profile = state.get('player_profile')
    if profile is None:
        profile = {}
    if not isinstance(profile, dict):
        return None
    model = profile.get('canonical_model') or profile.get('model') or state.get('model')
    if not isinstance(model, str) or not model:
        return None
    # Routing aliases do not change the underlying model. Keep all other model
    # identifiers exact rather than merging arbitrary model/version suffixes.
    for suffix in (':nitro', ':floor'):
        if model.endswith(suffix):
            model = model[:-len(suffix)]
            break
    persona = state.get('player_persona', profile.get('persona'))
    if persona is None:
        if model == 'gpt-6-astra':
            name = 'astra'
        elif model == 'z-ai/glm-5.3-flash':
            name = 'legacy-glm'
        else:
            return None
    elif isinstance(persona, dict):
        name = persona.get('name')
    else:
        return None
    if not isinstance(name, str) or not name:
        return None
    return name, model


class Store:
    def __init__(self, config):
        self.config = config
        with self.connection() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS games(id TEXT PRIMARY KEY, user_id TEXT NOT NULL,
                    updated REAL NOT NULL, state TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS games_user ON games(user_id);
                CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, game_id TEXT NOT NULL,
                    at REAL NOT NULL, kind TEXT NOT NULL, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS requests(game_id TEXT, request_id TEXT, body TEXT,
                    PRIMARY KEY(game_id,request_id));
                CREATE TABLE IF NOT EXISTS shares(token TEXT PRIMARY KEY, game_id TEXT UNIQUE,
                    created REAL NOT NULL, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS budget(day TEXT PRIMARY KEY, turns INTEGER DEFAULT 0,
                    tokens INTEGER DEFAULT 0, reserved INTEGER DEFAULT 0);
            """)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.config.db_path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def create(self, state):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            states = [json.loads(r[0]) for r in db.execute("SELECT state FROM games WHERE user_id=?", (state['user_id'],))]
            if sum(s['status'] != 'finished' for s in states) >= self.config.max_games_per_user:
                raise ValueError("Finish an existing game before starting another.")
            db.execute("INSERT INTO games VALUES(?,?,?,?)", (state['id'], state['user_id'], state['updated_at'], json.dumps(state)))
            self._event(db, state['id'], 'created', state)

    def get(self, game_id):
        with self.connection() as db:
            row = db.execute("SELECT state FROM games WHERE id=?", (game_id,)).fetchone()
        if row is None:
            raise KeyError("Game not found")
        return json.loads(row[0])

    def list(self, user_id=None):
        with self.connection() as db:
            rows = db.execute("SELECT state FROM games ORDER BY updated DESC" if user_id is None else
                              "SELECT state FROM games WHERE user_id=? ORDER BY updated DESC", () if user_id is None else (user_id,)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def matchup_record(self, state):
        """Read-only account/opponent totals; each completed game counts once.

        Deriving from game rows initializes historical totals without a
        migration, counter writes, or duplicate counts from action retries.
        Use the supplied current-game snapshot for its row so its inclusion
        agrees with the board even if that game changes during this read.
        Other games come from one fresh database read, never a cached counter.
        """
        record = dict(completed_games=0, human_wins=0, ai_wins=0, draws=0,
                      human_points=0, ai_points=0, includes_current_game=False)
        user_id = state.get('user_id')
        identity = _matchup_identity(state)
        if not isinstance(user_id, str) or not user_id or identity is None:
            return record
        with self.connection() as db:
            rows = db.execute('SELECT id,state FROM games WHERE user_id=?', (user_id,)).fetchall()
        for row in rows:
            current = row['id'] == state.get('id')
            other = state if current else json.loads(row['state'])
            if (other.get('user_id') != user_id or _matchup_identity(other) != identity
                    or other.get('status') != 'finished'
                    or other.get('result') not in ('1-0', '0-1', '1/2-1/2')
                    or other.get('human_side') not in ('white', 'black')
                    or other.get('astra_side') != ('black' if other['human_side'] == 'white' else 'white')):
                continue
            record['completed_games'] += 1
            record['includes_current_game'] |= current
            if other['result'] == '1/2-1/2':
                record['draws'] += 1
            elif other['result'] == ('1-0' if other['human_side'] == 'white' else '0-1'):
                record['human_wins'] += 1
            else:
                record['ai_wins'] += 1
        record['human_points'] = record['human_wins'] + record['draws'] / 2
        record['ai_points'] = record['ai_wins'] + record['draws'] / 2
        return record

    def mutate(self, game_id, fn, *, version=None, request_id=None, body=None, kind='update', increment=True, return_applied=False, transaction_hook=None):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT state FROM games WHERE id=?", (game_id,)).fetchone()
            if row is None:
                raise KeyError("Game not found")
            state = json.loads(row[0])
            encoded = json.dumps(body, sort_keys=True)
            if request_id:
                prior = db.execute("SELECT body FROM requests WHERE game_id=? AND request_id=?", (game_id, request_id)).fetchone()
                if prior:
                    if prior[0] != encoded:
                        raise Conflict("That request ID was already used for another action.")
                    return (state, False) if return_applied else state
            if version is not None and version != state['version']:
                raise Conflict("The game changed. Refresh the board and try again.")
            fn(state)
            if transaction_hook is not None:
                transaction_hook(state, db)
            if increment:
                state['version'] += 1
            state['updated_at'] = time.time()
            db.execute("UPDATE games SET state=?, updated=? WHERE id=?", (json.dumps(state), state['updated_at'], game_id))
            if request_id:
                db.execute("INSERT INTO requests VALUES(?,?,?)", (game_id, request_id, encoded))
            self._event(db, game_id, kind, {'version': state['version'], 'ply': len(state['moves']), 'request': body})
        return (state, True) if return_applied else state

    @staticmethod
    def _event(db, game_id, kind, data):
        db.execute("INSERT INTO events(game_id,at,kind,data) VALUES(?,?,?,?)", (game_id, time.time(), kind, json.dumps(data)))

    def audit(self, game_id, kind, data):
        with self.connection() as db:
            self._event(db, game_id, kind, data)

    def share(self, game_id, data):
        token = secrets.token_urlsafe(24)
        with self.connection() as db:
            db.execute("DELETE FROM shares WHERE game_id=?", (game_id,))
            db.execute("INSERT INTO shares VALUES(?,?,?,?)", (token, game_id, time.time(), json.dumps(data)))
        return token

    def revoke_share(self, game_id):
        with self.connection() as db:
            db.execute("DELETE FROM shares WHERE game_id=?", (game_id,))

    def public_replay(self, token):
        with self.connection() as db:
            row = db.execute("SELECT data FROM shares WHERE token=?", (token,)).fetchone()
        if row is None:
            raise KeyError("Replay not found")
        return json.loads(row[0])

    def reserve(self):
        day = datetime.now(timezone.utc).date().isoformat()
        amount = self.config.max_turn_tokens
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT OR IGNORE INTO budget(day) VALUES(?)", (day,))
            row = db.execute("SELECT * FROM budget WHERE day=?", (day,)).fetchone()
            if row['turns'] >= self.config.max_daily_turns or row['tokens'] + row['reserved'] + amount > self.config.max_daily_tokens:
                raise DailyResourceLimit()
            db.execute("UPDATE budget SET turns=turns+1,reserved=reserved+? WHERE day=?", (amount, day))
        return day, amount

    def settle(self, reservation, tokens=None):
        day, amount = reservation
        charged = amount if tokens is None else max(0, int(tokens))
        with self.connection() as db:
            db.execute("UPDATE budget SET reserved=MAX(0,reserved-?),tokens=tokens+? WHERE day=?", (amount, charged, day))

    def recover_reservations(self):
        # A crashed process may have spent its full reservation. Do not refund it.
        with self.connection() as db:
            db.execute("UPDATE budget SET tokens=tokens+reserved,reserved=0")
