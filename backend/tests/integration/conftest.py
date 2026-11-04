"""PostgreSQL fixtures. Set TEST_DATABASE_URL to an empty, disposable database.

The schema is rebuilt from the Alembic migrations at the start of the run, and every
test runs inside a transaction that is rolled back afterwards.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

BACKEND = Path(__file__).resolve().parents[2]


def alembic_config(url: str) -> Config:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    config.set_main_option("sqlalchemy.url", url)
    return config


@pytest.fixture(scope="session")
def pg_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set: skipping PostgreSQL integration tests")
    return url


@pytest.fixture(scope="session")
def pg_engine(pg_url: str) -> Iterator[Engine]:
    engine = create_engine(pg_url)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    command.upgrade(alembic_config(pg_url), "head")
    yield engine
    engine.dispose()


@pytest.fixture
def pg_connection(pg_engine: Engine) -> Iterator[Connection]:
    connection = pg_engine.connect()
    outer = connection.begin()
    yield connection
    outer.rollback()
    connection.close()


@pytest.fixture
def pg_factory(pg_connection: Connection) -> sessionmaker[Session]:
    # Commits inside the code under test only release savepoints; the test's outer
    # transaction is rolled back at the end.
    return sessionmaker(
        bind=pg_connection, join_transaction_mode="create_savepoint", expire_on_commit=False
    )


@pytest.fixture
def pg(pg_factory: sessionmaker[Session]) -> Iterator[Session]:
    with pg_factory() as session:
        yield session
