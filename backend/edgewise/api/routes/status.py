"""Health check, safety limits and a status overview for the dashboard."""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_FLOOR, Decimal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select, text

from edgewise import __version__
from edgewise.api.deps import ClockDep, DbDep, OwnerDep, SettingsDep
from edgewise.db.models import FeedStatus, Signal, WorkerHeartbeat
from edgewise.domain.lifecycle import SignalStatus
from edgewise.domain.limits import DEFAULT_LIMITS
from edgewise.services import limits as limits_service
from edgewise.services import portfolio

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
    last_success_at: datetime | None
    paused: bool
    last_error: str | None


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
    workers: list[WorkerOut]


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
        feeds=[
            FeedOut(
                feed=f.feed,
                last_success_at=f.last_success_at,
                paused=f.paused,
                last_error=f.last_error,
            )
            for f in db.scalars(select(FeedStatus).order_by(FeedStatus.feed))
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
