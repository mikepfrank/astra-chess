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

    def mutate(self, game_id, fn, *, version=None, request_id=None, body=None, kind='update', increment=True, return_applied=False):
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
                raise ValueError("Astra has reached the service's daily resource allowance. Your game is saved; please return later.")
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
