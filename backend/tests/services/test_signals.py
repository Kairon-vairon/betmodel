"""Signal lifecycle against the database: create, place, skip, undo, expire."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal as D
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from edgewise.db.models import AuditEntry, Bet, LedgerKind, PauseReason, Signal
from edgewise.domain.finder import find_value
from edgewise.domain.lifecycle import ExpiryReason, SignalStatus
from edgewise.domain.limits import DEFAULT_LIMITS
from edgewise.domain.markets import Selection
from edgewise.services import portfolio, signals
from tests.conftest import FakeClock
from tests.factories import (
    add_book_price,
    add_fair_price,
    candidate_for,
    make_bookmaker,
    make_match,
)

SYDNEY = ZoneInfo("Australia/Sydney")


@pytest.fixture
def setup(db: Session, clock: FakeClock) -> tuple[Signal, int]:
    portfolio.add_ledger_entry(
        db, kind=LedgerKind.DEPOSIT, amount=D("2186.90"), now=clock(), actor="owner"
    )
    book = make_bookmaker(db)
    event, sel = make_match(db, kickoff=clock() + timedelta(hours=8))
    now = clock()
    state = portfolio.portfolio_state(db, now=now, tz=SYDNEY)
    result = find_value([candidate_for(event, sel[Selection.HOME], book.id, now)], state, now=now)
    (signal,) = signals.record_suggestions(db, result, now=now, bankroll=state.bankroll)
    return signal, book.id


def test_suggestion_is_stored_with_everything_needed(
    setup: tuple[Signal, int], db: Session, clock: FakeClock
) -> None:
    signal, _ = setup
    stored = db.get(Signal, signal.id)
    assert stored is not None
    assert stored.status is SignalStatus.AWAITING
    assert stored.suggested_stake == D("33")
    assert stored.min_odds == D("1.89")
    assert stored.edge == D("0.0569")
    assert stored.bankroll_at_signal == D("2186.90")
    assert stored.expires_at == clock() + timedelta(minutes=60)
    assert stored.strategy_version == "reference-price-v1"
    assert "Sportsbet pays 1.95" in stored.reason


def test_place_then_no_second_decision(
    setup: tuple[Signal, int], db: Session, clock: FakeClock
) -> None:
    signal, _ = setup
    bet = signals.mark_placed(db, signal.id, odds_taken=D("1.95"), stake=D("33"), now=clock())
    assert bet.warnings == []
    assert signal.status is SignalStatus.PLACED
    with pytest.raises(signals.SignalError, match="already placed"):
        signals.mark_skipped(db, signal.id, now=clock())
    with pytest.raises(ValueError):
        signals.mark_placed(db, signal.id, odds_taken=D("1.95"), stake=D("33"), now=clock())


def test_skip_and_undo(setup: tuple[Signal, int], db: Session, clock: FakeClock) -> None:
    signal, _ = setup
    signals.mark_skipped(db, signal.id, now=clock(), reason="price gone")
    assert signal.skip_reason == "price gone"
    clock.advance(minutes=5)
    signals.undo_decision(db, signal.id, now=clock(), settled=False)
    assert signal.status is SignalStatus.AWAITING
    assert signal.skip_reason is None


def test_undo_placed_removes_the_bet_within_the_window(
    setup: tuple[Signal, int], db: Session, clock: FakeClock
) -> None:
    signal, _ = setup
    signals.mark_placed(db, signal.id, odds_taken=D("1.95"), stake=D("33"), now=clock())
    db.flush()
    signals.undo_decision(db, signal.id, now=clock() + timedelta(minutes=9), settled=False)
    db.flush()
    assert db.scalar(select(Bet)) is None
    signals.mark_placed(db, signal.id, odds_taken=D("1.95"), stake=D("33"), now=clock())
    with pytest.raises(signals.SignalError, match="no longer be undone"):
        signals.undo_decision(db, signal.id, now=clock() + timedelta(minutes=11), settled=False)


def test_expires_when_the_window_ends(
    setup: tuple[Signal, int], db: Session, clock: FakeClock
) -> None:
    signal, _ = setup
    clock.advance(minutes=59)
    assert signals.expire_due(db, now=clock(), limits=DEFAULT_LIMITS) == []
    clock.advance(minutes=1)
    assert signals.expire_due(db, now=clock(), limits=DEFAULT_LIMITS) == [signal]
    assert signal.status is SignalStatus.EXPIRED
    assert signal.expiry_reason is ExpiryReason.APPROVAL_WINDOW
    action = db.scalar(select(AuditEntry.action).order_by(AuditEntry.id.desc()).limit(1))
    assert action == "signal_expired"


def test_expires_when_a_fresh_price_drops_below_minimum(
    setup: tuple[Signal, int], db: Session, clock: FakeClock
) -> None:
    signal, book_id = setup
    clock.advance(minutes=10)
    add_book_price(db, signal.selection_id, book_id, "1.88", clock() - timedelta(hours=2))
    db.flush()
    assert signals.expire_due(db, now=clock(), limits=DEFAULT_LIMITS) == []  # stale: ignored
    add_book_price(db, signal.selection_id, book_id, "1.88", clock())
    db.flush()
    assert signals.expire_due(db, now=clock(), limits=DEFAULT_LIMITS) == [signal]
    assert signal.expiry_reason is ExpiryReason.ODDS_BELOW_MINIMUM


def test_expires_when_betfair_moves_and_the_value_is_gone(
    setup: tuple[Signal, int], db: Session, clock: FakeClock
) -> None:
    signal, book_id = setup
    add_book_price(db, signal.selection_id, book_id, "1.95", clock())
    add_fair_price(db, signal.selection_id, 0.52, clock())
    db.flush()
    assert signals.expire_due(db, now=clock(), limits=DEFAULT_LIMITS) == [signal]
    assert signal.expiry_reason is ExpiryReason.VALUE_GONE


def test_pausing_alerts_expires_waiting_bets(
    setup: tuple[Signal, int], db: Session, clock: FakeClock
) -> None:
    signal, _ = setup
    portfolio.pause_alerts(db, PauseReason.OWNER, now=clock(), actor="owner")
    assert signals.expire_due(db, now=clock(), limits=DEFAULT_LIMITS) == [signal]
    assert signal.expiry_reason is ExpiryReason.ALERTS_PAUSED


def test_one_awaiting_signal_per_selection_is_enforced_by_the_database(
    setup: tuple[Signal, int], db: Session, clock: FakeClock
) -> None:
    from sqlalchemy.exc import IntegrityError

    signal, book_id = setup
    duplicate = Signal(
        event_id=signal.event_id,
        selection_id=signal.selection_id,
        bookmaker_id=book_id,
        offered_odds=D("1.95"),
        offered_at=clock(),
        fair_prob=0.542,
        edge=D("0.0569"),
        kelly_stake=D("32.75"),
        suggested_stake=D("33"),
        min_odds=D("1.89"),
        bankroll_at_signal=D("2186.90"),
        reason="dup",
        strategy_version="x",
        expires_at=clock() + timedelta(hours=1),
    )
    db.add(duplicate)
    with pytest.raises(IntegrityError):
        db.flush()
