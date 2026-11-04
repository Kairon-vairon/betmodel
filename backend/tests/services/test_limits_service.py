"""Stored limit changes. HIGH-RISK."""

from __future__ import annotations

from decimal import Decimal as D

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from edgewise.db.models import AuditEntry, LimitSetting
from edgewise.services import limits as limits_service
from tests.conftest import FakeClock


def test_defaults_when_nothing_stored(db: Session) -> None:
    assert limits_service.current_limits(db).max_stake_fraction == D("0.02")


def test_latest_change_wins_and_is_audited(db: Session, clock: FakeClock) -> None:
    limits_service.set_limit(db, "min_edge", D("0.04"), changed_by="owner", now=clock())
    clock.advance(minutes=1)
    limits_service.set_limit(
        db, "min_edge", D("0.035"), changed_by="owner", now=clock(), reason="draws need more"
    )
    db.flush()
    assert limits_service.current_limits(db).min_edge == D("0.035")
    entry = db.scalar(select(AuditEntry).order_by(AuditEntry.id.desc()).limit(1))
    assert entry is not None and entry.action == "limit_changed"
    assert entry.details == {"old": "0.04", "new": "0.035", "reason": "draws need more"}


def test_invalid_changes_are_refused_before_saving(db: Session, clock: FakeClock) -> None:
    with pytest.raises(ValueError):
        limits_service.set_limit(
            db, "max_stake_fraction", D("0.2"), changed_by="owner", now=clock()
        )
    with pytest.raises(ValueError):  # would put min odds above max odds
        limits_service.set_limit(db, "min_odds", D("7"), changed_by="owner", now=clock())
    with pytest.raises(ValueError, match="unknown"):
        limits_service.set_limit(db, "stake", D("1"), changed_by="owner", now=clock())
    assert db.scalar(select(LimitSetting)) is None
