"""Declarative base and column types shared by every table."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = sa.MetaData(naming_convention=NAMING_CONVENTION)


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """Timezone-aware datetimes, always stored and returned in UTC.

    Naive datetimes are refused: a time without a zone is a bug waiting to happen when
    kick-offs are in Europe and the owner is in Sydney.
    """

    impl = sa.DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: sa.Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime: attach a time zone (use UTC)")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: sa.Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:  # SQLite (tests only) drops the zone; values are UTC
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


def str_enum(enum_cls: type[StrEnum], name: str) -> sa.Enum:
    """Store an enum as text with a CHECK constraint (no PostgreSQL enum types to migrate)."""
    return sa.Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=32,
        values_callable=lambda members: [m.value for m in members],
        validate_strings=True,
    )


JSONType: Any = sa.JSON().with_variant(JSONB(), "postgresql")
BigID: Any = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
Money = sa.Numeric(12, 2)
Odds = sa.Numeric(8, 3)
Ratio = sa.Numeric(9, 6)
Probability: sa.Double[float] = sa.Double()
