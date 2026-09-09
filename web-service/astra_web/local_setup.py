"""Optional Windows-user credential storage for local testing.

Only DPAPI ciphertext goes to disk. Production and non-Windows hosts can supply
OPENAI_API_KEY in the environment; explicit environment settings always win.
"""
import ctypes
import json
import os
from pathlib import Path
import shutil
import tempfile

import httpx


MODEL_URL = "https://api.openai.com/v1/models/gpt-6-astra"
MODEL_ID = "gpt-6-astra"
MESSAGES = {
    "saved": "Credential validated and saved for this Windows user.",
    "invalid_key": "The credential was rejected. Nothing was saved.",
    "access_denied": "The credential does not have the required access. Nothing was saved.",
    "model_unavailable": "The requested Astra model is unavailable to this credential. Nothing was saved.",
    "rate_limited": "Validation was rate limited. Try again later; nothing was saved.",
    "service_unavailable": "OpenAI validation is temporarily unavailable. Nothing was saved.",
    "connection_failed": "Could not securely connect to OpenAI. Nothing was saved.",
    "unexpected_response": "Validation returned an unexpected response. Nothing was saved.",
    "windows_only": "Local credential storage requires Windows. Set OPENAI_API_KEY in the environment on other hosts.",
    "cli_unavailable": "Choose an existing reviewed Codex executable with --codex-bin.",
    "configuration_invalid": "Local setup configuration is invalid. Run configure_local.py again.",
    "credential_missing": "The saved credential is missing. Run configure_local.py again or set OPENAI_API_KEY.",
    "credential_unreadable": "This Windows user could not decrypt the saved credential. Run configure_local.py again or set OPENAI_API_KEY.",
    "save_failed": "Local setup could not be saved. Check the application directory permissions.",
    "input_unavailable": "A hidden interactive terminal prompt is required. Run configure_local.py in a terminal.",
    "cancelled": "Setup cancelled. Nothing was saved.",
}


class LocalSetupError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(MESSAGES[code])


def _is_windows():
    return os.name == "nt"


def _clean_key(key):
    if not isinstance(key, str):
        raise LocalSetupError("invalid_key")
    key = key.strip()
    if not 10 <= len(key) <= 4096 or not key.isascii() or any(ord(c) <= 32 or ord(c) == 127 for c in key):
        raise LocalSetupError("invalid_key")
    return key


def _dpapi(data: bytes, decrypt: bool = False) -> bytes:
    if not _is_windows():
        raise LocalSetupError("windows_only")
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    source = ctypes.create_string_buffer(data)
    incoming = Blob(len(data), ctypes.cast(source, ctypes.POINTER(ctypes.c_ubyte)))
    outgoing = Blob()
    function = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p if decrypt else wintypes.LPCWSTR,
                         ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                         wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    try:
        # CRYPTPROTECT_UI_FORBIDDEN only: no LOCAL_MACHINE flag, no dialog fallback.
        if not function(ctypes.byref(incoming), None if decrypt else "Astra chess local API key",
                        None, None, None, 1, ctypes.byref(outgoing)):
            raise LocalSetupError("credential_unreadable" if decrypt else "save_failed")
        return ctypes.string_at(outgoing.data, outgoing.size)
    finally:
        ctypes.memset(source, 0, len(source))
        if outgoing.data:
            ctypes.memset(outgoing.data, 0, outgoing.size)
            kernel32.LocalFree(ctypes.cast(outgoing.data, ctypes.c_void_p))


def validate_api_key(key: str, *, transport=None) -> str:
    """Return a classification only; API response/error text never leaves here."""
    try:
        key = _clean_key(key)
    except LocalSetupError:
        return "invalid_key"
    try:
        with httpx.Client(transport=transport, timeout=25, trust_env=False,
                          follow_redirects=False) as client:
            response = client.get(MODEL_URL, headers={"Authorization": "Bearer " + key})
        if response.status_code == 200:
            return "validated" if response.json().get("id") == MODEL_ID else "unexpected_response"
        if response.status_code in (401, 403, 404, 429):
            return {401: "invalid_key", 403: "access_denied", 404: "model_unavailable", 429: "rate_limited"}[response.status_code]
        return "service_unavailable" if 500 <= response.status_code < 600 else "unexpected_response"
    except (httpx.HTTPError, OSError):
        return "connection_failed"
    except (ValueError, AttributeError):
        return "unexpected_response"


