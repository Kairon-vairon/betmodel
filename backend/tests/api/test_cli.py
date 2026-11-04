"""The server commands the owner runs: create-owner, deposit, withdraw, reset-2fa."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from edgewise import cli
from edgewise.auth import totp
from edgewise.config import get_settings
from edgewise.db.base import Base
from edgewise.db.models import AuthSession, Owner
from edgewise.services import portfolio
from tests.conftest import SECRET_KEY

SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"


@pytest.fixture
def database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    url = f"sqlite:///{tmp_path / 'cli.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("APP_SECRET_KEY", SECRET_KEY)
    monkeypatch.setattr(totp, "new_secret", lambda: SECRET)
    get_settings.cache_clear()
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    engine.dispose()
    yield url
    get_settings.cache_clear()


def answers(*replies: str) -> cli.Prompt:
    queue = list(replies)
    return lambda _question: queue.pop(0)


def current_code() -> str:
    return totp.code_at(SECRET, datetime.now(UTC))


def test_create_owner_confirms_the_authenticator_first(
    database: str, capsys: pytest.CaptureFixture[str]
) -> None:
    password = "a long enough password"
    code = current_code()
    result = cli.main(
        ["create-owner", "--username", "Owner@Example.com"],
        prompt=answers("000000", code),  # first code wrong, second right
        secret_prompt=answers(password, password),
    )
    assert result == 0
    out = capsys.readouterr().out
    assert SECRET in out  # shown for manual entry
    assert "That code didn't match" in out
    with Session(create_engine(database)) as session:
        owner = session.scalars(select(Owner)).one()
        assert owner.username == "owner@example.com"
        assert SECRET not in owner.totp_secret_encrypted  # encrypted at rest
    # A second owner is refused.
    assert (
        cli.main(["create-owner", "--username", "x@y.z"], prompt=answers(), secret_prompt=answers())
        == 1
    )


def test_mismatched_passwords_are_asked_again(database: str) -> None:
    code = current_code()
    result = cli.main(
        ["create-owner", "--username", "owner@example.com"],
        prompt=answers(code),
        secret_prompt=answers(
            "first password abc",
            "different one xyz",
            "a long enough password",
            "a long enough password",
        ),
    )
    assert result == 0


def test_weak_password_is_refused(database: str, capsys: pytest.CaptureFixture[str]) -> None:
    result = cli.main(
        ["create-owner", "--username", "owner@example.com"],
        prompt=answers(current_code()),
        secret_prompt=answers("short", "short"),
    )
    assert result == 2
    assert "at least 12 characters" in capsys.readouterr().err


def test_deposit_and_withdraw(database: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["deposit", "$2,000", "--note", "opening bankroll"]) == 0
    assert cli.main(["withdraw", "150"]) == 0
    assert "Bankroll is now $1,850.00." in capsys.readouterr().out
    with Session(create_engine(database)) as session:
        assert str(portfolio.bankroll(session)) == "1850.00"
    with pytest.raises(SystemExit):
        cli.main(["deposit", "abc"])
    assert cli.main(["withdraw", "5000"]) == 2  # more than the bankroll


def test_reset_2fa_signs_out_everywhere(database: str) -> None:
    password = "a long enough password"
    cli.main(
        ["create-owner", "--username", "owner@example.com"],
        prompt=answers(current_code()),
        secret_prompt=answers(password, password),
    )
    engine = create_engine(database)
    with Session(engine) as session:
        owner = session.scalars(select(Owner)).one()
        now = datetime.now(UTC)
        session.add(
            AuthSession(
                owner_id=owner.id,
                token_hash="x" * 64,
                last_seen_at=now,
                expires_at=now.replace(year=2030),
            )
        )
        session.commit()
    assert (
        cli.main(["reset-2fa", "--username", "owner@example.com"], prompt=answers(current_code()))
        == 0
    )
    with Session(engine) as session:
        assert session.scalars(select(AuthSession.revoked_at)).one() is not None
