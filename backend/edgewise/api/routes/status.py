"""Health check, safety limits and a status overview for the dashboard."""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_FLOOR, Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from edgewise import __version__
from edgewise.api.deps import ClockDep, DbDep, OwnerDep, SettingsDep
from edgewise.config import Settings
from edgewise.db.models import FeedStatus, Notification, Signal, WorkerHeartbeat
from edgewise.domain.lifecycle import SignalStatus
from edgewise.domain.limits import DEFAULT_LIMITS
from edgewise.services import limits as limits_service
from edgewise.services import portfolio
from edgewise.services.feeds import BETFAIR, FEED_NAMES, FEEDS, FIXTURES, ODDS

router = APIRouter(prefix="/api", tags=["status"])


class Health(BaseModel):
    status: str
    stack: str
    version: str


@router.get("/health", response_model=Health)
def health(settings: SettingsDep, db: DbDep) -> Health:
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Database unavailable") from exc
    return Health(status="ok", stack=settings.app_env.value, version=__version__)


class LimitOut(BaseModel):
    name: str
    value: Decimal
    default: Decimal
    changed: bool


class LimitsOut(BaseModel):
    limits: list[LimitOut]
    valid: bool  # False if stored values don't form a valid set: no bets are suggested


@router.get("/limits", response_model=LimitsOut)
def get_limits(_: OwnerDep, db: DbDep) -> LimitsOut:
    defaults = DEFAULT_LIMITS.as_numbers()
    try:
        current = limits_service.current_limits(db).as_numbers()
        valid = True
    except ValueError:
        current, valid = defaults, False
    return LimitsOut(
        limits=[
            LimitOut(
                name=name, value=current[name], default=default, changed=current[name] != default
            )
            for name, default in defaults.items()
        ],
        valid=valid,
    )


class FeedOut(BaseModel):
    feed: str
    name: str
    # not_configured (no key) / waiting (no reply yet) / ok / paused
    state: str
    last_success_at: datetime | None
    paused: bool
    last_error: str | None
    details: dict[str, Any]


class NoticeOut(BaseModel):
    created_at: datetime
    kind: str
    title: str
    body: str


class WorkerOut(BaseModel):
    worker: str
    last_beat_at: datetime
    healthy: bool


class Overview(BaseModel):
    stack: str
    bankroll: Decimal
    peak_bankroll: Decimal
    exposure_today: Decimal
    daily_exposure_limit: Decimal
    max_stake: Decimal
    alerts_paused: bool
    pause_reasons: list[str]
    awaiting_approval: int
    feeds: list[FeedOut]
    notices: list[NoticeOut]
    workers: list[WorkerOut]


def _feeds(db: Session, settings: Settings) -> list[FeedOut]:
    configured = {
        FIXTURES: bool(settings.football_data_api_key),
        ODDS: bool(settings.odds_api_key),
        BETFAIR: settings.betfair_configured,
    }
    rows = {f.feed: f for f in db.scalars(select(FeedStatus))}
    out: list[FeedOut] = []
    for feed in FEEDS:
        row = rows.get(feed)
        if not configured[feed]:
            state = "not_configured"
        elif row is not None and row.paused:
            state = "paused"
        elif row is not None and row.last_success_at is not None:
            state = "ok"
        else:
            state = "waiting"
        out.append(
            FeedOut(
                feed=feed,
                name=FEED_NAMES[feed],
                state=state,
                last_success_at=row.last_success_at if row else None,
                paused=bool(row and row.paused),
                last_error=row.last_error if row else None,
                details=dict(row.details or {}) if row else {},
            )
        )
    return out


@router.get("/overview", response_model=Overview)
def overview(_: OwnerDep, settings: SettingsDep, clock: ClockDep, db: DbDep) -> Overview:
    now = clock()
    try:
        limits = limits_service.current_limits(db)
    except ValueError:
        limits = DEFAULT_LIMITS
    bank = portfolio.bankroll(db)
    pauses = portfolio.open_pauses(db)
    awaiting = db.scalar(
        select(func.count()).select_from(Signal).where(Signal.status == SignalStatus.AWAITING)
    )
    return Overview(
        stack=settings.app_env.value,
        bankroll=bank,
        peak_bankroll=portfolio.peak_since_resume(db),
        exposure_today=portfolio.exposure_today(db, now=now, tz=settings.owner_tz),
        daily_exposure_limit=(bank * limits.max_daily_exposure_fraction).quantize(Decimal("0.01")),
        max_stake=(bank * limits.max_stake_fraction).quantize(Decimal("1"), rounding=ROUND_FLOOR),
        alerts_paused=bool(pauses),
        pause_reasons=[p.reason.value for p in pauses],
        awaiting_approval=awaiting or 0,
        feeds=_feeds(db, settings),
        notices=[
            NoticeOut(created_at=n.created_at, kind=n.kind, title=n.title, body=n.body)
            for n in db.scalars(
                select(Notification).order_by(Notification.created_at.desc()).limit(5)
            )
        ],
        workers=[
            WorkerOut(
                worker=w.worker,
                last_beat_at=w.last_beat_at,
                healthy=(now - w.last_beat_at).total_seconds() < 120,
            )
            for w in db.scalars(select(WorkerHeartbeat).order_by(WorkerHeartbeat.worker))
        ],
    )