def _read_config(path):
    if not path.exists():
        return {}
    try:
        if path.stat().st_size > 16384:
            raise ValueError()
        data = json.loads(path.read_text(encoding="utf-8"))
        required = {"version", "player", "codex_bin"}
        allowed = required | {"max_daily_tokens"}
        if (not isinstance(data, dict) or not required <= set(data) or not set(data) <= allowed
                or type(data["version"]) is not int or data["version"] != 1 or data["player"] != "codex"
                or not isinstance(data["codex_bin"], str) or not data["codex_bin"]
                or len(data["codex_bin"]) > 4096 or "\x00" in data["codex_bin"]):
            raise ValueError()
        if "max_daily_tokens" in data and (type(data["max_daily_tokens"]) is not int
                                          or data["max_daily_tokens"] <= 0):
            raise ValueError()
        return data
    except (OSError, ValueError, UnicodeError):
        raise LocalSetupError("configuration_invalid") from None


def _atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix="." + path.name,
                                         suffix=".tmp", delete=False) as file:
            temporary = Path(file.name)
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def configure_local(app_root, key: str, codex_bin: str | None = None, *, transport=None) -> str:
    """Validate first, then save DPAPI ciphertext and a nonsecret CLI path."""
    if not _is_windows():
        return "windows_only"
    status = validate_api_key(key, transport=transport)
    if status != "validated":
        return status
    folder = Path(app_root) / "var"
    try:
        previous = _read_config(folder / "local-config.json")
        if not codex_bin:
            codex_bin = os.environ.get("ASTRA_CODEX_BIN") or previous.get("codex_bin") or "codex"
        resolved = shutil.which(codex_bin)
        if not resolved or not Path(resolved).is_file():
            return "cli_unavailable"
        settings = {"version": 1, "player": "codex", "codex_bin": str(Path(resolved).resolve())}
        if "max_daily_tokens" in previous:
            settings["max_daily_tokens"] = previous["max_daily_tokens"]
        encrypted = _dpapi(_clean_key(key).encode("utf-8"))
        _atomic_write(folder / "secrets" / "openai-key.dpapi", encrypted)
        _atomic_write(folder / "local-config.json", (json.dumps(settings, indent=2) + "\n").encode("utf-8"))
        return "saved"
    except LocalSetupError as error:
        return error.code
    except (OSError, ValueError):
        return "save_failed"


def load_local_environment(app_root):
    """Load optional local settings without overriding any explicit environment."""
    folder = Path(app_root) / "var"
    settings = _read_config(folder / "local-config.json")
    if not settings:
        return
    pending = {"ASTRA_CODEX_BIN": settings["codex_bin"], "ASTRA_PLAYER": settings["player"]}
    if "max_daily_tokens" in settings:
        pending["ASTRA_MAX_DAILY_TOKENS"] = str(settings["max_daily_tokens"])
    if "OPENAI_API_KEY" not in os.environ:
        if not _is_windows():
            raise LocalSetupError("windows_only")
        path = folder / "secrets" / "openai-key.dpapi"
        if not path.is_file():
            raise LocalSetupError("credential_missing")
        try:
            if path.stat().st_size > 65536:
                raise ValueError()
            pending["OPENAI_API_KEY"] = _clean_key(_dpapi(path.read_bytes(), decrypt=True).decode("utf-8"))
        except (OSError, ValueError, UnicodeError, LocalSetupError):
            raise LocalSetupError("credential_unreadable") from None
    for name, value in pending.items():
        os.environ.setdefault(name, value)
