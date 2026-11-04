"""Storing suggestions and the owner's decisions on them.

Nothing here places a bet. "Placed" records what the owner did themselves at the
bookmaker (CLAUDE.md rules 1 and 2).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from edgewise.db.models import (
    Bet,
    Event,
    LatestFairPrice,
    LatestPrice,
    PriceSide,
    PriceSource,
    Signal,
)
from edgewise.domain.finder import FinderResult
from edgewise.domain.freshness import DEFAULT_FRESHNESS, FreshnessPolicy
from edgewise.domain.lifecycle import (
    OpenSignal,
    SignalStatus,
    can_undo,
    check_placement,
    check_transition,
    expiry_reason,
)
from edgewise.domain.limits import SafetyLimits
from edgewise.services import audit
from edgewise.services.portfolio import open_pauses


class SignalError(ValueError):
    pass


def record_suggestions(
    session: Session, result: FinderResult, *, now: datetime, bankroll: Decimal
) -> list[Signal]:
    signals: list[Signal] = []
    for s in result.suggestions:
        c = s.candidate
        signal = Signal(
            event_id=c.event_id,
            selection_id=c.selection_id,
            bookmaker_id=c.bookmaker_id,
            offered_odds=c.offered_odds,
            offered_at=c.offered_at,
            fair_prob=c.fair_prob,
            edge=s.edge,
            kelly_stake=s.kelly_stake,
            suggested_stake=s.stake,
            capped_by=s.capped_by,
            min_odds=s.min_odds,
            bankroll_at_signal=bankroll,
            reason=s.reason,
            strategy_version=s.strategy_version,
            status=SignalStatus.AWAITING,
            created_at=now,
            expires_at=s.expires_at,
        )
        session.add(signal)
        signals.append(signal)
    session.flush()
    for signal in signals:
        audit.record(
            session,
            actor="worker",
            action="signal_created",
            at=now,
            entity_type="signal",
            entity_id=signal.id,
            edge=signal.edge,
            stake=signal.suggested_stake,
        )
    return signals


def _get(session: Session, signal_id: int) -> Signal:
    signal = session.get(Signal, signal_id, with_for_update=True)
    if signal is None:
        raise SignalError("That bet doesn't exist.")
    return signal


def mark_placed(
    session: Session,
    signal_id: int,
    *,
    odds_taken: Decimal,
    stake: Decimal,
    now: datetime,
    notes: str | None = None,
) -> Bet:
    """The owner placed the bet at the bookmaker. Record exactly what they got."""
    signal = _get(session, signal_id)
    if signal.status is not SignalStatus.AWAITING:
        raise SignalError(f"This bet is already {signal.status.value}.")
    check_transition(signal.status, SignalStatus.PLACED)
    warnings = check_placement(
        odds_taken=odds_taken,
        stake=stake,
        min_odds=signal.min_odds,
        suggested_stake=signal.suggested_stake,
    )
    signal.status = SignalStatus.PLACED
    signal.decided_at = now
    bet = Bet(
        signal_id=signal.id,
        bookmaker_id=signal.bookmaker_id,
        odds_taken=odds_taken,
        stake=stake,
        placed_at=now,
        warnings=[w.value for w in warnings],
        notes=notes,
    )
    session.add(bet)
    session.flush()
    audit.record(
        session,
        actor="owner",
        action="signal_placed",
        at=now,
        entity_type="signal",
        entity_id=signal.id,
        odds_taken=odds_taken,
        stake=stake,
        warnings=warnings,
    )
    return bet


def mark_skipped(
    session: Session, signal_id: int, *, now: datetime, reason: str | None = None
) -> Signal:
    signal = _get(session, signal_id)
    if signal.status is not SignalStatus.AWAITING:
        raise SignalError(f"This bet is already {signal.status.value}.")
    check_transition(signal.status, SignalStatus.SKIPPED)
    signal.status = SignalStatus.SKIPPED
    signal.decided_at = now
    signal.skip_reason = reason
    audit.record(
        session,
        actor="owner",
        action="signal_skipped",
        at=now,
        entity_type="signal",
        entity_id=signal.id,
        reason=reason,
    )
    return signal


def undo_decision(session: Session, signal_id: int, *, now: datetime, settled: bool) -> Signal:
    """Undo a mistaken Placed/Skipped tap within a few minutes, before kick-off."""
    signal = _get(session, signal_id)
    kickoff = session.scalar(select(Event.kickoff_at).where(Event.id == signal.event_id))
    assert kickoff is not None
    if not can_undo(
        signal.status, decided_at=signal.decided_at, now=now, kickoff=kickoff, settled=settled
    ):
        raise SignalError("This can no longer be undone.")
    clash = session.scalar(
        select(Signal.id).where(
            Signal.selection_id == signal.selection_id,
            Signal.status == SignalStatus.AWAITING,
            Signal.id != signal.id,
        )
    )
    if clash is not None:
        raise SignalError("A newer suggestion for this selection is already waiting.")
    previous = signal.status
    if previous is SignalStatus.PLACED and signal.bet is not None:
        session.delete(signal.bet)
    signal.status = SignalStatus.AWAITING
    signal.decided_at = None
    signal.skip_reason = None
    audit.record(
        session,
        actor="owner",
        action="signal_undone",
        at=now,
        entity_type="signal",
        entity_id=signal.id,
        previous=previous,
    )
    return signal


def latest_bookmaker_price(
    session: Session, selection_id: int, bookmaker_id: int
) -> tuple[Decimal, datetime] | None:
    """The bookmaker's current price and when the feed last confirmed it."""
    row = session.execute(
        select(LatestPrice.odds, LatestPrice.last_seen_at).where(
            LatestPrice.selection_id == selection_id,
            LatestPrice.source == PriceSource.ODDS_FEED,
            LatestPrice.bookmaker_id == bookmaker_id,
            LatestPrice.side == PriceSide.BACK,
        )
    ).first()
    return (row[0], row[1]) if row else None


