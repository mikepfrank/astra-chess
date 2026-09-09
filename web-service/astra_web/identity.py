"""Cookie identities, optional passwords/reset email, and opt-in player notes.

The app applies Origin, request-size, rate-limit and CSRF middleware to this
router. These handlers run in FastAPI's worker pool because SQLite, scrypt and
SMTP are synchronous. No database connection is shared between operations.
"""

from contextlib import contextmanager
from email.message import EmailMessage
import hashlib
import hmac
import re
import secrets
import smtplib
import sqlite3
import ssl
import time
import unicodedata
from typing import Callable

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from .config import Config


COOKIE_NAME = "astra_session"
SESSION_SECONDS = 30 * 24 * 60 * 60
RESET_SECONDS = 60 * 60
PASSWORD_MIN_LENGTH = 10
MEMORY_MAX_LENGTH = 4000
SCRYPT_N, SCRYPT_R, SCRYPT_P = 32768, 8, 3


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N,
                            r=SCRYPT_R, p=SCRYPT_P, dklen=64, maxmem=64 * 1024 * 1024)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${digest.hex()}"


def _password_matches(password: str, encoded: str) -> bool:
    try:
        method, n, r, p, salt, expected = encoded.split("$")
        if (method, n, r, p) != ("scrypt", str(SCRYPT_N), str(SCRYPT_R), str(SCRYPT_P)):
            return False
        if len(password) > 256 or len(salt) != 32 or len(expected) != 128:
            return False
        digest = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt),
                                n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P,
                                dklen=64, maxmem=64 * 1024 * 1024)
        return hmac.compare_digest(digest.hex(), expected)
    except (ValueError, UnicodeError):
        return False


def _name(value: str) -> tuple[str, str]:
    value = unicodedata.normalize("NFKC", value).strip()
    if not 1 <= len(value) <= 40 or any(
            unicodedata.category(c).startswith("C") or c in "\u2028\u2029" for c in value):
        raise HTTPException(400, "Choose a name of 1 to 40 visible characters.")
    return value, value.casefold()


def _new_password(value: str) -> str:
    try:
        valid = PASSWORD_MIN_LENGTH <= len(value) <= 256 and len(value.encode("utf-8")) <= 1024
    except UnicodeError:
        valid = False
    if not valid:
        raise HTTPException(400, "Use a password of 10 to 256 characters.")
    return value


def _email(value: str | None) -> str | None:
    value = (value or "").strip()
    if not value:
        return None
    if len(value) > 254 or not re.fullmatch(r"[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+", value):
        raise HTTPException(400, "Enter a valid email address.")
    if not value.isascii() or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise HTTPException(400, "Enter a valid email address.")
    return value


