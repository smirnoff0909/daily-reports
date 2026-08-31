import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo


def _flag(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql+psycopg://reports:reports@db:5432/reports"
    )
    secret_key: str = os.getenv("SECRET_KEY", "dev-only-change-me")
    timezone: str = os.getenv("APP_TIMEZONE", "Europe/Moscow")
    edit_window_days: int = int(os.getenv("EDIT_WINDOW_DAYS", "3"))
    hours_soft_limit: float = float(os.getenv("HOURS_SOFT_LIMIT", "12"))
    hours_hard_limit: float = float(os.getenv("HOURS_HARD_LIMIT", "24"))
    session_max_age: int = int(os.getenv("SESSION_MAX_AGE", str(12 * 60 * 60)))
    cookie_secure: bool = _flag("COOKIE_SECURE", "true")
    app_name: str = os.getenv("APP_NAME", "Отчёты")

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


settings = Settings()