def latest_fair_price(session: Session, selection_id: int) -> tuple[float, datetime] | None:
    """The current fair probability and when the exchange last confirmed it."""
    row = session.execute(
        select(LatestFairPrice.fair_prob, LatestFairPrice.as_of).where(
            LatestFairPrice.selection_id == selection_id
        )
    ).first()
    return (row[0], row[1]) if row else None


def expire_due(
    session: Session,
    *,
    now: datetime,
    limits: SafetyLimits,
    freshness: FreshnessPolicy = DEFAULT_FRESHNESS,
) -> list[Signal]:
    """Expire awaiting signals whose window ended or whose value is gone."""
    paused = bool(open_pauses(session))
    rows = session.execute(
        select(Signal, Event.kickoff_at)
        .join(Event, Event.id == Signal.event_id)
        .where(Signal.status == SignalStatus.AWAITING)
        .with_for_update(of=Signal)
    ).all()
    expired: list[Signal] = []
    for signal, kickoff in rows:
        odds: Decimal | None = None
        price = latest_bookmaker_price(session, signal.selection_id, signal.bookmaker_id)
        if price is not None and freshness.bookmaker_fresh(price[1], now, kickoff):
            odds = price[0]
        prob: float | None = None
        fair = latest_fair_price(session, signal.selection_id)
        if fair is not None and freshness.exchange_fresh(fair[1], now, kickoff):
            prob = fair[0]
        reason = expiry_reason(
            OpenSignal(signal.status, signal.expires_at, kickoff, signal.min_odds),
            now=now,
            current_odds=odds,
            current_fair_prob=prob,
            alerts_paused=paused,
            limits=limits,
        )
        if reason is None:
            continue
        check_transition(signal.status, SignalStatus.EXPIRED)
        signal.status = SignalStatus.EXPIRED
        signal.expiry_reason = reason
        signal.decided_at = now
        audit.record(
            session,
            actor="worker",
            action="signal_expired",
            at=now,
            entity_type="signal",
            entity_id=signal.id,
            reason=reason,
            current_odds=odds,
            current_fair_prob=prob,
        )
        expired.append(signal)
    return expired
