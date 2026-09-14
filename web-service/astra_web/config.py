from dataclasses import dataclass, field
import ipaddress
from pathlib import Path
import os
import re
from urllib.parse import urlsplit


APP_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = APP_ROOT.parent


def origin_host_authorities(origin):
    """Validate a bare HTTP(S) origin and return its exact Host representations."""
    if (not isinstance(origin, str) or not 1 <= len(origin) <= 2048
            or any(ord(char) <= 32 or ord(char) >= 127 for char in origin)):
        raise ValueError('Origins must be bare ASCII HTTP(S) origins')
    try:
        parts = urlsplit(origin)
        hostname, port = parts.hostname, parts.port
        if (parts.scheme not in {'http', 'https'} or not hostname
                or parts.username is not None or parts.password is not None
                or origin != parts.scheme + '://' + parts.netloc
                or parts.netloc != parts.netloc.lower()):
            raise ValueError
        if ':' in hostname:
            ipaddress.IPv6Address(hostname)
            host = '[' + hostname + ']'
        else:
            if (len(hostname) > 253 or not re.fullmatch(
                    r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?'
                    r'(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*', hostname)):
                raise ValueError
            host = hostname
        if port is not None and not 1 <= port <= 65535:
            raise ValueError
        # Reject ambiguous authorities such as an empty port or zero padding.
        if parts.netloc != host + (':' + str(port) if port is not None else ''):
            raise ValueError
    except ValueError:
        raise ValueError('Origins must contain only an HTTP(S) scheme, hostname and optional port') from None
    default_port = 443 if parts.scheme == 'https' else 80
    if port is None or port == default_port:
        return frozenset({host, host + ':' + str(default_port)})
    return frozenset({host + ':' + str(port)})


