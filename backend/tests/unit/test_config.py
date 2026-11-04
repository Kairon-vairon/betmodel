"""Settings: the secret key can come from the environment or a file created on first start."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
from pydantic import ValidationError

from edgewise.config import Settings, Stack, load_or_create_secret_key

KEY = "k" * 16 + "0123456789abcdef0123456789abcdef"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("APP_SECRET_KEY", "APP_SECRET_KEY_FILE", "APP_ENV"):
        monkeypatch.delenv(name, raising=False)


def test_key_from_the_environment_wins_over_the_file(tmp_path: Path) -> None:
    key_file = tmp_path / "app_secret_key"
    settings = Settings(app_secret_key=KEY, app_secret_key_file=key_file)
    assert settings.app_secret_key.get_secret_value() == KEY
    assert not key_file.exists()


def test_key_file_is_created_once_then_reused(tmp_path: Path) -> None:
    key_file = tmp_path / "app_secret_key"
    first = Settings(app_secret_key_file=key_file).app_secret_key.get_secret_value()
    second = Settings(app_secret_key_file=key_file).app_secret_key.get_secret_value()
    assert first == second
    assert len(first) == 64 and int(first, 16) >= 0
    assert stat.S_IMODE(os.stat(key_file).st_mode) == 0o600  # only the app can read it


def test_empty_value_in_env_file_falls_back_to_the_key_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key_file = tmp_path / "app_secret_key"
    monkeypatch.setenv("APP_SECRET_KEY", "")  # what "APP_SECRET_KEY=" in .env gives
    monkeypatch.setenv("APP_SECRET_KEY_FILE", str(key_file))
    assert len(Settings().app_secret_key.get_secret_value()) == 64
    assert key_file.exists()


def test_no_key_anywhere_is_a_clear_error() -> None:
    with pytest.raises(ValidationError, match="Set APP_SECRET_KEY"):
        Settings()


def test_weak_keys_are_refused(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="at least 32 characters"):
        Settings(app_secret_key="change-me")
    weak = tmp_path / "weak"
    weak.write_text("short\n")
    with pytest.raises(ValidationError, match="at least 32 characters"):
        Settings(app_secret_key_file=weak)


def test_missing_folder_is_a_clear_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="folder for APP_SECRET_KEY_FILE does not exist"):
        load_or_create_secret_key(tmp_path / "missing" / "app_secret_key")


def test_a_file_created_by_another_process_is_read_not_replaced(tmp_path: Path) -> None:
    key_file = tmp_path / "app_secret_key"
    key_file.write_text(KEY + "\n")
    assert load_or_create_secret_key(key_file) == KEY


def test_lab_never_sends_alerts() -> None:
    assert Settings(app_secret_key=KEY).can_send_alerts is True
    lab = Settings(app_secret_key=KEY, app_env=Stack.LAB, alerts_enabled=True)
    assert lab.can_send_alerts is False
