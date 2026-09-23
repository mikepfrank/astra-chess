"""Isolated credential and budget checks; no real network or model requests."""
import contextlib
from concurrent.futures import ThreadPoolExecutor
import getpass
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx

import configure_openrouter as cli
from astra_web import openrouter_setup as setup


KEY = "sk-or-v1-placeholder-for-tests-only"
OTHER_KEY = "sk-or-v1-different-placeholder-for-tests-only"


class OpenRouterSetupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.ledger = self.root / "var" / "openrouter-budget.json"
        self.month_patch = patch.object(setup, "_utc_month", return_value="2026-09")
        self.month = self.month_patch.start()
        self.addCleanup(self.month_patch.stop)

    @staticmethod
    def body(**overrides):
        return {"data": {"limit": 100, "limit_reset": None, "limit_remaining": 99.5,
                         "usage": 0.5, "byok_usage": 0, "include_byok_in_limit": True,
                         "usage_monthly": 0, "byok_usage_monthly": 0,
                         "label": KEY, "untrusted_extra": KEY, **overrides}}

    def transport(self, status=200, body=None):
        return httpx.MockTransport(lambda request: httpx.Response(
            status, content=json.dumps(self.body() if body is None else body).encode()))

    def require(self, body=None, key=KEY, **kwargs):
        return setup.require_budget(key, self.ledger, transport=self.transport(body=body), **kwargs)

    def test_service_budget_path_uses_private_writable_state(self):
        with patch.dict(os.environ, {'ASTRA_OPENROUTER_BUDGET_PATH': str(self.ledger)}):
            result = setup.require_budget(KEY, transport=self.transport())
        self.assertTrue(self.ledger.is_file())
        self.assertEqual(result['spent_usd'], 0)

    def assert_error(self, code, callback, *args, **kwargs):
        with self.assertRaises(setup.OpenRouterSetupError) as raised:
            callback(*args, **kwargs)
        self.assertEqual(raised.exception.code, code)
        self.assertNotIn(KEY, str(raised.exception))
        self.assertNotIn(OTHER_KEY, str(raised.exception))

    def write_config(self, **overrides):
        path = self.root / "var" / "openrouter-config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"version": 1, "profile": setup.PROFILE,
            "player": "codex", "codex_bin": "reviewed-codex.exe", **overrides}), encoding="utf-8")
        return path

    def write_legacy_ledger(self, **overrides):
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        value = {"version": 2, "key_sha256": hashlib.sha256(KEY.encode()).hexdigest(),
                 "budget_usd": "50", "initial_usage_usd": "100", "initial_byok_usage_usd": "20",
                 "usage_usd": "110", "byok_usage_usd": "22", "remaining_usd": "38", **overrides}
        self.ledger.write_text(json.dumps(value), encoding="utf-8")
        return value

    def test_fixed_endpoint_no_redirect_proxy_or_credentials_in_result(self):
        requests = []

        def handle(request):
            requests.append(request)
            self.assertEqual(str(request.url), setup.KEY_URL)
            self.assertEqual(request.method, "GET")
            self.assertEqual(request.headers["Authorization"], "Bearer " + KEY)
            return httpx.Response(200, json=self.body())

        original = httpx.Client
        with patch.object(setup.httpx, "Client", wraps=original) as factory:
            result = setup.require_budget(KEY, self.ledger, transport=httpx.MockTransport(handle))
        self.assertEqual(result["limit_usd"], 100)
        self.assertEqual(result["remaining_usd"], 99.5)
        self.assertEqual(result["spent_usd"], 0)
        self.assertEqual(result["budget_enforcement"], "local-utc-calendar-month")
        self.assertEqual(result["stop_remaining_usd"], 0)
        self.assertEqual(result["month"], "2026-09")
        self.assertEqual(result["timezone"], "UTC")
        self.assertEqual(len(requests), 1)
        self.assertFalse(factory.call_args.kwargs["follow_redirects"])
        self.assertFalse(factory.call_args.kwargs["trust_env"])
        self.assertEqual(factory.call_args.kwargs["timeout"], 25)
        self.assertNotIn(KEY, json.dumps(result))
        self.assertNotIn("key_sha256", result)
        saved = json.loads(self.ledger.read_text())
        self.assertEqual(len(saved["key_sha256"]), 64)
        self.assertNotIn(KEY, self.ledger.read_text())

    def test_invalid_keys_do_not_send_requests_or_create_ledger(self):
        def reject(request):
            self.fail("Invalid keys must not leave the process")
        for key in (None, "", "short", "bad\nheader-value", "x" * 4097):
            self.assert_error("invalid_key", setup.require_budget, key, self.ledger,
                              transport=httpx.MockTransport(reject))
        self.assertFalse(self.ledger.exists())

    def test_budget_metadata_fails_closed(self):
        overrides = [
            {"limit": -1}, {"limit": True}, {"limit": float("inf")},
            {"usage": -1}, {"usage": True}, {"usage": "0.5"}, {"usage": float("nan")},
            {"usage": float("inf")}, {"byok_usage": -0.1},
            {"limit_remaining": True}, {"limit_remaining": 101},
            {"limit_remaining": -0.1}, {"limit_remaining": float("inf")},
            {"usage_monthly": -1}, {"usage_monthly": True}, {"usage_monthly": "0"},
            {"usage_monthly": float("nan")}, {"usage_monthly": float("inf")},
            {"usage_monthly": 1}, {"byok_usage_monthly": 1},
            {"byok_usage_monthly": None}, {"byok_usage_monthly": -1},
        ]
        for override in overrides:
            with self.subTest(override=override):
                self.assert_error("budget_invalid", self.require, self.body(**override))
                self.assertFalse(self.ledger.exists())
        for missing in ("usage", "byok_usage", "usage_monthly", "byok_usage_monthly"):
            body = self.body()
            del body["data"][missing]
            self.assert_error("budget_invalid", self.require, body)

    def test_shared_uncapped_key_uses_both_usage_deltas_from_first_baseline(self):
        initial = self.require(self.body(limit=None, limit_remaining=None, usage=900,
                                         byok_usage=200, include_byok_in_limit=False))
        self.assertEqual(initial["remaining_usd"], 100)
        self.assertEqual(initial["spent_usd"], 0)
        self.assertIsNone(initial["provider_limit_usd"])
        updated = self.require(self.body(limit=None, limit_remaining=None, usage=902.5,
                                         byok_usage=203, include_byok_in_limit=False))
        self.assertEqual(updated["spent_usd"], 5.5)
        self.assertEqual(updated["remaining_usd"], 94.5)
        self.assertEqual(updated["budget_enforcement"], "local-utc-calendar-month")
        self.assertNotIn("usage_usd", updated)  # Do not publish the key's prior usage.
        self.assertEqual(json.loads(self.ledger.read_text())["initial_usage_usd"], "900")

    def test_optional_provider_limits_only_reduce_local_remaining(self):
        result = self.require(self.body(limit=12, limit_remaining=11.5, byok_usage=1))
        self.assertEqual(result["remaining_usd"], 11.5)
        result = self.require(self.body(limit=1000, limit_remaining=999, usage=3, byok_usage=2))
        self.assertEqual(result["remaining_usd"], 96.5)
        self.assertEqual(result["provider_limit_usd"], 1000)
        self.assertEqual(result["provider_remaining_usd"], 999)

    def test_absent_optional_provider_cap_metadata_is_accepted(self):
        result = self.require({"data": {"usage": 100, "byok_usage": 20,
                                        "usage_monthly": 10, "byok_usage_monthly": 2}})
        self.assertEqual(result["remaining_usd"], 100)
        self.assertIsNone(result["provider_remaining_usd"])

    def test_provider_daily_reset_does_not_reset_local_month_budget(self):
        self.require(self.body(limit=200, limit_remaining=200, usage=500, byok_usage=5,
                               limit_reset="daily", include_byok_in_limit=False))
        result = self.require(self.body(limit=200, limit_remaining=200, usage=510,
                                        byok_usage=10, limit_reset="daily"))
        self.assertEqual(result["remaining_usd"], 85)
        self.assertEqual(result["spent_usd"], 15)
        # Even if other provider metadata resets, cumulative usage must not.
        self.assert_error("budget_changed", self.require,
            self.body(limit=200, limit_remaining=200, usage=0, byok_usage=0, limit_reset="daily"))

    def test_full_local_allowance_and_overspend_stop_shared_uncapped_key(self):
        self.require(self.body(limit=None, limit_remaining=None, usage=500, byok_usage=20))
        result = self.require(self.body(limit=None, limit_remaining=None, usage=594, byok_usage=25))
        self.assertEqual(result["remaining_usd"], 1)
        self.assert_error("budget_low", self.require,
            self.body(limit=None, limit_remaining=None, usage=595, byok_usage=25))
        self.assert_error("budget_low", self.require,
            self.body(limit=None, limit_remaining=None, usage=595.5, byok_usage=26))
        saved = json.loads(self.ledger.read_text())
        self.assertEqual(saved["initial_usage_usd"], "500")
        self.assertEqual(saved["usage_usd"], "595.5")
        self.assertEqual(saved["remaining_usd"], "0")

    def test_five_dollar_reserve_removed_but_provider_exhaustion_preserves_evidence(self):
        self.require()
        self.assertEqual(self.require(self.body(usage=45, limit_remaining=5))["remaining_usd"], 5)
        self.assertEqual(json.loads(self.ledger.read_text())["usage_usd"], "45")
        self.assert_error("budget_low", self.require, self.body(usage=50.25, limit_remaining=0))
        self.assertEqual(json.loads(self.ledger.read_text())["usage_usd"], "50.25")

    def test_new_key_cannot_reset_budget_or_be_sent_to_provider(self):
        self.require()
        before = self.ledger.read_bytes()
        self.assert_error("budget_changed", setup.require_budget, OTHER_KEY, self.ledger,
            transport=httpx.MockTransport(lambda request: self.fail("Replacement key must not be used")))
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_usage_cannot_decrease_and_initial_usage_is_retained(self):
        self.require(self.body(usage=2, byok_usage=0.1, limit_remaining=47.9))
        self.require(self.body(usage=3, byok_usage=0.2, limit_remaining=46.8))
        before = self.ledger.read_bytes()
        for override in ({"usage": 2.9, "byok_usage": 0.2}, {"usage": 3, "byok_usage": 0.1}):
            self.assert_error("budget_changed", self.require, self.body(limit_remaining=46.8, **override))
            self.assertEqual(self.ledger.read_bytes(), before)
        saved = json.loads(before)
        self.assertEqual(saved["initial_usage_usd"], "2")
        self.assertEqual(saved["initial_byok_usage_usd"], "0.1")
        self.assertEqual(saved["version"], 3)
        self.assertEqual(saved["budget_usd"], "100")

    def test_exact_decimal_boundaries(self):
        self.require(self.body(limit=None, limit_remaining=None, usage=0))
        raw = b'{"data":{"limit":null,"limit_remaining":null,"usage":99.999999999999999,"byok_usage":0,"usage_monthly":99.999999999999999,"byok_usage_monthly":0}}'
        result = setup.require_budget(KEY, self.ledger,
            transport=httpx.MockTransport(lambda request: httpx.Response(200, content=raw)))
        self.assertGreater(result["remaining_usd"], 0)
        self.assertEqual(json.loads(self.ledger.read_text())["remaining_usd"], "1E-15")
        self.assert_error("budget_low", self.require, self.body(limit=None, limit_remaining=None,
            usage=100, usage_monthly=100))

    def test_legacy_migration_carries_all_experiment_spend_into_current_month(self):
        original = self.write_legacy_ledger(usage_usd="155", byok_usage_usd="24", remaining_usd="0")
        result = self.require(self.body(limit=None, limit_remaining=None,
            usage=160, byok_usage=25, usage_monthly=7, byok_usage_monthly=1))
        self.assertEqual(result["spent_usd"], 65)
        self.assertEqual(result["remaining_usd"], 35)
        saved = json.loads(self.ledger.read_text())
        self.assertEqual(saved["version"], 3)
        self.assertEqual(saved["month"], "2026-09")
        self.assertEqual(saved["migration_month"], "2026-09")
        for key in ("key_sha256", "initial_usage_usd", "initial_byok_usage_usd"):
            self.assertEqual(saved[key], original[key])
        # The migration is one-time; later checks this month retain the old baseline.
        result = self.require(self.body(limit=None, limit_remaining=None,
            usage=162, byok_usage=26, usage_monthly=9, byok_usage_monthly=2))
        self.assertEqual(result["spent_usd"], 68)

    def test_legacy_migration_over_new_cap_saves_accounting_then_refuses(self):
        self.write_legacy_ledger()
        self.assert_error("budget_low", self.require,
            self.body(limit=None, limit_remaining=None, usage=200, byok_usage=23))
        saved = json.loads(self.ledger.read_text())
        self.assertEqual(saved["version"], 3)
        self.assertEqual(saved["spent_usd"], "103")
        self.assertEqual(saved["remaining_usd"], "0")

    def test_new_month_restores_allowance_and_charges_usage_before_first_check(self):
        self.require(self.body(limit=None, limit_remaining=None, usage=100, byok_usage=20))
        self.assert_error("budget_low", self.require,
            self.body(limit=None, limit_remaining=None, usage=195, byok_usage=25))
        self.month.return_value = "2026-10"
        result = self.require(self.body(limit=None, limit_remaining=None,
            usage=205, byok_usage=28, usage_monthly=10, byok_usage_monthly=3))
        self.assertEqual(result["month"], "2026-10")
        self.assertEqual(result["spent_usd"], 13)
        self.assertEqual(result["remaining_usd"], 87)
        saved = json.loads(self.ledger.read_text())
        self.assertEqual(saved["migration_month"], "2026-09")
        self.assertEqual(saved["initial_usage_usd"], "100")
        # Advancing another day does not make a second baseline or another refund.
        result = self.require(self.body(limit=None, limit_remaining=None,
            usage=208, byok_usage=30, usage_monthly=13, byok_usage_monthly=5))
        self.assertEqual(result["spent_usd"], 18)

    def test_skipped_months_and_year_rollover_use_only_current_provider_month(self):
        self.require(self.body(limit=None, limit_remaining=None, usage=100, byok_usage=20))
        for month, usage, byok, monthly, byok_monthly in (
                ("2026-12", 300, 40, 21, 4),
                ("2027-01", 330, 42, 2, 1),
                ("2027-03", 600, 80, 11, 3)):
            with self.subTest(month=month):
                self.month.return_value = month
                result = self.require(self.body(limit=None, limit_remaining=None, usage=usage,
                    byok_usage=byok, usage_monthly=monthly, byok_usage_monthly=byok_monthly))
                self.assertEqual(result["spent_usd"], monthly + byok_monthly)
                self.assertEqual(result["remaining_usd"], 100 - monthly - byok_monthly)
                self.assertEqual(json.loads(self.ledger.read_text())["migration_month"], "2026-09")

    def test_monthly_counter_regression_does_not_refund_current_month(self):
        self.require(self.body(limit=None, limit_remaining=None, usage=100, byok_usage=20))
        self.month.return_value = "2026-10"
        result = self.require(self.body(limit=None, limit_remaining=None,
            usage=120, byok_usage=25, usage_monthly=20, byok_usage_monthly=5))
        self.assertEqual(result["spent_usd"], 25)
        result = self.require(self.body(limit=None, limit_remaining=None,
            usage=121, byok_usage=26, usage_monthly=18, byok_usage_monthly=4))
        self.assertEqual(result["spent_usd"], 25)
        self.assertEqual(result["remaining_usd"], 75)
        result = self.require(self.body(limit=None, limit_remaining=None,
            usage=125, byok_usage=28, usage_monthly=25, byok_usage_monthly=8))
        self.assertEqual(result["spent_usd"], 33)

    def test_stale_rollover_counters_do_not_pin_previous_month_spend(self):
        self.require(self.body(limit=None, limit_remaining=None, usage=100, byok_usage=20))
        self.assert_error("budget_low", self.require,
            self.body(limit=None, limit_remaining=None, usage=190, byok_usage=30,
                      usage_monthly=90, byok_usage_monthly=10))
        before = self.ledger.read_bytes()
        self.month.return_value = "2026-10"
        # Each monthly component must fit the corresponding cumulative increase;
        # a stale provider value must not become October's permanent high-water mark.
        for monthly, byok_monthly in ((90, 1), (1, 10), (90, 10)):
            with self.subTest(monthly=monthly, byok_monthly=byok_monthly):
                self.assert_error("budget_invalid", self.require,
                    self.body(limit=None, limit_remaining=None, usage=191, byok_usage=31,
                              usage_monthly=monthly, byok_usage_monthly=byok_monthly))
                self.assertEqual(self.ledger.read_bytes(), before)
        result = self.require(self.body(limit=None, limit_remaining=None, usage=191, byok_usage=31,
            usage_monthly=1, byok_usage_monthly=1))
        self.assertEqual(result["spent_usd"], 2)
        self.assertEqual(result["remaining_usd"], 98)
        saved = json.loads(self.ledger.read_text())
        self.assertEqual(saved["month"], "2026-10")
        self.assertEqual(saved["spent_usd"], "2")

    def test_new_month_does_not_permit_credential_swap_or_cumulative_counter_reset(self):
        self.require(self.body(limit=None, limit_remaining=None, usage=100, byok_usage=20))
        self.month.return_value = "2026-10"
        before = self.ledger.read_bytes()
        self.assert_error("budget_changed", setup.require_budget, OTHER_KEY, self.ledger,
            transport=httpx.MockTransport(lambda request: self.fail("Replacement key must not send")))
        for usage, byok in ((99, 20), (100, 19)):
            self.assert_error("budget_changed", self.require,
                self.body(limit=None, limit_remaining=None, usage=usage, byok_usage=byok))
            self.assertEqual(self.ledger.read_bytes(), before)

    def test_clock_month_rollback_fails_before_fetch_without_changing_ledger(self):
        self.require()
        before = self.ledger.read_bytes()
        self.month.return_value = "2026-08"
        self.assert_error("budget_changed", setup.require_budget, KEY, self.ledger,
            transport=httpx.MockTransport(lambda request: self.fail("Clock rollback must not send")))
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_fetch_crossing_month_boundary_leaves_ledger_unchanged_for_retry(self):
        self.write_legacy_ledger()
        before = self.ledger.read_bytes()
        body = self.body(limit=None, limit_remaining=None, usage=115, byok_usage=25,
                         usage_monthly=15, byok_usage_monthly=5)
        with patch.object(setup, "_utc_month", side_effect=["2026-09", "2026-10"]):
            self.assert_error("service_unavailable", self.require, body)
        self.assertEqual(self.ledger.read_bytes(), before)
        self.month.return_value = "2026-10"
        self.assertEqual(self.require(body)["spent_usd"], 20)
        self.assertEqual(json.loads(self.ledger.read_text())["migration_month"], "2026-10")

    def test_invalid_monthly_telemetry_preserves_existing_ledger(self):
        self.require()
        before = self.ledger.read_bytes()
        body = self.body()
        del body["data"]["usage_monthly"]
        self.assert_error("budget_invalid", self.require, body)
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_invalid_version_three_ledger_fails_before_fetch(self):
        self.require(self.body(limit=None, limit_remaining=None, usage=100, byok_usage=20))
        self.require(self.body(limit=None, limit_remaining=None, usage=110, byok_usage=22))
        original = json.loads(self.ledger.read_text())
        cases = [{"version": True}, {"budget_usd": "50"}, {"month": "2026-13"},
                 {"month": "2026-9"}, {"month": "0000-01"}, {"month": "2026-08"},
                 {"migration_month": "2026-10"}, {"migration_month": None},
                 {"usage_monthly_usd": "111"}, {"byok_usage_monthly_usd": "23"},
                 {"remaining_usd": "89"}, {"spent_usd": "11", "remaining_usd": "89"},
                 {"spent_usd": "NaN"}, {"initial_usage_usd": "111"}, {"unknown": "extra"}]
        for changes in cases:
            with self.subTest(changes=changes):
                self.ledger.write_text(json.dumps({**original, **changes}), encoding="utf-8")
                before = self.ledger.read_bytes()
                self.assert_error("budget_unreadable", setup.require_budget, KEY, self.ledger,
                    transport=httpx.MockTransport(lambda request: self.fail("Bad ledger must not send")))
                self.assertEqual(self.ledger.read_bytes(), before)

    def test_later_month_ledger_cannot_understate_recorded_monthly_spend(self):
        self.require(self.body(limit=None, limit_remaining=None, usage=100, byok_usage=20))
        self.month.return_value = "2026-10"
        self.require(self.body(limit=None, limit_remaining=None, usage=120, byok_usage=25,
            usage_monthly=20, byok_usage_monthly=5))
        value = json.loads(self.ledger.read_text())
        value.update(spent_usd="24", remaining_usd="76")
        self.ledger.write_text(json.dumps(value), encoding="utf-8")
        before = self.ledger.read_bytes()
        self.assert_error("budget_unreadable", setup.require_budget, KEY, self.ledger,
            transport=httpx.MockTransport(lambda request: self.fail("Understated ledger must not send")))
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_concurrent_legacy_migration_and_month_rollover_preserve_one_ledger(self):
        original = self.write_legacy_ledger()
        calls = []

        def fetch(request):
            calls.append(request)
            index = len(calls)
            return httpx.Response(200, json=self.body(limit=None, limit_remaining=None,
                usage=110 + index + (2 if index > 2 else 0),
                byok_usage=22 + (1 if index > 2 else 0),
                usage_monthly=index, byok_usage_monthly=1))

        def check(_):
            return setup.require_budget(KEY, self.ledger, transport=httpx.MockTransport(fetch))

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(check, range(2)))
        self.assertCountEqual([value["spent_usd"] for value in results], [13, 14])
        saved = json.loads(self.ledger.read_text())
        self.assertEqual(saved["initial_usage_usd"], original["initial_usage_usd"])
        self.assertEqual(saved["key_sha256"], original["key_sha256"])
        self.month.return_value = "2026-10"
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(check, range(2)))
        self.assertCountEqual([value["spent_usd"] for value in results], [4, 5])
        saved = json.loads(self.ledger.read_text())
        self.assertEqual(saved["spent_usd"], "5")
        self.assertEqual(saved["month"], "2026-10")
        self.assertEqual(saved["migration_month"], "2026-09")

    def test_setup_previews_legacy_migration_without_modifying_saved_baseline(self):
        self.write_legacy_ledger()
        before = self.ledger.read_bytes()
        with patch.object(setup, "_is_windows", return_value=True), \
                patch.object(setup, "_reviewed_cli", return_value="reviewed-codex.exe"), \
                patch.object(setup, "_dpapi", return_value=b"encrypted-fixture"):
            result = setup.configure_openrouter(self.root, KEY, transport=self.transport(body=self.body(
                limit=None, limit_remaining=None, usage=115, byok_usage=23,
                usage_monthly=3, byok_usage_monthly=1)))
        self.assertEqual(result["spent_usd"], 18)
        self.assertEqual(result["remaining_usd"], 82)
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_unreadable_ledger_never_resets_or_sends(self):
        self.ledger.parent.mkdir(parents=True)
        for text in (KEY, "[]", '{"version":true}', "x" * 17000):
            self.ledger.write_text(text, encoding="utf-8")
            self.assert_error("budget_unreadable", setup.require_budget, KEY, self.ledger,
                transport=httpx.MockTransport(lambda request: self.fail("Bad ledger must not send")))
            self.assertEqual(self.ledger.read_text(), text)

    def test_default_ledger_is_shared_at_app_root(self):
        with patch.object(setup, "APP_ROOT", self.root):
            setup.require_budget(KEY, transport=self.transport())
        self.assertTrue(self.ledger.is_file())

    def test_concurrent_checks_wait_and_observe_the_same_initial_baseline(self):
        fetching, release, waiting = threading.Event(), threading.Event(), threading.Event()
        calls = []
        original_lock = setup.ProcessLock

        class ObservedLock(original_lock):
            def __enter__(self):
                try:
                    return super().__enter__()
                except RuntimeError:
                    waiting.set()
                    raise

        def fetch(request):
            calls.append(request)
            if len(calls) == 1:
                fetching.set()
                if not release.wait(5):
                    raise AssertionError('Concurrent budget test did not release its first fetch')
            return httpx.Response(200, json=self.body(limit=None, limit_remaining=None,
                usage=100 + len(calls), byok_usage=20))

        with patch.object(setup, 'ProcessLock', ObservedLock), ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(setup.require_budget, KEY, self.ledger, transport=httpx.MockTransport(fetch))
            try:
                self.assertTrue(fetching.wait(5))
                second = pool.submit(setup.require_budget, KEY, self.ledger, transport=httpx.MockTransport(fetch))
                self.assertTrue(waiting.wait(5))
                self.assertFalse(second.done())
                self.assertEqual(len(calls), 1, 'Waiting must cover the provider fetch, not just the file write')
            finally:
                release.set()
            self.assertEqual(first.result(timeout=5)['spent_usd'], 0)
            self.assertEqual(second.result(timeout=5)['spent_usd'], 1)
        saved = json.loads(self.ledger.read_text())
        self.assertEqual(saved['initial_usage_usd'], '101')
        self.assertEqual(saved['usage_usd'], '102')
        self.assertEqual(saved['initial_byok_usage_usd'], '20')
        self.assertEqual(saved['remaining_usd'], '99')

    def test_check_waits_for_another_process_to_release_the_budget_lock(self):
        self.require()
        lock_path = self.ledger.with_suffix('.json.lock')
        code = ('import sys\nfrom astra_web.process_lock import ProcessLock\n'
                'with ProcessLock(sys.argv[1]):\n'
                ' print("locked", flush=True)\n'
                ' sys.stdin.readline()\n')
        holder = subprocess.Popen([sys.executable, '-c', code, str(lock_path)],
            cwd=Path(setup.__file__).resolve().parent.parent, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        def close_holder():
            if holder.poll() is None:
                holder.kill()
            holder.communicate(timeout=5)

        self.addCleanup(close_holder)
        self.assertEqual(holder.stdout.readline().strip(), 'locked')
        waiting = threading.Event()
        original_lock = setup.ProcessLock

        class ObservedLock(original_lock):
            def __enter__(self):
                try:
                    return super().__enter__()
                except RuntimeError:
                    waiting.set()
                    raise

        with patch.object(setup, 'ProcessLock', ObservedLock), ThreadPoolExecutor(max_workers=1) as pool:
            check = pool.submit(self.require, self.body(usage=1.5))
            try:
                self.assertTrue(waiting.wait(5))
                self.assertFalse(check.done())
            finally:
                holder.communicate('\n', timeout=5)
            self.assertEqual(check.result(timeout=5)['spent_usd'], 1)
        self.assertEqual(holder.returncode, 0)

    def test_budget_lock_timeout_fails_closed_without_fetching_or_changing_ledger(self):
        self.require()
        before = self.ledger.read_bytes()
        with setup.ProcessLock(self.ledger.with_suffix('.json.lock')), \
                patch.object(setup, 'BUDGET_LOCK_WAIT_SECONDS', .06):
            started = time.monotonic()
            self.assert_error('budget_busy', setup.require_budget, KEY, self.ledger,
                transport=httpx.MockTransport(lambda request: self.fail('Lock timeout must not fetch telemetry')))
            elapsed = time.monotonic() - started
        self.assertGreaterEqual(elapsed, .04)
        self.assertLess(elapsed, 3)
        self.assertEqual(self.ledger.read_bytes(), before)
        self.assertEqual(self.require()['spent_usd'], 0, 'The timed-out waiter must not leave a lock held')

    def test_safe_http_errors_redirects_and_size_bounds(self):
        cases = {401: "invalid_key", 403: "access_denied", 429: "rate_limited",
                 500: "service_unavailable", 302: "unexpected_response"}
        for status, code in cases.items():
            self.assert_error(code, setup.require_budget, KEY, self.ledger,
                transport=self.transport(status, {"error": KEY}))
        for body in ([], {"data": []}, {"data": None}):
            self.assert_error("unexpected_response", self.require, body)
        for raw in (b"not json", b"x" * (setup.MAX_JSON_BYTES + 1)):
            self.assert_error("unexpected_response", setup.require_budget, KEY, self.ledger,
                transport=httpx.MockTransport(lambda request: httpx.Response(200, content=raw)))
        requests = []
        def redirect(request):
            requests.append(request)
            return httpx.Response(302, headers={"Location": "https://untrusted.invalid/"})
        self.assert_error("unexpected_response", setup.require_budget, KEY, self.ledger,
                          transport=httpx.MockTransport(redirect))
        self.assertEqual(len(requests), 1)

    def test_connection_failure_has_no_exception_content(self):
        def timeout(request):
            raise httpx.ReadTimeout(KEY)
        self.assert_error("connection_failed", setup.require_budget, KEY, self.ledger,
                          transport=httpx.MockTransport(timeout))

    def test_setup_saves_ciphertext_and_only_openrouter_files(self):
        (self.root / "var").mkdir()
        old = self.root / "var" / "local-config.json"
        old.write_text("invalid OpenAI configuration must not be read")
        with patch.object(setup, "_is_windows", return_value=True), \
                patch.object(setup, "_reviewed_cli", return_value="reviewed-codex.exe"), \
                patch.object(setup, "_dpapi", return_value=b"encrypted-fixture"):
            result = setup.configure_openrouter(self.root, KEY, transport=self.transport())
        self.assertEqual(result["limit_usd"], 100)
        self.assertFalse(self.ledger.exists())  # Setup must not start the session.
        self.assertEqual((self.root / "var" / "secrets" / "openrouter-key.dpapi").read_bytes(), b"encrypted-fixture")
        self.assertEqual(old.read_text(), "invalid OpenAI configuration must not be read")
        self.assertFalse((self.root / "var" / "secrets" / "openai-key.dpapi").exists())
        config = json.loads((self.root / "var" / "openrouter-config.json").read_text())
        self.assertEqual(config["profile"], "openrouter-glm")
        for path in self.root.rglob("*"):
            if path.is_file():
                self.assertNotIn(KEY.encode(), path.read_bytes())

    def test_setup_keeps_existing_baseline_and_rejects_credential_swap(self):
        self.require(self.body(limit=None, limit_remaining=None, usage=500, byok_usage=10))
        before = self.ledger.read_bytes()
        with patch.object(setup, "_is_windows", return_value=True), \
                patch.object(setup, "_reviewed_cli", return_value="reviewed-codex.exe"), \
                patch.object(setup, "_dpapi", return_value=b"encrypted-fixture"):
            result = setup.configure_openrouter(self.root, KEY,
                transport=self.transport(body=self.body(limit=None, limit_remaining=None, usage=505, byok_usage=12)))
            self.assertEqual(result["remaining_usd"], 93)
            self.assertEqual(before, self.ledger.read_bytes())
            self.assert_error("budget_changed", setup.configure_openrouter, self.root, OTHER_KEY,
                              transport=self.transport())

    def test_failed_setup_does_not_replace_existing_credential(self):
        config = self.write_config()
        key_path = self.root / "var" / "secrets" / "openrouter-key.dpapi"
        key_path.parent.mkdir()
        key_path.write_bytes(b"existing encrypted fixture")
        before = {path: path.read_bytes() for path in (config, key_path)}
        with patch.object(setup, "_is_windows", return_value=True), \
                patch.object(setup, "_reviewed_cli", return_value="reviewed-codex.exe"), \
                patch.object(setup, "_dpapi") as encrypt:
            self.assert_error("invalid_key", setup.configure_openrouter, self.root, KEY,
                              transport=self.transport(401))
        encrypt.assert_not_called()
        self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_loader_skips_openai_and_respects_explicit_environment(self):
        self.write_config()
        (self.root / "var" / "local-config.json").write_text("must not be read")
        explicit = {"OPENROUTER_API_KEY": KEY, "OPENAI_API_KEY": "unrelated",
                    "ASTRA_PLAYER": "disabled", "ASTRA_CODEX_BIN": "explicit.exe",
                    "ASTRA_MODEL_PROFILE": "explicit-profile"}
        with patch.object(setup.os, "environ", explicit.copy()), \
                patch.object(setup, "_dpapi", side_effect=AssertionError("Do not decrypt")), \
                patch.object(setup.httpx, "Client", side_effect=AssertionError("No network on load")):
            setup.load_openrouter_environment(self.root)
            self.assertEqual(dict(setup.os.environ), explicit)

    def test_loader_decrypts_only_openrouter_key_and_sets_profile(self):
        self.write_config()
        secret = self.root / "var" / "secrets" / "openrouter-key.dpapi"
        secret.parent.mkdir()
        secret.write_bytes(b"fixture encrypted key")
        with patch.object(setup.os, "environ", {}), \
                patch.object(setup, "_is_windows", return_value=True), \
                patch.object(setup, "_dpapi", return_value=KEY.encode()) as decrypt:
            setup.load_openrouter_environment(self.root)
            self.assertEqual(setup.os.environ["OPENROUTER_API_KEY"], KEY)
            self.assertEqual(setup.os.environ["ASTRA_MODEL_PROFILE"], setup.PROFILE)
            self.assertNotIn("OPENAI_API_KEY", setup.os.environ)
            decrypt.assert_called_once_with(b"fixture encrypted key", decrypt=True)

    def test_invalid_config_and_failed_decryption_do_not_partially_set_environment(self):
        for extra in ({"version": True}, {"profile": "other"}, {"unknown": 1}):
            self.write_config(**extra)
            with patch.object(setup.os, "environ", {}):
                self.assert_error("configuration_invalid", setup.load_openrouter_environment, self.root)
                self.assertEqual(dict(setup.os.environ), {})
        self.write_config()
        with patch.object(setup.os, "environ", {}), patch.object(setup, "_is_windows", return_value=False):
            self.assert_error("windows_only", setup.load_openrouter_environment, self.root)
            self.assertEqual(dict(setup.os.environ), {})
        with patch.object(setup.os, "environ", {}), patch.object(setup, "_is_windows", return_value=True):
            self.assert_error("credential_missing", setup.load_openrouter_environment, self.root)
            self.assertEqual(dict(setup.os.environ), {})

    def test_absent_setup_is_optional_and_never_loads_openai_config(self):
        folder = self.root / "var"
        folder.mkdir()
        (folder / "local-config.json").write_text("not valid JSON")
        with patch.object(setup.os, "environ", {}):
            setup.load_openrouter_environment(self.root)
            self.assertEqual(dict(setup.os.environ), {})

    def test_cli_version_check_is_secret_free_and_rejects_unknown_versions(self):
        binary = self.root / "codex.exe"
        binary.write_bytes(b"fixture never executed")
        with patch.object(setup.shutil, "which", return_value=str(binary)), \
                patch.object(setup.os, "environ", {"OPENROUTER_API_KEY": KEY, "OPENAI_API_KEY": OTHER_KEY,
                    "CODEX_HOME": "private operator home", "HTTP_PROXY": "private proxy"}), \
                patch.object(setup.subprocess, "run", return_value=SimpleNamespace(
                    returncode=0, stdout=b"codex-cli 0.154.0\n")) as run:
            self.assertEqual(setup._reviewed_cli(str(binary), self.root), str(binary.resolve()))
            passed = run.call_args.kwargs
            self.assertNotIn("OPENROUTER_API_KEY", passed["env"])
            self.assertNotIn("OPENAI_API_KEY", passed["env"])
            self.assertNotIn("HTTP_PROXY", passed["env"])
            self.assertNotEqual(passed["env"]["CODEX_HOME"], "private operator home")
            self.assertEqual(run.call_args.args[0], [str(binary.resolve()), "--version"])
            self.assertEqual(passed["timeout"], 10)
            run.return_value = SimpleNamespace(returncode=0, stdout=KEY.encode())
            self.assert_error("cli_unreviewed", setup._reviewed_cli, str(binary), self.root)
            run.side_effect = subprocess.TimeoutExpired(KEY, 10)
            self.assert_error("cli_unreviewed", setup._reviewed_cli, str(binary), self.root)

    def test_cli_hidden_prompt_refuses_echo_and_redacts_failures(self):
        output = io.StringIO()
        with patch.object(cli, "_is_windows", return_value=True), \
                patch.object(cli.getpass, "getpass", return_value=KEY), \
                patch.object(cli, "configure_openrouter", side_effect=RuntimeError(KEY)), \
                contextlib.redirect_stdout(output):
            self.assertEqual(cli.main([]), 1)
        self.assertNotIn(KEY, output.getvalue())
        self.assertIn(setup.MESSAGES["save_failed"], output.getvalue())
        with patch.object(cli, "_is_windows", return_value=True), \
                patch.object(cli.getpass, "getpass", side_effect=getpass.GetPassWarning()), \
                patch.object(cli, "configure_openrouter") as configure, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main([]), 1)
            configure.assert_not_called()


if __name__ == "__main__":
    unittest.main()