def is_bare_email(value: str) -> bool:
    """Accept one ASCII mailbox without display names, comments or header syntax."""
    if not isinstance(value, str) or len(value) > 254 or not re.fullmatch(
            r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
            r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+", value):
        return False
    local, domain = value.rsplit("@", 1)
    return (len(local) <= 64 and not local.startswith(".") and not local.endswith(".") and
            ".." not in local and all(len(label) <= 63 for label in domain.split(".")))


@dataclass
class Config:
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("ASTRA_DATA_DIR", str(APP_ROOT / "var"))).resolve())
    origin: str = field(default_factory=lambda: os.getenv("ASTRA_ORIGIN", "http://127.0.0.1:8788").rstrip("/"))
    additional_origins: tuple[str, ...] = field(default_factory=lambda: tuple(
        part.strip() for part in os.getenv('ASTRA_ADDITIONAL_ORIGINS', '').split(','))
        if os.getenv('ASTRA_ADDITIONAL_ORIGINS', '').strip() else ())
    model_profile: str = field(default_factory=lambda: os.getenv("ASTRA_MODEL_PROFILE", "astra"))
    persona: str | None = field(default_factory=lambda: os.getenv("ASTRA_PERSONA"))
    model: str | None = None
    reasoning: str | None = None
    player_mode: str = field(default_factory=lambda: os.getenv("ASTRA_PLAYER", "disabled"))
    codex_bin: str = field(default_factory=lambda: os.getenv("ASTRA_CODEX_BIN", "codex"))
    max_workers: int = field(default_factory=lambda: int(os.getenv("ASTRA_MAX_WORKERS", "1")))
    max_games_per_user: int = 3
    suspend_hours: float = 36
    ordinary_seconds: float = 120
    critical_seconds: float = 240
    max_queries: int = 8
    max_messages_per_minute: int = 6
    max_daily_turns: int = field(default_factory=lambda: int(os.getenv("ASTRA_MAX_DAILY_TURNS", "500")))
    max_turn_tokens: int = field(default_factory=lambda: int(os.getenv("ASTRA_MAX_TURN_TOKENS", "3000000")))
    max_daily_tokens: int = field(default_factory=lambda: int(os.getenv("ASTRA_MAX_DAILY_TOKENS", "20000000")))
    operator_user_id: str = field(default_factory=lambda: os.getenv("ASTRA_OPERATOR_USER_ID", "").strip())
    monitor_excluded_game_ids: tuple[str, ...] = field(default_factory=lambda: tuple(
        part.strip() for part in os.getenv("ASTRA_MONITOR_EXCLUDED_GAME_IDS", "").split(','))
        if os.getenv("ASTRA_MONITOR_EXCLUDED_GAME_IDS", "").strip() else ())
    smtp_host: str = field(default_factory=lambda: os.getenv("ASTRA_SMTP_HOST", ""))
    smtp_port: int = field(default_factory=lambda: int(os.getenv("ASTRA_SMTP_PORT", "587")))
    smtp_user: str = field(default_factory=lambda: os.getenv("ASTRA_SMTP_USER", ""))
    smtp_password: str = field(default_factory=lambda: os.getenv("ASTRA_SMTP_PASSWORD", ""))
    smtp_from: str = field(default_factory=lambda: os.getenv("ASTRA_SMTP_FROM", ""))
    smtp_feedback_address: str = field(default_factory=lambda: os.getenv("ASTRA_SMTP_FEEDBACK_ADDRESS", ""))
    secure_cookies: bool = field(default_factory=lambda: os.getenv("ASTRA_ORIGIN", "").startswith("https://"))

    def __post_init__(self):
        from .player_profiles import get_profile
        profile = get_profile(self.model_profile)
        if self.model is None:
            self.model = profile.model
        if self.reasoning is None:
            self.reasoning = profile.reasoning
        if profile.name == 'openrouter-glm':
            # At the 250K compaction threshold each tool round repeats context.
            # Allow compaction plus a complete status/candidate/query/choose
            # action, while preserving any smaller operator-configured limit.
            self.max_turn_tokens = min(self.max_turn_tokens, 2_000_000)

    @property
    def db_path(self):
        return self.data_dir / "astra.sqlite3"

    def validate(self):
        from .player_profiles import persona_for, profile_for
        origin_host_authorities(self.origin)
        if not isinstance(self.additional_origins, tuple) or len(self.additional_origins) > 8:
            raise ValueError('ASTRA_ADDITIONAL_ORIGINS must be a tuple of at most eight origins')
        origins = (self.origin, *self.additional_origins)
        for alias in self.additional_origins:
            origin_host_authorities(alias)
            if urlsplit(alias).scheme != urlsplit(self.origin).scheme:
                raise ValueError('Additional origins must use the canonical origin scheme')
        if len(set(origins)) != len(origins):
            raise ValueError('Configured origins must be distinct')
        profile = profile_for(self)
        persona_for(self)
        if profile.name == 'openrouter-glm' and self.max_workers != 1:
            raise ValueError('Initial OpenRouter experiments require one worker')
        if self.player_mode not in {"disabled", "codex", "test"}:
            raise ValueError("ASTRA_PLAYER must be disabled, codex, or test")
        if self.max_workers < 1 or self.max_workers > 16:
            raise ValueError("ASTRA_MAX_WORKERS must be between 1 and 16")
        if self.max_daily_tokens < 1 or self.max_turn_tokens < 1 or self.max_daily_turns < 1:
            raise ValueError("Resource limits must be positive")
        if self.operator_user_id and not re.fullmatch(r"[0-9a-f]{32}", self.operator_user_id):
            raise ValueError("ASTRA_OPERATOR_USER_ID must be one existing 32-character lowercase hexadecimal account ID")
        if not isinstance(self.monitor_excluded_game_ids, tuple) or any(
                not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{32}", value)
                for value in self.monitor_excluded_game_ids):
            raise ValueError("ASTRA_MONITOR_EXCLUDED_GAME_IDS must contain comma-separated 32-character lowercase hexadecimal game IDs")
        if self.smtp_feedback_address and not is_bare_email(self.smtp_feedback_address):
            raise ValueError("ASTRA_SMTP_FEEDBACK_ADDRESS must be a single bare email address")
        self.data_dir.mkdir(parents=True, exist_ok=True)
