from dataclasses import dataclass, field
from pathlib import Path
import os
import re


APP_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = APP_ROOT.parent


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
    model: str = "gpt-6-astra"
    reasoning: str = "ultra"
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
    smtp_host: str = field(default_factory=lambda: os.getenv("ASTRA_SMTP_HOST", ""))
    smtp_port: int = field(default_factory=lambda: int(os.getenv("ASTRA_SMTP_PORT", "587")))
    smtp_user: str = field(default_factory=lambda: os.getenv("ASTRA_SMTP_USER", ""))
    smtp_password: str = field(default_factory=lambda: os.getenv("ASTRA_SMTP_PASSWORD", ""))
    smtp_from: str = field(default_factory=lambda: os.getenv("ASTRA_SMTP_FROM", ""))
    smtp_feedback_address: str = field(default_factory=lambda: os.getenv("ASTRA_SMTP_FEEDBACK_ADDRESS", ""))
    secure_cookies: bool = field(default_factory=lambda: os.getenv("ASTRA_ORIGIN", "").startswith("https://"))

    @property
    def db_path(self):
        return self.data_dir / "astra.sqlite3"

    def validate(self):
        if self.player_mode not in {"disabled", "codex", "test"}:
            raise ValueError("ASTRA_PLAYER must be disabled, codex, or test")
        if self.max_workers < 1 or self.max_workers > 16:
            raise ValueError("ASTRA_MAX_WORKERS must be between 1 and 16")
        if self.max_daily_tokens < 1 or self.max_turn_tokens < 1 or self.max_daily_turns < 1:
            raise ValueError("Resource limits must be positive")
        if self.smtp_feedback_address and not is_bare_email(self.smtp_feedback_address):
            raise ValueError("ASTRA_SMTP_FEEDBACK_ADDRESS must be a single bare email address")
        self.data_dir.mkdir(parents=True, exist_ok=True)