class Identity:
    """Identity persistence; ``email_sender(recipient, reset_url)`` is injectable.

    Session/reset bearer tokens are stored only as SHA-256 digests. Cookies last
    30 days; reset links last one hour. User notes are never model-editable.
    """

    def __init__(self, config: Config,
                 email_sender: Callable[[str, str], None] | None = None):
        self.config = config
        self._email_sender = email_sender
        self.config.data_dir.mkdir(parents=True, exist_ok=True)
        self._dummy_password_hash = _password_hash(secrets.token_urlsafe(32))
        with self._db() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS auth_users (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    name_key TEXT NOT NULL UNIQUE,
                    password_hash TEXT,
                    email TEXT,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS auth_sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
                    csrf_token TEXT NOT NULL,
                    expires_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS auth_sessions_user ON auth_sessions(user_id);
                CREATE TABLE IF NOT EXISTS auth_resets (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
                    expires_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS auth_resets_user ON auth_resets(user_id);
                CREATE TABLE IF NOT EXISTS auth_memory (
                    user_id TEXT PRIMARY KEY REFERENCES auth_users(id) ON DELETE CASCADE,
                    enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0, 1)),
                    text TEXT NOT NULL DEFAULT '',
                    updated_at REAL NOT NULL
                );
            """)

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.config.db_path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    @property
    def email_reset_available(self) -> bool:
        return self._email_sender is not None or bool(self.config.smtp_host and self.config.smtp_from)

    @staticmethod
    def _public(row) -> dict:
        return {"id": row["id"], "name": row["name"],
                "protected": bool(row["password_hash"]),
                "memory_enabled": bool(row["password_hash"] and row["memory_enabled"])}

    @staticmethod
    def _valid_token(token) -> bool:
        return isinstance(token, str) and 20 <= len(token) <= 128 and token.isascii()

    def _session(self, token: str | None):
        if not self._valid_token(token):
            return None
        with self._db() as db:
            return db.execute("""
                SELECT u.*, s.csrf_token, COALESCE(m.enabled, 0) AS memory_enabled
                FROM auth_sessions s JOIN auth_users u ON u.id=s.user_id
                LEFT JOIN auth_memory m ON m.user_id=u.id
                WHERE s.token_hash=? AND s.expires_at>?
            """, (_token_hash(token), time.time())).fetchone()

    def user_for_token(self, token: str | None) -> dict | None:
        row = self._session(token)
        return self._public(row) if row else None

    def csrf_valid(self, token: str | None, header: str | None) -> bool:
        if not isinstance(header, str) or not header.isascii() or len(header) > 128:
            return False
        row = self._session(token)
        return bool(row and hmac.compare_digest(row["csrf_token"], header))

    def state(self, token: str | None) -> dict:
        row = self._session(token)
        return {"user": self._public(row) if row else None,
                "csrf_token": row["csrf_token"] if row else None,
                "email_reset_available": self.email_reset_available}

    @staticmethod
    def _new_session(db, user_id: str) -> str:
        token = secrets.token_urlsafe(48)
        now = time.time()
        db.execute("DELETE FROM auth_sessions WHERE expires_at<=?", (now,))
        db.execute("DELETE FROM auth_resets WHERE expires_at<=?", (now,))
        db.execute("INSERT INTO auth_sessions VALUES (?, ?, ?, ?)",
                   (_token_hash(token), user_id, secrets.token_urlsafe(32), now + SESSION_SECONDS))
        return token

    def register(self, name: str, password: str | None = None, email: str | None = None) -> str:
        name, key = _name(name)
        email = _email(email)
        password = password or None
        if email and not password:
            raise HTTPException(400, "Set a password before adding a recovery email.")
        encoded = _password_hash(_new_password(password)) if password else None
        try:
            with self._db() as db:
                user_id = secrets.token_hex(16)
                db.execute("INSERT INTO auth_users VALUES (?, ?, ?, ?, ?, ?)",
                           (user_id, name, key, encoded, email, time.time()))
                token = self._new_session(db, user_id)
        except sqlite3.IntegrityError:
            raise HTTPException(409, "That name is already taken.") from None
        return token

    def login(self, name: str, password: str, old_token: str | None = None) -> str:
        _, key = _name(name)
        with self._db() as db:
            row = db.execute("SELECT * FROM auth_users WHERE name_key=?", (key,)).fetchone()
        encoded = row["password_hash"] if row and row["password_hash"] else self._dummy_password_hash
        valid = _password_matches(password, encoded)
        if not row or not row["password_hash"] or not valid:
            raise HTTPException(401, "The name or password is incorrect.")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT password_hash FROM auth_users WHERE id=?", (row["id"],)).fetchone()
            if not current or current["password_hash"] != encoded:
                raise HTTPException(401, "The name or password is incorrect.")
            if self._valid_token(old_token):
                db.execute("DELETE FROM auth_sessions WHERE token_hash=?", (_token_hash(old_token),))
            return self._new_session(db, row["id"])

    def logout(self, token: str | None):
        if self._valid_token(token):
            with self._db() as db:
                db.execute("DELETE FROM auth_sessions WHERE token_hash=?", (_token_hash(token),))

    def protect(self, user_id: str, password: str, email: str | None = None) -> str:
        email = _email(email)
        encoded = _password_hash(_new_password(password))
        with self._db() as db:
            changed = db.execute("UPDATE auth_users SET password_hash=?, email=? "
                                 "WHERE id=? AND password_hash IS NULL", (encoded, email, user_id))
            if changed.rowcount != 1:
                raise HTTPException(409, "This account already has a password.")
            db.execute("DELETE FROM auth_sessions WHERE user_id=?", (user_id,))
            return self._new_session(db, user_id)

    def forgot(self, name: str):
        # Uniform response for absent names, guests, missing email and SMTP errors.
        if not self.email_reset_available:
            return
        try:
            _, key = _name(name)
        except HTTPException:
            return
        token = secrets.token_urlsafe(32)
        hashed = _token_hash(token)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM auth_users WHERE name_key=?", (key,)).fetchone()
            if not row or not row["password_hash"] or not row["email"]:
                return
            # Only the latest reset link remains valid.
            db.execute("DELETE FROM auth_resets WHERE user_id=?", (row["id"],))
            db.execute("INSERT INTO auth_resets VALUES (?, ?, ?)",
                       (hashed, row["id"], time.time() + RESET_SECONDS))
        reset_url = self.config.origin + "/#reset=" + token
        try:
            if self._email_sender:
                self._email_sender(row["email"], reset_url)
            else:
                self._send_email(row["email"], reset_url)
        except Exception:
            # Do not print exceptions: mail transports may include message text.
            with self._db() as db:
                db.execute("DELETE FROM auth_resets WHERE token_hash=?", (hashed,))

    def _send_email(self, recipient: str, reset_url: str):
        message = EmailMessage()
        message["From"] = self.config.smtp_from
        message["To"] = recipient
        message["Subject"] = "Reset your Astra chess password"
        message.set_content("A password reset was requested for your Astra chess account.\n\n"
                            f"Choose a new password here within one hour:\n{reset_url}\n\n"
                            "If you did not request this, ignore this email. Your password has not changed.")
        context = ssl.create_default_context()
        if self.config.smtp_port == 465:
            transport = smtplib.SMTP_SSL(self.config.smtp_host, self.config.smtp_port,
                                         timeout=15, context=context)
        else:
            transport = smtplib.SMTP(self.config.smtp_host, self.config.smtp_port, timeout=15)
        with transport as smtp:
            if self.config.smtp_port != 465:
                smtp.ehlo()
                smtp.starttls(context=context)
                smtp.ehlo()
            if self.config.smtp_user:
                smtp.login(self.config.smtp_user, self.config.smtp_password)
            smtp.send_message(message)

    def reset(self, token: str, password: str):
        if not self._valid_token(token):
            raise HTTPException(400, "This reset link is invalid or expired.")
        password = _new_password(password)
        hashed = _token_hash(token)
        # Check before doing costly password work; recheck under lock afterwards.
        with self._db() as db:
            row = db.execute("SELECT user_id FROM auth_resets WHERE token_hash=? AND expires_at>?",
                             (hashed, time.time())).fetchone()
        if not row:
            raise HTTPException(400, "This reset link is invalid or expired.")
        encoded = _password_hash(password)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT user_id FROM auth_resets WHERE token_hash=? AND expires_at>?",
                             (hashed, time.time())).fetchone()
            if not row:
                raise HTTPException(400, "This reset link is invalid or expired.")
            user_id = row["user_id"]
            db.execute("UPDATE auth_users SET password_hash=? WHERE id=?", (encoded, user_id))
            db.execute("DELETE FROM auth_resets WHERE user_id=?", (user_id,))
            db.execute("DELETE FROM auth_sessions WHERE user_id=?", (user_id,))

    def get_memory(self, user_id: str) -> dict:
        with self._db() as db:
            row = db.execute("SELECT m.enabled, m.text, u.password_hash FROM auth_users u "
                             "LEFT JOIN auth_memory m ON m.user_id=u.id WHERE u.id=?", (user_id,)).fetchone()
        if not row or not row["password_hash"]:
            raise HTTPException(403, "Set a password before enabling player memories.")
        return {"enabled": bool(row["enabled"]), "text": row["text"] or ""}

    def put_memory(self, user_id: str, enabled: bool, text: str) -> dict:
        if len(text) > MEMORY_MAX_LENGTH or "\x00" in text:
            raise HTTPException(400, "Player memory must contain at most 4000 characters and no null characters.")
        with self._db() as db:
            row = db.execute("SELECT password_hash FROM auth_users WHERE id=?", (user_id,)).fetchone()
            if not row or not row["password_hash"]:
                raise HTTPException(403, "Set a password before enabling player memories.")
            db.execute("INSERT INTO auth_memory VALUES (?, ?, ?, ?) "
                       "ON CONFLICT(user_id) DO UPDATE SET enabled=excluded.enabled, "
                       "text=excluded.text, updated_at=excluded.updated_at",
                       (user_id, int(enabled), text, time.time()))
        return {"enabled": bool(enabled), "text": text}

    def memory_for_user(self, user_id: str) -> str:
        with self._db() as db:
            row = db.execute("SELECT m.text FROM auth_memory m JOIN auth_users u ON u.id=m.user_id "
                             "WHERE m.user_id=? AND m.enabled=1 AND u.password_hash IS NOT NULL",
                             (user_id,)).fetchone()
        return row["text"] if row else ""


def require_user(request: Request) -> dict:
    user = request.app.state.identity.user_for_token(request.cookies.get(COOKIE_NAME))
    if user is None:
        raise HTTPException(401, "Choose a player name or sign in to continue.")
    return user


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class RegisterInput(Input):
    name: str = Field(min_length=1, max_length=80)
    password: str | None = Field(default=None, max_length=256)
    email: str | None = Field(default=None, max_length=254)


class LoginInput(Input):
    name: str = Field(min_length=1, max_length=80)
    password: str = Field(max_length=256)


class ProtectInput(Input):
    password: str = Field(max_length=256)
    email: str | None = Field(default=None, max_length=254)


class ForgotInput(Input):
    name: str = Field(min_length=1, max_length=80)


class ResetInput(Input):
    token: str = Field(max_length=128)
    password: str = Field(max_length=256)


class MemoryInput(Input):
    enabled: bool
    text: str = Field(max_length=MEMORY_MAX_LENGTH)


router = APIRouter(prefix="/api/auth", tags=["identity"])


def _with_cookie(identity: Identity, response: Response, token: str) -> dict:
    response.set_cookie(COOKIE_NAME, token, max_age=SESSION_SECONDS, httponly=True,
                        secure=identity.config.secure_cookies, samesite="strict", path="/")
    response.headers["Cache-Control"] = "no-store"
    return identity.state(token)


@router.get("/me")
def me(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return request.app.state.identity.state(request.cookies.get(COOKIE_NAME))


@router.post("/register")
def register(body: RegisterInput, request: Request, response: Response):
    identity = request.app.state.identity
    if identity.user_for_token(request.cookies.get(COOKIE_NAME)):
        raise HTTPException(409, "Sign out before creating a different account.")
    return _with_cookie(identity, response, identity.register(body.name, body.password, body.email))


@router.post("/login")
def login(body: LoginInput, request: Request, response: Response):
    identity = request.app.state.identity
    token = identity.login(body.name, body.password, request.cookies.get(COOKIE_NAME))
    return _with_cookie(identity, response, token)


@router.post("/logout")
def logout(request: Request, response: Response):
    request.app.state.identity.logout(request.cookies.get(COOKIE_NAME))
    response.delete_cookie(COOKIE_NAME, httponly=True,
                           secure=request.app.state.identity.config.secure_cookies, samesite="strict", path="/")
    response.headers["Cache-Control"] = "no-store"
    return {"ok": True}


@router.post("/protect")
def protect(body: ProtectInput, request: Request, response: Response):
    identity = request.app.state.identity
    user = require_user(request)
    return _with_cookie(identity, response, identity.protect(user["id"], body.password, body.email))


@router.post("/forgot")
def forgot(body: ForgotInput, request: Request, background_tasks: BackgroundTasks):
    # Dispatch after the uniform response so SMTP timing cannot reveal accounts.
    background_tasks.add_task(request.app.state.identity.forgot, body.name)
    return {"ok": True, "message": "If this account has a recovery email, a reset link has been sent."}


@router.post("/reset")
def reset(body: ResetInput, request: Request):
    request.app.state.identity.reset(body.token, body.password)
    return {"ok": True}


@router.get("/memory")
def memory(request: Request, response: Response):
    user = require_user(request)
    response.headers["Cache-Control"] = "no-store"
    return request.app.state.identity.get_memory(user["id"])


@router.put("/memory")
def save_memory(body: MemoryInput, request: Request, response: Response):
    user = require_user(request)
    response.headers["Cache-Control"] = "no-store"
    return request.app.state.identity.put_memory(user["id"], body.enabled, body.text)
