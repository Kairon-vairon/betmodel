"""Current safety limits: code defaults plus the owner's stored changes.

HIGH-RISK CODE (CLAUDE.md rule 4).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from edgewise.db.models import LimitSetting
from edgewise.domain.limits import BOUNDS, DEFAULT_LIMITS, SafetyLimits
from edgewise.services import audit


def stored_overrides(session: Session) -> dict[str, Decimal]:
    latest = (
        select(LimitSetting.name, func.max(LimitSetting.id).label("id"))
        .group_by(LimitSetting.name)
        .subquery()
    )
    rows = session.execute(
        select(LimitSetting.name, LimitSetting.value).join(latest, LimitSetting.id == latest.c.id)
    )
    return {name: value for name, value in rows}


def current_limits(session: Session) -> SafetyLimits:
    """Raises ValueError if the stored values don't make a valid set: fail closed."""
    return DEFAULT_LIMITS.with_overrides(stored_overrides(session))


def set_limit(
    session: Session,
    name: str,
    value: Decimal,
    *,
    changed_by: str,
    now: datetime,
    reason: str | None = None,
) -> SafetyLimits:
    """Store a new value for one limit after checking the whole set is still valid."""
    if name not in BOUNDS:
        raise ValueError(f"unknown limit: {name}")
    before = current_limits(session)
    after = DEFAULT_LIMITS.with_overrides({**stored_overrides(session), name: value})
    session.add(
        LimitSetting(
            name=name, value=value, effective_from=now, changed_by=changed_by, reason=reason
        )
    )
    audit.record(
        session,
        actor=changed_by,
        action="limit_changed",
        at=now,
        entity_type="limit",
        entity_id=name,
        old=before.as_numbers()[name],
        new=value,
        reason=reason,
    )
    return after
