import concurrent.futures
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from astra_web.config import Config
from astra_web.identity import COOKIE_NAME, Identity, router


PASSWORD = "a long test password"
NEW_PASSWORD = "another long password"


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.mail = []
        self.verification_mail = []
        self.config = Config(data_dir=Path(self.directory.name), origin="http://testserver",
                             smtp_host="", smtp_from="", secure_cookies=False)
        self.identity = Identity(self.config, email_sender=lambda email, url: self.mail.append((email, url)),
                                 verification_sender=lambda email, url: self.verification_mail.append((email, url)))
        self.app = FastAPI()
        self.app.state.identity = self.identity
        self.app.include_router(router)
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.directory.cleanup()

    def query(self, sql, args=()):
        db = sqlite3.connect(self.config.db_path)
        try:
            with db:
                return db.execute(sql, args).fetchall()
        finally:
            db.close()

    def register(self, name="Mike", protected=False, email=None, client=None):
        body = {"name": name}
        if protected:
            body["password"] = PASSWORD
        if email:
            body["email"] = email
        response = (client or self.client).post("/api/auth/register", json=body)
        self.assertEqual(response.status_code, 200, response.text)
        return response

    def cool_mail(self):
        self.query("UPDATE auth_mail_events SET created_at=created_at-61")

    def register_verified(self):
        response = self.register(protected=True, email="player@example.org")
        self.identity.verify_email(self.verification_mail[-1][1].split("#verify-email=")[1])
        self.cool_mail()
        return response

    def test_guest_browser_persistence_unique_name_and_no_name_login(self):
        self.assertIsNone(self.client.get("/api/auth/me").json()["user"])
        response = self.register()
        state = response.json()
        self.assertEqual(set(state["user"]), {"id", "name", "protected", "memory_enabled"})
        self.assertFalse(state["user"]["protected"])
        self.assertEqual(self.client.get("/api/auth/me").json(), state)
        self.assertIn("HttpOnly", response.headers["set-cookie"])
        self.assertIn("SameSite=strict", response.headers["set-cookie"])
        with TestClient(self.app) as other:
            duplicate = other.post("/api/auth/register", json={"name": "ＭＩＫＥ"})
            self.assertEqual(duplicate.status_code, 409)
            guessed = other.post("/api/auth/login", json={"name": "Mike", "password": PASSWORD})
            self.assertEqual(guessed.status_code, 401)
            self.assertIsNone(other.get("/api/auth/me").json()["user"])

    def test_hashes_cookies_rotation_logout_and_expiry(self):
        self.register(protected=True)
        token = self.client.cookies.get(COOKIE_NAME)
        state = self.client.get("/api/auth/me").json()
        self.assertTrue(self.identity.csrf_valid(token, state["csrf_token"]))
        self.assertFalse(self.identity.csrf_valid(token, "wrong"))
        self.assertFalse(self.identity.csrf_valid(token, "\u2603"))
        self.assertFalse(self.identity.csrf_valid(None, state["csrf_token"]))
        stored_password = self.query("SELECT password_hash FROM auth_users")[0][0]
        self.assertTrue(stored_password.startswith("scrypt$32768$8$3$"))
        self.assertNotIn(PASSWORD, stored_password)
        self.assertNotEqual(self.query("SELECT token_hash FROM auth_sessions")[0][0], token)
        login = self.client.post("/api/auth/login", json={"name": "MIKE", "password": PASSWORD})
        self.assertEqual(login.status_code, 200)
        self.assertIsNone(self.identity.user_for_token(token))
        second_token = self.client.cookies.get(COOKIE_NAME)
        self.assertNotEqual(second_token, token)
        self.assertNotEqual(login.json()["csrf_token"], state["csrf_token"])
        self.client.post("/api/auth/logout")
        self.assertIsNone(self.identity.user_for_token(second_token))
        self.assertIsNone(self.client.cookies.get(COOKIE_NAME))
        self.client.post("/api/auth/login", json={"name": "Mike", "password": PASSWORD})
        expired = self.client.cookies.get(COOKIE_NAME)
        self.query("UPDATE auth_sessions SET expires_at=?", (time.time() - 1,))
        self.assertIsNone(self.identity.user_for_token(expired))
        self.assertFalse(self.identity.csrf_valid(expired, login.json()["csrf_token"]))

    def test_account_memory_is_opt_in_protected_and_private(self):
        self.assertEqual(self.client.get("/api/auth/memory").status_code, 401)
        user = self.register().json()["user"]
        self.assertEqual(self.client.get("/api/auth/memory").status_code, 403)
        self.assertEqual(self.client.put("/api/auth/memory", json={"enabled": True, "text": "notes"}).status_code, 403)
        old_cookie = self.client.cookies.get(COOKIE_NAME)
        upgrade = self.client.post("/api/auth/protect", json={"password": PASSWORD})
        self.assertEqual(upgrade.status_code, 200)
        self.assertTrue(upgrade.json()["user"]["protected"])
        self.assertEqual(upgrade.json()["user"]["id"], user["id"])
        self.assertIsNone(self.identity.user_for_token(old_cookie))
        self.assertEqual(self.identity.memory_for_user(user["id"]), "")
        self.assertEqual(self.client.get("/api/auth/memory").json(), {"enabled": False, "text": ""})
        notes = "I like explanatory games.\nI usually play during lunch."
        self.assertEqual(self.client.put("/api/auth/memory", json={"enabled": True, "text": notes}).status_code, 200)
        self.assertEqual(self.identity.memory_for_user(user["id"]), notes)
        self.assertTrue(self.client.get("/api/auth/me").json()["user"]["memory_enabled"])
        with TestClient(self.app) as other:
            other_user = self.register("Other", protected=True, client=other).json()["user"]
            self.assertEqual(other.get("/api/auth/memory").json()["text"], "")
            self.assertEqual(self.identity.memory_for_user(other_user["id"]), "")
            self.assertEqual(other.put("/api/auth/memory", json={"enabled": True, "text": "hack", "user_id": user["id"]}).status_code, 422)
        self.client.put("/api/auth/memory", json={"enabled": False, "text": notes})
        self.assertEqual(self.identity.memory_for_user(user["id"]), "")
        self.assertEqual(self.client.get("/api/auth/memory").json()["text"], notes)
        self.assertEqual(self.client.put("/api/auth/memory", json={"enabled": True, "text": "x" * 4001}).status_code, 422)

    def test_reset_is_single_use_hashed_and_revokes_every_session(self):
        self.register_verified()
        original = self.client.cookies.get(COOKIE_NAME)
        second = self.identity.login("Mike", PASSWORD)
        forgot = self.client.post("/api/auth/forgot", json={"name": "Mike"})
        absent = self.client.post("/api/auth/forgot", json={"name": "Nobody"})
        self.assertEqual(forgot.json(), absent.json())
        self.assertEqual(len(self.mail), 1)
        recipient, url = self.mail[0]
        self.assertEqual(recipient, "player@example.org")
        self.assertEqual(urlsplit(url).path, "/")
        self.assertEqual(urlsplit(url).query, "")
        token = urlsplit(url).fragment.removeprefix("reset=")
        self.assertNotIn(token, forgot.text)
        self.assertNotEqual(self.query("SELECT token_hash FROM auth_resets")[0][0], token)
        done = self.client.post("/api/auth/reset", json={"token": token, "password": NEW_PASSWORD})
        self.assertEqual(done.status_code, 200)
        self.assertEqual(self.query("SELECT * FROM auth_resets"), [])
        self.assertIsNone(self.identity.user_for_token(original))
        self.assertIsNone(self.identity.user_for_token(second))
        self.assertEqual(self.client.post("/api/auth/reset", json={"token": token, "password": PASSWORD}).status_code, 400)
        self.assertEqual(self.client.post("/api/auth/login", json={"name": "Mike", "password": PASSWORD}).status_code, 401)
        self.assertEqual(self.client.post("/api/auth/login", json={"name": "Mike", "password": NEW_PASSWORD}).status_code, 200)

    def test_new_reset_supersedes_old_and_expired_links_fail(self):
        self.register_verified()
        self.identity.forgot("Mike")
        old = self.mail[-1][1].split("#reset=")[1]
        self.cool_mail()
        self.identity.forgot("Mike")
        new = self.mail[-1][1].split("#reset=")[1]
        self.assertEqual(len(self.query("SELECT * FROM auth_resets")), 1)
        for token in (old, new):
            if token == new:
                self.query("UPDATE auth_resets SET expires_at=?", (time.time() - 1,))
            with self.assertRaises(HTTPException) as context:
                self.identity.reset(token, NEW_PASSWORD)
            self.assertEqual(context.exception.status_code, 400)

    def test_simultaneous_reset_consumes_once(self):
        self.register_verified()
        self.identity.forgot("Mike")
        token = self.mail[-1][1].split("#reset=")[1]

        def reset_once():
            try:
                self.identity.reset(token, NEW_PASSWORD)
                return 200
            except HTTPException as error:
                return error.status_code

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: reset_once(), range(2)))
        self.assertEqual(sorted(results), [200, 400])

    def test_email_failure_does_not_leak_token_or_leave_reset(self):
        self.register_verified()

        def failed_sender(recipient, reset_url):
            raise RuntimeError(reset_url)

        self.identity._email_sender = failed_sender
        response = self.client.post("/api/auth/forgot", json={"name": "Mike"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("#reset=", response.text)
        self.assertEqual(self.query("SELECT * FROM auth_resets"), [])

    def test_unconfigured_email_does_not_claim_capability(self):
        self.identity._email_sender = None
        self.identity._verification_sender = None
        self.assertFalse(self.client.get("/api/auth/me").json()["email_reset_available"])
        self.register(protected=True, email="player@example.org")
        self.assertEqual(self.client.post("/api/auth/forgot", json={"name": "Mike"}).status_code, 200)
        self.assertEqual(self.query("SELECT * FROM auth_resets"), [])

    def test_reset_transport_requires_tls(self):
        self.config.smtp_host = "smtp.example.org"
        self.config.smtp_from = "astra@example.org"
        self.config.smtp_user = "sender"
        self.config.smtp_password = "smtp password"
        transport = MagicMock()
        smtp = transport.__enter__.return_value
        with patch("astra_web.identity.smtplib.SMTP", return_value=transport) as factory:
            self.identity._send_email("player@example.org", "https://example.org/#reset=secret")
        factory.assert_called_once_with("smtp.example.org", 587, timeout=15)
        smtp.starttls.assert_called_once()
        smtp.login.assert_called_once_with("sender", "smtp password")
        smtp.send_message.assert_called_once()
        methods = [call[0] for call in smtp.method_calls]
        self.assertLess(methods.index("starttls"), methods.index("login"))
        self.assertLess(methods.index("starttls"), methods.index("send_message"))
        self.config.smtp_port = 465
        with patch("astra_web.identity.smtplib.SMTP_SSL", return_value=transport) as secure_factory:
            self.identity._send_email("player@example.org", "https://example.org/#reset=secret")
        secure_factory.assert_called_once()

    def test_validation_and_secure_cookie(self):
        self.assertEqual(self.client.post("/api/auth/register", json={"name": "Bad\nName"}).status_code, 400)
        self.assertEqual(self.client.post("/api/auth/register", json={"name": "Mike", "password": "short"}).status_code, 400)
        self.assertEqual(self.client.post("/api/auth/register", json={"name": "Mike", "email": "player@example.org"}).status_code, 400)
        self.assertEqual(self.client.post("/api/auth/register", json={"name": "Mike", "password": PASSWORD, "email": "bad\nheader@example.org"}).status_code, 400)
        self.assertEqual(self.client.post("/api/auth/register", json={"name": "Mike", "protected": True}).status_code, 422)
        self.config.secure_cookies = True
        response = self.register(protected=True)
        self.assertIn("Secure", response.headers["set-cookie"])
        self.assertNotIn(PASSWORD, response.text)


if __name__ == "__main__":
    unittest.main()
