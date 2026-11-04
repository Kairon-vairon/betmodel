"""Settings, read from environment variables only (CLAUDE.md rule 5: no secrets in the repo)."""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PLACEHOLDER_SECRETS = {"", "change-me", "changeme", "secret"}


class Stack(StrEnum):
    LIVE = "live"
    LAB = "lab"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False)

    app_env: Stack = Stack.LIVE
    app_secret_key: SecretStr = Field(
        description="Long random string. Encrypts 2FA secrets. Generate with: openssl rand -hex 32"
    )
    database_url: str = "postgresql+psycopg://edgewise:edgewise@localhost:5432/edgewise"
    # The owner's time zone: used for "today" in daily exposure and quiet hours.
    tz: str = "Australia/Sydney"

    # Login sessions
    session_max_age_hours: int = Field(default=168, ge=1)  # 7 days, then log in again
    session_idle_hours: int = Field(default=72, ge=1)  # or after 3 days without use
    cookie_secure: bool = True  # only set False for local development over plain http
    login_max_failures: int = Field(default=5, ge=1)
    login_lockout_minutes: int = Field(default=15, ge=1)

    # Alerts (Milestone 4). The lab stack can never send them, whatever this says.
    alerts_enabled: bool = True

    # Data feeds (Milestone 2)
    odds_api_key: SecretStr | None = None
    football_data_api_key: SecretStr | None = None
    betfair_app_key: SecretStr | None = None
    betfair_username: str | None = None
    betfair_password: SecretStr | None = None
    betfair_cert_path: str | None = None

    @model_validator(mode="after")
    def _check_secret_key(self) -> Settings:
        key = self.app_secret_key.get_secret_value()
        if key.strip().lower() in _PLACEHOLDER_SECRETS or len(key) < 32:
            raise ValueError(
                "APP_SECRET_KEY must be a random string of at least 32 characters "
                "(generate one with: openssl rand -hex 32)"
            )
        ZoneInfo(self.tz)  # fail fast on a typo in TZ
        return self

    @property
    def is_lab(self) -> bool:
        return self.app_env is Stack.LAB

    @property
    def can_send_alerts(self) -> bool:
        """Hard guard: the lab stack never sends alerts (RELEASE_PROCESS.md)."""
        return self.app_env is Stack.LIVE and self.alerts_enabled

    @property
    def owner_tz(self) -> ZoneInfo:
        return ZoneInfo(self.tz)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # values come from the environment
