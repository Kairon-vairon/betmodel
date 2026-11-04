"""Audit log: every owner action and every automated change (append-only table)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from edgewise.db.models import AuditEntry


def record(
    session: Session,
    *,
    actor: str,
    action: str,
    at: datetime,
    entity_type: str | None = None,
    entity_id: object | None = None,
    **details: Any,
) -> AuditEntry:
    entry = AuditEntry(
        occurred_at=at,
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=None if entity_id is None else str(entity_id),
        details={k: _jsonable(v) for k, v in details.items()},
    )
    session.add(entry)
    return entry


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_jsonable(v) for v in value]
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")  # 0.040000 -> "0.04"
    return str(value)  # Decimal, datetime, enums
