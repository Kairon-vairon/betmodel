"""Settings, read from environment variables only (CLAUDE.md rule 5: no secrets in the repo)."""

from __future__ import annotations

import os
import secrets
import time
from decimal import Decimal
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from edgewise.domain.pricing import MarginMethod

_PLACEHOLDER_SECRETS = {"", "change-me", "changeme", "secret"}


class Stack(StrEnum):
    LIVE = "live"
    LAB = "lab"


def load_or_create_secret_key(path: Path) -> str:
    """Read the secret key from `path`, creating it on first use (owner-only, 64 hex chars).

    Safe when the API and worker start at the same time: only one of them creates it.
    """
    if not path.parent.is_dir():
        raise ValueError(f"The folder for APP_SECRET_KEY_FILE does not exist: {path.parent}")
    for _ in range(50):
        try:
            key = path.read_text().strip()
        except FileNotFoundError:
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                continue  # another process is creating it right now
            with os.fdopen(fd, "w") as handle:
                handle.write(secrets.token_hex(32) + "\n")
            continue  # read back what was written
        if key:
            return key
        time.sleep(0.1)  # created by another process but not written yet
    raise ValueError(f"Could not read the secret key from {path}")


class Settings(BaseSettings):
    # Empty values (e.g. "ODDS_API_KEY=" in the env file) count as not set.
    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False, env_ignore_empty=True)

    app_env: Stack = Stack.LIVE
    # Encrypts the 2FA secret. Either give it directly (APP_SECRET_KEY, e.g. from
    # `openssl rand -hex 32`) or point APP_SECRET_KEY_FILE at a file, which is created
    # with a random key on first start (Docker keeps it in the app-secrets volume).
    app_secret_key: SecretStr
    app_secret_key_file: Path | None = None
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

    # Data feeds (Milestone 2). A feed runs only when its keys are set.
    odds_api_key: SecretStr | None = None  # the-odds-api.com
    odds_api_regions: str = "au"
    odds_api_url: str = "https://api.the-odds-api.com/v4"
    football_data_api_key: SecretStr | None = None  # api-football.com
    api_football_url: str = "https://v3.football.api-sports.io"
    betfair_app_key: SecretStr | None = None
    betfair_username: str | None = None
    betfair_password: SecretStr | None = None
    betfair_cert_path: str | None = None  # folder with one .crt and one .key (optional)
    betfair_identity_url: str = "https://identitysso.betfair.com.au/api"
    betfair_cert_identity_url: str = "https://identitysso-cert.betfair.com.au/api"
    betfair_betting_url: str = "https://api.betfair.com/exchange/betting/rest/v1.0"
    # How far ahead to collect matches and prices.
    feed_horizon_days: int = Field(default=7, ge=1, le=14)
    # Fair price method (docs/ARCHITECTURE.md): multiplicative baseline, max back/lay gap.
    fair_price_method: MarginMethod = MarginMethod.MULTIPLICATIVE
    fair_price_max_spread: Decimal = Decimal("0.05")

    @property
    def betfair_configured(self) -> bool:
        return bool(self.betfair_app_key and self.betfair_username and self.betfair_password)

    @model_validator(mode="before")
    @classmethod
    def _secret_key_from_file(cls, data: Any) -> Any:
        if isinstance(data, dict) and not data.get("app_secret_key"):
            path = data.get("app_secret_key_file")
            if not path:
                raise ValueError(
                    "Set APP_SECRET_KEY (generate one with: openssl rand -hex 32), "
                    "or APP_SECRET_KEY_FILE to have one created automatically"
                )
            data = {**data, "app_secret_key": load_or_create_secret_key(Path(path))}
        return data

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
