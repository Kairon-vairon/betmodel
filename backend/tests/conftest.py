"""Shared fixtures. Fast tests use in-memory SQLite; integration tests use PostgreSQL."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from edgewise.api.main import create_app
from edgewise.auth import totp
from edgewise.config import Settings
from edgewise.db import models  # noqa: F401  (registers tables)
from edgewise.db.base import Base
from edgewise.db.session import make_session_factory, transaction
from edgewise.services import auth as auth_service

SECRET_KEY = "test-secret-key-0123456789abcdef0123456789"
PASSWORD = "correct horse battery staple"
USERNAME = "owner@example.com"


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> None:
        self.now += timedelta(**kwargs)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(datetime(2026, 11, 7, 9, 0, 0, tzinfo=UTC))  # 8pm Sydney (AEDT)


@pytest.fixture
def settings() -> Settings:
    return Settings(app_secret_key=SECRET_KEY, database_url="sqlite://", cookie_secure=True)


def _sqlite_engine() -> Engine:
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )

    @event.listens_for(engine, "connect")
    def _foreign_keys(dbapi_conn: Any, _: Any) -> None:
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def session_factory() -> Iterator[sessionmaker[Session]]:
    engine = _sqlite_engine()
    yield make_session_factory(engine)
    engine.dispose()


@pytest.fixture
def db(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    with session_factory() as session:
        yield session


@dataclass
class OwnerLogin:
    username: str
    password: str
    secret: str

    def code(self, at: datetime) -> str:
        return totp.code_at(self.secret, at)


@pytest.fixture
def owner(
    session_factory: sessionmaker[Session], settings: Settings, clock: FakeClock
) -> OwnerLogin:
    secret = totp.new_secret()
    with transaction(session_factory) as session:
        auth_service.create_owner(
            session,
            settings,
            username=USERNAME,
            password=PASSWORD,
            totp_secret=secret,
            now=clock(),
        )
    return OwnerLogin(USERNAME, PASSWORD, secret)


@pytest.fixture
def client(
    settings: Settings, session_factory: sessionmaker[Session], clock: FakeClock
) -> Iterator[TestClient]:
    app = create_app(settings, session_factory, clock)
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client
