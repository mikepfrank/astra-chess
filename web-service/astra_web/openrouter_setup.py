"""Isolated OpenRouter credentials and a $100 UTC calendar-month spending guard.

No inference request is made here. GET /api/v1/key supplies cumulative and UTC
monthly OpenRouter and BYOK usage, including other use of a shared key. Migration
charges all usage since the experiment's original baseline to the current month.
Later months use provider monthly counters, even after a period without checks.
This is a local admission check, not a provider-enforced hard spending cap:
in-flight work and reporting delay can exceed the remaining allowance. Refuse
new requests once the allowance is exhausted, and pin one credential across this
worktree's game directories so replacing it cannot restart the allowance.
Credential setup only validates telemetry; the first action preflight records
the baseline immediately before model work. Subsequent preflights keep it.

Provider references checked September 23, 2026:
https://openrouter.ai/docs/api_reference/limits
https://openrouter.ai/docs/api/api-reference/api-keys/get-current-key
https://openrouter.zendesk.com/hc/en-us/articles/51680687417499-Can-I-create-one-API-key-per-user-with-its-own-spending-limit-Management-API-keys

The application needs an inference key, never a management key. Real keys and
the private budget fingerprint must not enter model context or public records.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

import httpx

from .local_setup import _atomic_write, _clean_key, _dpapi, _is_windows, LocalSetupError
from .process_lock import ProcessLock


APP_ROOT = Path(__file__).resolve().parents[1]
KEY_URL = "https://openrouter.ai/api/v1/key"
PROFILE = "openrouter-glm"
MAX_BUDGET = Decimal("100")
STOP_REMAINING = Decimal("0")
MAX_JSON_BYTES = 65536
BUDGET_LOCK_WAIT_SECONDS = 30
BUDGET_LOCK_POLL_SECONDS = .05
MESSAGES = {
    "saved": "OpenRouter credential and local monthly budget saved for this Windows user.",
    "invalid_key": "OpenRouter rejected the credential. Nothing was saved.",
    "access_denied": "The OpenRouter credential does not have the required access.",
    "budget_invalid": "OpenRouter did not provide valid cumulative and UTC monthly usage or credit-limit metadata. No new model action is permitted.",
    "budget_low": "The OpenRouter monthly allowance or provider credit limit is exhausted; no new model action is permitted.",
    "budget_changed": "The experiment credential or recorded usage changed. Budget reconciliation is required before continuing.",
    "budget_unreadable": "The private OpenRouter budget record could not be safely read or updated.",
    "budget_busy": "Another OpenRouter budget check did not finish within the allowed wait. Retry shortly.",
    "rate_limited": "OpenRouter budget verification was rate limited. No model action was started.",
    "service_unavailable": "OpenRouter budget verification is temporarily unavailable. No model action was started.",
    "connection_failed": "Could not securely verify the OpenRouter budget. No model action was started.",
    "unexpected_response": "OpenRouter budget verification returned an unexpected response.",
    "windows_only": "Local encrypted credential storage requires Windows. On Linux set OPENROUTER_API_KEY in the service environment.",
    "cli_unavailable": "Choose an existing reviewed Codex executable with --codex-bin.",
    "cli_unreviewed": "The selected executable did not report an audited Codex CLI version.",
    "configuration_invalid": "The isolated OpenRouter configuration is invalid. Run configure_openrouter.py again.",
    "credential_missing": "The saved OpenRouter credential is missing. Run configure_openrouter.py or set OPENROUTER_API_KEY.",
    "credential_unreadable": "This Windows user could not decrypt the saved OpenRouter credential.",
    "save_failed": "OpenRouter setup could not be saved. Check the application directory permissions.",
    "input_unavailable": "A hidden interactive terminal prompt is required. Run configure_openrouter.py in a terminal.",
    "cancelled": "OpenRouter setup cancelled.",
}


class OpenRouterSetupError(RuntimeError):
    """Safe classification only: never include HTTP bodies or raw exceptions."""

    def __init__(self, code):
        self.code = code
        super().__init__(MESSAGES[code])


def _key(value):
    try:
        return _clean_key(value)
    except LocalSetupError:
        raise OpenRouterSetupError("invalid_key") from None


def _money(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise OpenRouterSetupError("budget_invalid")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise OpenRouterSetupError("budget_invalid") from None
    if not result.is_finite() or result < 0:
        raise OpenRouterSetupError("budget_invalid")
    return result


def _fetch_budget(key, transport):
    try:
        with httpx.Client(transport=transport, timeout=25, trust_env=False,
                          follow_redirects=False) as client:
            with client.stream("GET", KEY_URL, headers={"Authorization": "Bearer " + key}) as response:
                classifications = {401: "invalid_key", 403: "access_denied", 429: "rate_limited"}
                if response.status_code != 200:
                    code = classifications.get(response.status_code,
                        "service_unavailable" if response.status_code >= 500 else "unexpected_response")
                    raise OpenRouterSetupError(code)
                chunks, length = [], 0
                for chunk in response.iter_bytes():
                    length += len(chunk)
                    if length > MAX_JSON_BYTES:
                        raise OpenRouterSetupError("unexpected_response")
                    chunks.append(chunk)
        payload = json.loads(b"".join(chunks), parse_float=Decimal)
    except OpenRouterSetupError:
        raise
    except (httpx.HTTPError, OSError):
        raise OpenRouterSetupError("connection_failed") from None
    except (ValueError, UnicodeError):
        raise OpenRouterSetupError("unexpected_response") from None
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        raise OpenRouterSetupError("unexpected_response")
    data = payload["data"]
    if not {"usage", "byok_usage", "usage_monthly", "byok_usage_monthly"} <= data.keys():
        raise OpenRouterSetupError("budget_invalid")
    usage, byok = (_money(data[name]) for name in ("usage", "byok_usage"))
    monthly, byok_monthly = (_money(data[name]) for name in ("usage_monthly", "byok_usage_monthly"))
    if monthly > usage or byok_monthly > byok:
        raise OpenRouterSetupError("budget_invalid")
    limit = None if data.get("limit") is None else _money(data["limit"])
    remaining = None if data.get("limit_remaining") is None else _money(data["limit_remaining"])
    if limit is not None and remaining is not None and remaining > limit:
        raise OpenRouterSetupError("budget_invalid")
    return {"provider_limit_usd": limit, "provider_remaining_usd": remaining,
            "usage_usd": usage, "byok_usage_usd": byok,
            "usage_monthly_usd": monthly, "byok_usage_monthly_usd": byok_monthly}


def _utc_month():
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _valid_month(value):
    return isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{3}-(0[1-9]|1[0-2])", value)


def _ledger(path):
    if not path.exists():
        return None
    try:
        if not path.is_file() or path.stat().st_size > 16384:
            raise ValueError()
        data = json.loads(path.read_text(encoding="utf-8"))
        expected = {"version", "key_sha256", "budget_usd", "initial_usage_usd",
                    "initial_byok_usage_usd", "usage_usd", "byok_usage_usd", "remaining_usd"}
        if isinstance(data, dict) and data.get("version") == 3:
            expected |= {"migration_month", "month", "usage_monthly_usd", "byok_usage_monthly_usd", "spent_usd"}
        if (not isinstance(data, dict) or set(data) != expected
                or type(data["version"]) is not int or data["version"] not in (2, 3)
                or not isinstance(data["key_sha256"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", data["key_sha256"])):
            raise ValueError()
        for name in expected - {"version", "key_sha256", "migration_month", "month"}:
            if not isinstance(data[name], str):
                raise ValueError()
            value = Decimal(data[name])
            if not value.is_finite() or value < 0:
                raise ValueError()
        expected_budget = Decimal("50") if data["version"] == 2 else MAX_BUDGET
        if Decimal(data["budget_usd"]) != expected_budget:
            raise ValueError()
        if data["version"] == 3:
            if (not _valid_month(data["month"]) or not _valid_month(data["migration_month"])
                    or data["month"] < data["migration_month"]
                    or Decimal(data["usage_monthly_usd"]) > Decimal(data["usage_usd"])
                    or Decimal(data["byok_usage_monthly_usd"]) > Decimal(data["byok_usage_usd"])
                    or Decimal(data["remaining_usd"]) > max(Decimal("0"), MAX_BUDGET - Decimal(data["spent_usd"]))):
                raise ValueError()
            accounted = (Decimal(data["usage_usd"]) - Decimal(data["initial_usage_usd"])
                         + Decimal(data["byok_usage_usd"]) - Decimal(data["initial_byok_usage_usd"]))
            if data["month"] != data["migration_month"]:
                accounted = Decimal(data["usage_monthly_usd"]) + Decimal(data["byok_usage_monthly_usd"])
            if Decimal(data["spent_usd"]) < accounted:
                raise ValueError()
        if (Decimal(data["usage_usd"]) < Decimal(data["initial_usage_usd"])
                or Decimal(data["byok_usage_usd"]) < Decimal(data["initial_byok_usage_usd"])):
            raise ValueError()
        return data
    except (OSError, ValueError, InvalidOperation, UnicodeError):
        raise OpenRouterSetupError("budget_unreadable") from None


@contextmanager
def _budget_lock(path):
    """Wait only for budget telemetry; leave the service singleton lock unchanged."""
    deadline = time.monotonic() + BUDGET_LOCK_WAIT_SECONDS
    while True:
        lock = ProcessLock(path)
        try:
            lock.__enter__()
        except RuntimeError:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise OpenRouterSetupError("budget_busy") from None
            time.sleep(min(BUDGET_LOCK_POLL_SECONDS, remaining))
            if time.monotonic() >= deadline:
                raise OpenRouterSetupError("budget_busy") from None
        else:
            break
    try:
        yield
    finally:
        lock.__exit__(None, None, None)


def _check_budget(key, ledger_path, transport, *, persist):
    key = _key(key)
    path = Path(ledger_path or os.getenv('ASTRA_OPENROUTER_BUDGET_PATH') or APP_ROOT / "var" / "openrouter-budget.json")
    key_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _budget_lock(path.with_suffix(path.suffix + ".lock")):
            previous = _ledger(path)
            if previous is not None and previous["key_sha256"] != key_hash:
                raise OpenRouterSetupError("budget_changed")
            month = _utc_month()
            if previous and previous["version"] == 3 and month < previous["month"]:
                raise OpenRouterSetupError("budget_changed")
            verified = _fetch_budget(key, transport)
            # Never attribute a response spanning midnight on the first to an
            # ambiguous month. A fresh check can retry without altering evidence.
            if _utc_month() != month:
                raise OpenRouterSetupError("service_unavailable")
            if previous is not None and (verified["usage_usd"] < Decimal(previous["usage_usd"])
                    or verified["byok_usage_usd"] < Decimal(previous["byok_usage_usd"])):
                raise OpenRouterSetupError("budget_changed")
            if previous and previous["version"] == 3 and month > previous["month"]:
                # The new month's usage cannot exceed all usage since a check
                # in an earlier month. Do not pin an obviously stale pre-reset
                # counter as the new month's high-water mark; retry fresh data.
                for total, monthly in (("usage_usd", "usage_monthly_usd"),
                                       ("byok_usage_usd", "byok_usage_monthly_usd")):
                    if verified[monthly] > verified[total] - Decimal(previous[total]):
                        raise OpenRouterSetupError("budget_invalid")
            initial_usage = Decimal(previous["initial_usage_usd"]) if previous else verified["usage_usd"]
            initial_byok = Decimal(previous["initial_byok_usage_usd"]) if previous else verified["byok_usage_usd"]
            migration_month = previous["migration_month"] if previous and previous["version"] == 3 else month
            if month == migration_month:
                spent = verified["usage_usd"] - initial_usage + verified["byok_usage_usd"] - initial_byok
            else:
                spent = verified["usage_monthly_usd"] + verified["byok_usage_monthly_usd"]
            if previous and previous["version"] == 3 and previous["month"] == month:
                # Reporting corrections cannot quietly refund an admitted month.
                spent = max(spent, Decimal(previous["spent_usd"]))
            remaining = max(Decimal("0"), MAX_BUDGET - spent)
            if verified["provider_remaining_usd"] is not None:
                remaining = min(remaining, verified["provider_remaining_usd"])
            saved = {"version": 3, "key_sha256": key_hash, "budget_usd": str(MAX_BUDGET),
                     "migration_month": migration_month, "month": month, "spent_usd": str(spent),
                     "usage_monthly_usd": str(verified["usage_monthly_usd"]),
                     "byok_usage_monthly_usd": str(verified["byok_usage_monthly_usd"]),
                     "initial_usage_usd": str(initial_usage), "initial_byok_usage_usd": str(initial_byok),
                     "usage_usd": str(verified["usage_usd"]),
                     "byok_usage_usd": str(verified["byok_usage_usd"]), "remaining_usd": str(remaining)}
            if persist:
                _atomic_write(path, (json.dumps(saved, indent=2) + "\n").encode("utf-8"))
                if os.name != "nt":
                    path.chmod(0o600)
            if remaining <= STOP_REMAINING:
                raise OpenRouterSetupError("budget_low")
    except OpenRouterSetupError:
        raise
    except OSError:
        raise OpenRouterSetupError("budget_unreadable") from None
    except RuntimeError:
        raise OpenRouterSetupError("budget_busy") from None
    return {"budget_enforcement": "local-utc-calendar-month", "month": month, "timezone": "UTC",
            "limit_usd": float(MAX_BUDGET),
            "spent_usd": float(spent), "remaining_usd": float(remaining),
            "provider_limit_usd": (None if verified["provider_limit_usd"] is None
                                   else float(verified["provider_limit_usd"])),
            "provider_remaining_usd": (None if verified["provider_remaining_usd"] is None
                                       else float(verified["provider_remaining_usd"])),
            "stop_remaining_usd": float(STOP_REMAINING)}


def require_budget(key, ledger_path: Path | None = None, *, transport=None):
    """Verify monthly usage/migrate the legacy ledger; suitable for to_thread.

    The default ledger belongs to the worktree, not a disposable game's data
    directory. Callers wait at most thirty seconds to acquire the shared OS lock;
    it covers the ledger read, telemetry fetch and write, never model inference.
    Cancelling an asyncio.to_thread caller does not stop this synchronous check:
    it may finish its bounded wait and telemetry update, but starts no model work.
    The returned dict contains no key, hash, account label, or raw response.
    """
    return _check_budget(key, ledger_path, transport, persist=True)


def _read_config(path):
    if not path.exists():
        return {}
    try:
        if path.stat().st_size > 16384:
            raise ValueError()
        data = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(data, dict) or set(data) != {"version", "profile", "player", "codex_bin"}
                or type(data["version"]) is not int or data["version"] != 1
                or data["profile"] != PROFILE or data["player"] != "codex"
                or not isinstance(data["codex_bin"], str) or not data["codex_bin"]
                or len(data["codex_bin"]) > 4096 or "\x00" in data["codex_bin"]):
            raise ValueError()
        return data
    except (OSError, ValueError, UnicodeError):
        raise OpenRouterSetupError("configuration_invalid") from None


def _reviewed_cli(binary, folder):
    # Lazy import prevents setup/bridge cycles. Version-only subprocess receives
    # no provider credentials or operator Codex home and does not start a turn.
    from .codex_bridge import reviewed_versions, _child_environment
    resolved = shutil.which(binary)
    if not resolved or not Path(resolved).is_file():
        raise OpenRouterSetupError("cli_unavailable")
    try:
        with tempfile.TemporaryDirectory(prefix="openrouter-version-", dir=folder) as temporary:
            root = Path(temporary)
            for child in ("codex-home", "tmp", "appdata"):
                (root / child).mkdir()
            environment = _child_environment(root, root / "codex-home", include_key=False)
            kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
            result = subprocess.run([str(Path(resolved).resolve()), "--version"], cwd=root,
                env=environment, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                timeout=10, check=False, **kwargs)
            accepted = {f"codex-cli {version}" for version in reviewed_versions(PROFILE)}
            if result.returncode != 0 or result.stdout.decode("utf-8", errors="replace").strip() not in accepted:
                raise OpenRouterSetupError("cli_unreviewed")
    except OpenRouterSetupError:
        raise
    except (OSError, subprocess.SubprocessError):
        raise OpenRouterSetupError("cli_unreviewed") from None
    return str(Path(resolved).resolve())


def configure_openrouter(app_root, key, codex_bin=None, *, transport=None):
    """Verify CLI and usage baseline, then store only DPAPI ciphertext/settings."""
    if not _is_windows():
        raise OpenRouterSetupError("windows_only")
    key = _key(key)
    folder = Path(app_root) / "var"
    try:
        previous = _read_config(folder / "openrouter-config.json")
        folder.mkdir(parents=True, exist_ok=True)
        binary = codex_bin or os.environ.get("ASTRA_CODEX_BIN") or previous.get("codex_bin") or "codex"
        resolved = _reviewed_cli(binary, folder)
        budget = _check_budget(key, folder / "openrouter-budget.json", transport, persist=False)
        encrypted = _dpapi(key.encode("utf-8"))
        settings = {"version": 1, "profile": PROFILE, "player": "codex", "codex_bin": resolved}
        _atomic_write(folder / "secrets" / "openrouter-key.dpapi", encrypted)
        _atomic_write(folder / "openrouter-config.json", (json.dumps(settings, indent=2) + "\n").encode("utf-8"))
        return budget
    except OpenRouterSetupError:
        raise
    except (OSError, ValueError, LocalSetupError):
        raise OpenRouterSetupError("save_failed") from None


def load_openrouter_environment(app_root):
    """Load only this experiment's settings; explicit environment always wins.

    This never reads local-config.json/openai-key.dpapi, sets OPENAI_API_KEY, or
    verifies the key over the network. The bridge checks the budget before work.
    """
    folder = Path(app_root) / "var"
    settings = _read_config(folder / "openrouter-config.json")
    if not settings:
        return
    pending = {"ASTRA_MODEL_PROFILE": settings["profile"], "ASTRA_PLAYER": settings["player"],
               "ASTRA_CODEX_BIN": settings["codex_bin"]}
    if "OPENROUTER_API_KEY" not in os.environ:
        if not _is_windows():
            raise OpenRouterSetupError("windows_only")
        path = folder / "secrets" / "openrouter-key.dpapi"
        if not path.is_file():
            raise OpenRouterSetupError("credential_missing")
        try:
            if path.stat().st_size > 65536:
                raise ValueError()
            pending["OPENROUTER_API_KEY"] = _key(_dpapi(path.read_bytes(), decrypt=True).decode("utf-8"))
        except (OSError, ValueError, UnicodeError, LocalSetupError, OpenRouterSetupError):
            raise OpenRouterSetupError("credential_unreadable") from None
    for name, value in pending.items():
        os.environ.setdefault(name, value)
