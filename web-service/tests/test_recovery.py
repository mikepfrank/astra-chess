"""Recovery lifecycle, legacy migration, durable admission, and HTTP boundaries.

All delivery uses injected senders or mocked SMTP. No external mail is sent.
"""
import concurrent.futures
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.testclient import TestClient

from astra_web.config import Config
from astra_web.identity import COOKIE_NAME, Identity, _token_hash, router
from tests.test_identity import PASSWORD, NEW_PASSWORD


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.config = Config(data_dir=Path(self.directory.name), origin="http://testserver",
                             smtp_host="", smtp_from="", smtp_feedback_address="", secure_cookies=False)
        self.now = time.time()
        clock = patch("astra_web.identity.time", SimpleNamespace(time=lambda: self.now))
        clock.start()
        self.addCleanup(clock.stop)
        self.resets, self.verifications = [], []
        self.identity = self.new_identity()
        self.app = FastAPI()
        self.app.state.identity = self.identity
        self.app.include_router(router)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def new_identity(self):
        return Identity(self.config, email_sender=lambda email, url: self.resets.append((email, url)),
                        verification_sender=lambda email, url: self.verifications.append((email, url)))

    def query(self, sql, params=()):
        with self.identity._db() as db:
            return [tuple(row) for row in db.execute(sql, params)]

    def account(self, email=None, name="Mike"):
        self.session = self.identity.register(name, PASSWORD, email)
        self.user_id = self.identity.user_for_token(self.session)["id"]
        self.client.cookies.set(COOKIE_NAME, self.session)
        return self.user_id

    def verified(self):
        self.account("player@example.org")
        self.identity.verify_email(self.verify_token())
        self.now += 61

    def verify_token(self):
        return self.verifications[-1][1].split("#verify-email=")[1]

    def reset_token(self):
        return self.resets[-1][1].split("#reset=")[1]

    def fails(self, code, fn, *args):
        with self.assertRaises(HTTPException) as context:
            fn(*args)
        self.assertEqual(context.exception.status_code, code)

    def test_optional_email_requires_explicit_one_use_confirmation_and_stays_private(self):
        registered = self.client.post("/api/auth/register", json={
            "name": "Mike", "password": PASSWORD, "email": "player@example.org"})
        self.assertEqual(registered.status_code, 200)
        state = registered.json()
        self.assertFalse(state["recovery"]["verified"])
        self.assertEqual(state["recovery"]["pending_email"], "player@example.org")
        self.assertEqual(state["recovery"]["pending_expires_at"], self.now + 86400)
        self.assertNotIn("email", state["user"])
        self.assertNotIn("recovery", state["user"])
        token = self.verify_token()
        self.assertGreaterEqual(len(token), 43)
        self.assertEqual(self.query("SELECT token_hash FROM auth_email_verifications"), [(_token_hash(token),)])
        self.assertNotIn(token, registered.text)
        self.identity.forgot("Mike")
        self.assertEqual(self.resets, [])
        with TestClient(self.app) as anonymous:
            self.assertEqual(anonymous.get("/api/auth/verify-email?token=" + token).status_code, 405)
            self.assertFalse(self.client.get("/api/auth/recovery").json()["verified"])
            confirmed = anonymous.post("/api/auth/verify-email", json={"token": token})
            self.assertEqual(confirmed.status_code, 200)
            self.assertIsNone(anonymous.cookies.get(COOKIE_NAME))
            self.assertNotIn("recovery", anonymous.get("/api/auth/me").json())
            self.assertEqual(anonymous.post("/api/auth/verify-email", json={"token": token}).status_code, 400)
        recovery = self.client.get("/api/auth/me").json()["recovery"]
        self.assertTrue(recovery["verified"])
        self.assertIsNone(recovery["pending_email"])

    def test_existing_guest_upgrade_and_protected_owner_management(self):
        self.assertEqual(self.client.get("/api/auth/recovery").status_code, 401)
        guest = self.client.post("/api/auth/register", json={"name": "Mike"}).json()
        self.assertNotIn("recovery", guest)
        self.assertEqual(self.client.get("/api/auth/recovery").status_code, 403)
        upgraded = self.client.post("/api/auth/protect", json={"password": PASSWORD,
                                                              "email": "player@example.org"}).json()
        self.assertEqual(upgraded["user"]["id"], guest["user"]["id"])
        self.assertFalse(upgraded["recovery"]["verified"])
        self.assertEqual(len(self.verifications), 1)
        before = self.query("SELECT * FROM auth_email_verifications")
        self.assertEqual(self.client.post("/api/auth/recovery", json={"password": "wrong",
                                                                     "email": None}).status_code, 401)
        self.assertEqual(self.query("SELECT * FROM auth_email_verifications"), before)
        self.assertEqual(self.client.post("/api/auth/recovery", json={"password": PASSWORD,
                                                                     "email": None, "user_id": "other"}).status_code, 422)

    def test_confirmation_targets_token_account_without_changing_unrelated_signed_in_user(self):
        self.account("player@example.org")
        owner_id, owner_token = self.user_id, self.verify_token()
        other_session = self.identity.register("Other", PASSWORD, "other@example.org")
        other_id = self.identity.user_for_token(other_session)["id"]
        self.client.cookies.set(COOKIE_NAME, other_session)
        response = self.client.post("/api/auth/verify-email", json={"token": owner_token})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/api/auth/me").json()["user"]["id"], other_id)
        self.assertFalse(self.identity.get_recovery(other_id)["verified"])
        self.assertTrue(self.identity.get_recovery(owner_id)["verified"])

    def test_replacement_preserves_verified_address_until_confirmation_then_revokes_old_reset(self):
        self.verified()
        response = self.identity.manage_recovery(self.user_id, PASSWORD, "new@example.org")
        self.assertEqual(response["recovery"]["email"], "player@example.org")
        self.assertTrue(response["recovery"]["verified"])
        self.assertEqual(response["recovery"]["pending_email"], "new@example.org")
        new_token = self.verify_token()
        self.now += 61
        self.identity.forgot("Mike")
        old_reset = self.reset_token()
        self.assertEqual(self.resets[-1][0], "player@example.org")
        self.identity.verify_email(new_token)
        self.assertEqual(self.identity.get_recovery(self.user_id)["email"], "new@example.org")
        self.fails(400, self.identity.reset, old_reset, NEW_PASSWORD)
        self.now += 61
        self.identity.forgot("Mike")
        self.assertEqual(self.resets[-1][0], "new@example.org")

    def test_removal_revokes_pending_and_reset_but_preserves_rate_budget(self):
        self.verified()
        self.identity.forgot("Mike")
        old_reset = self.reset_token()
        self.now += 61
        self.identity.manage_recovery(self.user_id, PASSWORD, "new@example.org")
        pending = self.verify_token()
        response = self.identity.manage_recovery(self.user_id, PASSWORD, "")
        self.assertEqual(response["recovery"], {"available": True, "email": None, "verified": False,
                                                "pending_email": None, "pending_expires_at": None})
        self.fails(400, self.identity.verify_email, pending)
        self.fails(400, self.identity.reset, old_reset, NEW_PASSWORD)
        self.fails(429, self.identity.manage_recovery, self.user_id, PASSWORD, "third@example.org")
        self.assertEqual(len(self.query("SELECT * FROM auth_mail_events")), 3)
        self.assertIsNotNone(self.identity.user_for_token(self.session))

    def test_removal_works_when_mail_is_unavailable(self):
        self.verified()
        self.identity._email_sender = None
        self.identity._verification_sender = None
        removed = self.identity.manage_recovery(self.user_id, PASSWORD, None)
        self.assertFalse(removed["recovery"]["available"])
        self.assertIsNone(removed["recovery"]["email"])
        self.fails(503, self.identity.manage_recovery, self.user_id, PASSWORD, "new@example.org")

    def test_password_reset_invalidates_pending_change_and_preserves_owned_account_notes(self):
        self.verified()
        self.identity.put_memory(self.user_id, True, "My private notes")
        self.identity.forgot("Mike")
        reset = self.reset_token()
        self.now += 61
        self.identity.manage_recovery(self.user_id, PASSWORD, "new@example.org")
        pending = self.verify_token()
        self.identity.reset(reset, NEW_PASSWORD)
        self.fails(400, self.identity.verify_email, pending)
        self.fails(401, self.identity.manage_recovery, self.user_id, PASSWORD, None)
        renewed = self.identity.login("Mike", NEW_PASSWORD)
        self.assertEqual(self.identity.user_for_token(renewed)["id"], self.user_id)
        self.assertEqual(self.identity.memory_for_user(self.user_id), "My private notes")
        self.assertEqual(self.identity.get_recovery(self.user_id)["email"], "player@example.org")

    def test_throttled_resend_preserves_token_and_admitted_resend_supersedes_it(self):
        self.account("player@example.org")
        first = self.verify_token()
        before = self.query("SELECT * FROM auth_email_verifications")
        self.fails(429, self.identity.manage_recovery, self.user_id, PASSWORD, "player@example.org")
        self.assertEqual(self.query("SELECT * FROM auth_email_verifications"), before)
        self.now += 61
        self.identity.manage_recovery(self.user_id, PASSWORD, "player@example.org")
        second = self.verify_token()
        self.assertNotEqual(first, second)
        self.fails(400, self.identity.verify_email, first)
        self.now += 86401
        self.assertIsNone(self.identity.get_recovery(self.user_id)["pending_email"])
        self.fails(400, self.identity.verify_email, second)

    def test_shared_destination_and_user_limits_survive_new_instance(self):
        self.verified()
        self.identity.forgot("Mike")
        valid_reset = self.query("SELECT * FROM auth_resets")
        restarted = self.new_identity()
        restarted.forgot("Mike")
        self.assertEqual(self.query("SELECT * FROM auth_resets"), valid_reset)
        self.assertEqual(len(self.resets), 1)
        other = restarted.register("Other", PASSWORD)
        other_id = restarted.user_for_token(other)["id"]
        self.fails(429, restarted.manage_recovery, other_id, PASSWORD, "PLAYER@EXAMPLE.ORG")
        self.fails(429, restarted.manage_recovery, self.user_id, PASSWORD, "different@example.org")
        rows = self.query("SELECT destination_hash FROM auth_mail_events")
        self.assertTrue(all(len(row[0]) == 64 and "@" not in row[0] for row in rows))

    def test_hourly_daily_and_retention_limits_share_reset_and_verification_budget(self):
        self.verified()  # One verification reservation already exists.
        for _ in range(4):
            self.identity.forgot("Mike")
            self.now += 61
        self.identity.forgot("Mike")
        self.assertEqual(len(self.resets), 4)
        self.fails(429, self.identity.manage_recovery, self.user_id, PASSWORD, "new@example.org")
        for _ in range(3):
            self.now += 3601
            for _ in range(5):
                self.identity.forgot("Mike")
                self.now += 61
        self.assertEqual(len(self.resets), 19)
        self.now += 3601
        self.identity.forgot("Mike")
        self.assertEqual(len(self.resets), 19)
        self.assertEqual(len(self.query("SELECT * FROM auth_mail_events")), 20)
        self.now += 86401
        self.identity.forgot("Mike")
        self.assertEqual(len(self.resets), 20)
        self.assertEqual(len(self.query("SELECT * FROM auth_mail_events")), 1)

    def test_concurrent_instances_reserve_only_one_reset_and_confirmation_consumes_once(self):
        self.verified()
        second = self.new_identity()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda identity: identity.forgot("Mike"), [self.identity, second]))
        self.assertEqual(len(self.resets), 1)
        self.assertEqual(len(self.query("SELECT * FROM auth_resets")), 1)
        self.now += 61
        self.identity.manage_recovery(self.user_id, PASSWORD, "new@example.org")
        token = self.verify_token()
        def confirm(identity):
            try:
                identity.verify_email(token)
                return 200
            except HTTPException as error:
                return error.status_code
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(confirm, [self.identity, second]))
        self.assertEqual(sorted(statuses), [200, 400])

    def test_password_change_between_authentication_and_write_rejects_management(self):
        self.verified()
        def raced_password_check(password, encoded):
            self.query("UPDATE auth_users SET password_hash='changed' WHERE id=?", (self.user_id,))
            return True
        with patch("astra_web.identity._password_matches", side_effect=raced_password_check):
            self.fails(401, self.identity.manage_recovery, self.user_id, PASSWORD, None)
        self.assertEqual(self.identity.get_recovery(self.user_id)["email"], "player@example.org")

    def test_delivery_and_password_work_leave_database_writable_and_failures_consume_budget(self):
        self.account()
        def writable(*args):
            with self.identity._db() as db:
                db.execute("BEGIN IMMEDIATE")
            return True
        self.identity._verification_sender = writable
        with patch("astra_web.identity._password_matches", side_effect=writable):
            self.identity.manage_recovery(self.user_id, PASSWORD, "player@example.org")
        self.assertEqual(len(self.query("SELECT * FROM auth_email_verifications")), 1)
        self.now += 61
        def failed_sender(email, url):
            writable()
            raise RuntimeError("private provider response " + email + url)
        self.identity._verification_sender = failed_sender
        response = self.client.post("/api/auth/recovery", json={"password": PASSWORD, "email": "new@example.org"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("provider", response.text)
        self.assertNotIn("#verify-email=", response.text)
        self.assertEqual(self.query("SELECT * FROM auth_email_verifications"), [])
        self.fails(429, self.identity.manage_recovery, self.user_id, PASSWORD, "new@example.org")

    def test_delivery_is_queued_after_response_preparation(self):
        tasks = BackgroundTasks()
        session = self.identity.register("Mike", PASSWORD, "player@example.org", tasks)
        self.assertEqual(self.verifications, [])
        self.assertEqual(len(tasks.tasks), 1)
        self.assertEqual(self.identity.state(session)["recovery"]["pending_email"], "player@example.org")

    def test_legacy_email_and_reset_migrate_without_granting_recovery_or_changing_session(self):
        self.account()
        encoded = self.query("SELECT password_hash FROM auth_users")[0][0]
        legacy_dir = Path(self.directory.name) / "legacy"
        legacy_dir.mkdir()
        legacy_config = Config(data_dir=legacy_dir, origin="http://testserver", smtp_host="", smtp_from="")
        with closing(sqlite3.connect(legacy_config.db_path)) as db, db:
            db.executescript("""
                CREATE TABLE auth_users(id TEXT PRIMARY KEY,name TEXT NOT NULL,name_key TEXT UNIQUE,
                                        password_hash TEXT,email TEXT,created_at REAL NOT NULL);
                CREATE TABLE auth_resets(token_hash TEXT PRIMARY KEY,user_id TEXT,expires_at REAL);
                CREATE TABLE auth_sessions(token_hash TEXT PRIMARY KEY,user_id TEXT,csrf_token TEXT,expires_at REAL);
                CREATE TABLE saved_games(user_id TEXT,payload TEXT);
            """)
            db.execute("INSERT INTO auth_users VALUES ('owner','Mike','mike',?,'legacy@example.org',?)", (encoded, self.now))
            db.execute("INSERT INTO auth_resets VALUES (?, 'owner', ?)", (_token_hash("x" * 43), self.now + 3600))
            db.execute("INSERT INTO auth_sessions VALUES (?, 'owner', 'existing-csrf', ?)",
                       (_token_hash("s" * 43), self.now + 3600))
            db.execute("INSERT INTO saved_games VALUES ('owner','preserved game')")
        upgraded = Identity(legacy_config, email_sender=lambda *args: self.fail("Legacy email must not receive resets"),
                            verification_sender=lambda *args: None)
        upgraded.forgot("Mike")
        self.assertEqual(upgraded.user_for_token("s" * 43)["id"], "owner")
        self.assertTrue(upgraded.csrf_valid("s" * 43, "existing-csrf"))
        state = upgraded.get_recovery("owner")
        self.assertEqual(state["email"], "legacy@example.org")
        self.assertFalse(state["verified"])
        self.fails(400, upgraded.reset, "x" * 43, NEW_PASSWORD)
        session = upgraded.login("Mike", PASSWORD)
        self.assertEqual(upgraded.user_for_token(session)["id"], "owner")
        with upgraded._db() as db:
            self.assertEqual(db.execute("SELECT payload FROM saved_games").fetchone()[0], "preserved game")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM auth_resets").fetchone()[0], 0)

    def test_real_boundary_requires_csrf_for_management_but_only_origin_for_confirmation(self):
        from astra_web.app import create_app
        app = create_app(self.config)
        app.state.identity._email_sender = lambda email, url: self.resets.append((email, url))
        app.state.identity._verification_sender = lambda email, url: self.verifications.append((email, url))
        with TestClient(app) as client:
            registered = client.post("/api/auth/register", json={"name": "Mike", "password": PASSWORD},
                                     headers={"Origin": self.config.origin}).json()
            body = {"password": PASSWORD, "email": "player@example.org"}
            self.assertEqual(client.post("/api/auth/recovery", json=body,
                                         headers={"Origin": self.config.origin}).status_code, 403)
            headers = {"Origin": self.config.origin, "X-CSRF-Token": registered["csrf_token"]}
            requested = client.post("/api/auth/recovery", json=body, headers=headers)
            self.assertEqual(requested.status_code, 200)
            self.assertEqual(requested.headers["cache-control"], "no-store")
            token = self.verify_token()
            client.cookies.clear()
            for origin in (None, "https://evil.invalid"):
                self.assertEqual(client.post("/api/auth/verify-email", json={"token": token},
                                             headers={} if origin is None else {"Origin": origin}).status_code, 403)
            done = client.post("/api/auth/verify-email", json={"token": token}, headers={"Origin": self.config.origin})
            self.assertEqual(done.status_code, 200)
            self.assertIsNone(client.cookies.get(COOKIE_NAME))
            self.assertEqual(client.get("/api/auth/recovery").status_code, 401)

    def test_mail_transport_has_safe_metadata_player_name_feedback_and_tls(self):
        self.config.smtp_host = "smtp.example.org"
        self.config.smtp_from = "Astra Chess <noreply@example.org>"
        self.config.smtp_feedback_address = "feedback@example.org"
        self.config.smtp_user = "sender"
        self.config.smtp_password = "test-only-password"
        self.config.validate()
        for verification in (False, True):
            transport = MagicMock()
            smtp = transport.__enter__.return_value
            with patch("astra_web.identity.smtplib.SMTP", return_value=transport):
                self.identity._send_email("player@example.org", "https://example.org/#token=secret",
                                          verification=verification, name="Mike <board> 🐈")
            message = smtp.send_message.call_args.args[0]
            self.assertEqual(message["Return-Path"], "feedback@example.org")
            self.assertEqual(message["From"], self.config.smtp_from)
            self.assertIn("Player account: Mike <board> 🐈", message.get_content())
            self.assertTrue(message["Date"])
            self.assertRegex(message["Message-ID"], r"^<[a-f0-9]{32}@testserver>$")
            self.assertNotIn("Mike", str(message["Subject"]))
            methods = [call[0] for call in smtp.method_calls]
            self.assertLess(methods.index("starttls"), methods.index("login"))
            self.assertLess(methods.index("starttls"), methods.index("send_message"))
        transport = MagicMock()
        smtp = transport.__enter__.return_value
        smtp.starttls.side_effect = RuntimeError("TLS unavailable")
        with patch("astra_web.identity.smtplib.SMTP", return_value=transport):
            with self.assertRaises(RuntimeError):
                self.identity._send_email("player@example.org", "https://example.org/#reset=secret")
        smtp.login.assert_not_called()
        smtp.send_message.assert_not_called()

    def test_feedback_address_rejects_header_injection_and_multiple_or_malformed_mailboxes(self):
        for value in ("a@example.org\r\nBcc:b@example.org", "a@example.org,b@example.org", "Name <a@example.org>",
                      "a@example.org\n", " a@example.org", "a@localhost", "a@@example.org", "☃@example.org",
                      "a(comment)@example.org", ".a@example.org", "a..b@example.org", "a.@example.org"):
            with self.subTest(value=value):
                self.config.smtp_feedback_address = value
                with self.assertRaisesRegex(ValueError, "single bare email address"):
                    self.config.validate()
        self.config.smtp_feedback_address = "feedback+astra@example.org"
        self.config.validate()


if __name__ == "__main__":
    unittest.main()
