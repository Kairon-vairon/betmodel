"""Bankroll, peak, exposure and alert pauses: what the safety limits are checked against.

HIGH-RISK CODE (CLAUDE.md rule 4): feeds the stake-sizing and drawdown-stop decisions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from edgewise.db.models import (
    AccountStatus,
    AlertPause,
    BankrollEntry,
    Bet,
    Bookmaker,
    Event,
    LedgerKind,
    PauseReason,
    Signal,
)
from edgewise.domain.finder import BookmakerState, PortfolioState
from edgewise.domain.lifecycle import SignalStatus
from edgewise.domain.limits import SafetyLimits
from edgewise.domain.staking import drawdown_breached
from edgewise.services import audit

CENT = Decimal("0.01")
_LEDGER_LOCK_ID = 7_210_001  # PostgreSQL advisory lock: one ledger writer at a time


def bankroll(session: Session) -> Decimal:
    latest = session.scalar(
        select(BankrollEntry.balance_after).order_by(BankrollEntry.id.desc()).limit(1)
    )
    return latest if latest is not None else Decimal("0.00")


def _lock_ledger(session: Session) -> None:
    if session.get_bind().dialect.name == "postgresql":
        session.execute(select(func.pg_advisory_xact_lock(_LEDGER_LOCK_ID)))


def add_ledger_entry(
    session: Session,
    *,
    kind: LedgerKind,
    amount: Decimal,
    now: datetime,
    actor: str,
    note: str | None = None,
    settlement_id: int | None = None,
) -> BankrollEntry:
    _lock_ledger(session)
    amount = amount.quantize(CENT, ROUND_HALF_UP)
    if kind is LedgerKind.DEPOSIT and amount <= 0:
        raise ValueError("A deposit must be more than $0.")
    if kind is LedgerKind.WITHDRAWAL and amount >= 0:
        raise ValueError("A withdrawal is recorded as a negative amount.")
    balance = bankroll(session) + amount
    if kind is LedgerKind.WITHDRAWAL and balance < 0:
        raise ValueError("You can't withdraw more than the bankroll.")
    entry = BankrollEntry(
        occurred_at=now,
        kind=kind,
        amount=amount,
        balance_after=balance,
        settlement_id=settlement_id,
        note=note,
    )
    session.add(entry)
    session.flush()
    audit.record(
        session,
        actor=actor,
        action=f"bankroll_{kind.value}",
        at=now,
        entity_type="bankroll_ledger",
        entity_id=entry.id,
        amount=amount,
        balance_after=balance,
        note=note,
    )
    return entry


_CASH_FLOWS = frozenset({LedgerKind.DEPOSIT, LedgerKind.WITHDRAWAL})


def peak_since_resume(session: Session) -> Decimal:
    """The bankroll's peak for the drawdown stop, counting betting results only.

    Deposits and withdrawals are not wins or losses, so they move the peak with them: a
    $500 withdrawal lowers the peak by $500 instead of looking like a $500 loss.
    The peak restarts at the current bankroll when the owner resumes alerts after a
    drawdown stop.
    """
    last_resume = session.scalar(
        select(func.max(AlertPause.resumed_at)).where(
            AlertPause.reason == PauseReason.DRAWDOWN_STOP
        )
    )
    entries = session.execute(
        select(
            BankrollEntry.occurred_at,
            BankrollEntry.kind,
            BankrollEntry.amount,
            BankrollEntry.balance_after,
        ).order_by(BankrollEntry.id)
    ).all()
    if not entries:
        return Decimal("0.00")

    cash_in = Decimal(0)  # net deposits minus withdrawals so far
    result = Decimal(0)  # betting result so far: balance minus net cash in
    best: Decimal | None = None  # best betting result since the resume
    at_resume: Decimal | None = None
    balance = Decimal(0)
    for occurred_at, kind, amount, balance in entries:
        if kind in _CASH_FLOWS:
            cash_in += amount
        result = balance - cash_in
        if last_resume is not None and occurred_at <= last_resume:
            at_resume = result
            continue
        best = result if best is None else max(best, result)
    if at_resume is not None:
        best = at_resume if best is None else max(best, at_resume)
    assert best is not None
    return balance + (best - result)


def open_pauses(session: Session) -> list[AlertPause]:
    return list(session.scalars(select(AlertPause).where(AlertPause.resumed_at.is_(None))))


def pause_alerts(
    session: Session, reason: PauseReason, *, now: datetime, actor: str, detail: str | None = None
) -> AlertPause | None:
    """Pause alerts. Returns None if already paused for this reason."""
    if any(p.reason is reason for p in open_pauses(session)):
        return None
    pause = AlertPause(reason=reason, detail=detail, paused_at=now)
    session.add(pause)
    audit.record(session, actor=actor, action="alerts_paused", at=now, reason=reason, detail=detail)
    return pause


def resume_alerts(session: Session, *, now: datetime, actor: str = "owner") -> int:
    """Only the owner resumes alerts. Resuming restarts the drawdown peak from today."""
    pauses = open_pauses(session)
    for pause in pauses:
        pause.resumed_at = now
    if pauses:
        audit.record(
            session,
            actor=actor,
            action="alerts_resumed",
            at=now,
            reasons=[p.reason for p in pauses],
        )
    return len(pauses)


def enforce_drawdown_stop(session: Session, *, now: datetime, limits: SafetyLimits) -> bool:
    """Pause alerts if the bankroll is down the drawdown-stop share from its peak.

    Returns True when this call paused alerts.
    """
    if not drawdown_breached(bankroll(session), peak_since_resume(session), limits):
        return False
    pause = pause_alerts(
        session,
        PauseReason.DRAWDOWN_STOP,
        now=now,
        actor="system",
        detail=f"Bankroll fell {limits.drawdown_stop_fraction:.0%} or more from its peak.",
    )
    return pause is not None


def start_of_owner_day(now: datetime, tz: ZoneInfo) -> datetime:
    local = now.astimezone(tz)
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


def exposure_today(session: Session, *, now: datetime, tz: ZoneInfo) -> Decimal:
    """Stake placed since midnight (owner's time) plus stake awaiting approval."""
    placed = session.scalar(
        select(func.coalesce(func.sum(Bet.stake), 0)).where(
            Bet.placed_at >= start_of_owner_day(now, tz)
        )
    )
    awaiting = session.scalar(
        select(func.coalesce(func.sum(Signal.suggested_stake), 0)).where(
            Signal.status == SignalStatus.AWAITING
        )
    )
    return (Decimal(placed or 0) + Decimal(awaiting or 0)).quantize(CENT, ROUND_HALF_UP)


def bookmaker_states(session: Session) -> dict[int, BookmakerState]:
    usable = {AccountStatus.ACTIVE, AccountStatus.LIMITED}
    return {
        b.id: BookmakerState(available=b.account_status in usable, stake_limit=b.stake_limit)
        for b in session.scalars(select(Bookmaker))
    }


_OPEN = (SignalStatus.AWAITING, SignalStatus.PLACED)


def portfolio_state(session: Session, *, now: datetime, tz: ZoneInfo) -> PortfolioState:
    per_event: dict[int, int] = {
        event_id: count
        for event_id, count in session.execute(
            select(Signal.event_id, func.count())
            .where(Signal.status.in_(_OPEN))
            .group_by(Signal.event_id)
        )
    }
    selections = frozenset(
        session.scalars(select(Signal.selection_id).where(Signal.status.in_(_OPEN)))
    )
    allowed = frozenset(session.scalars(select(Event.id).where(Event.allow_extra_bets.is_(True))))
    return PortfolioState(
        bankroll=bankroll(session),
        peak_bankroll=peak_since_resume(session),
        alerts_paused=bool(open_pauses(session)),
        exposure_today=exposure_today(session, now=now, tz=tz),
        bookmakers=bookmaker_states(session),
        bets_per_event=per_event,
        selections_with_bets=selections,
        extra_bets_allowed=allowed,
    )
