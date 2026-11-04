"""Bankroll ledger, drawdown stop and daily exposure. HIGH-RISK."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.orm import Session

from edgewise.db.models import AccountStatus, Bet, LedgerKind, PauseReason
from edgewise.domain.finder import find_value
from edgewise.domain.limits import DEFAULT_LIMITS
from edgewise.services import portfolio, signals
from tests.conftest import FakeClock
from tests.factories import candidate_for, make_bookmaker, make_match

SYDNEY = ZoneInfo("Australia/Sydney")


def deposit(db: Session, amount: str, at: datetime) -> None:
    portfolio.add_ledger_entry(db, kind=LedgerKind.DEPOSIT, amount=D(amount), now=at, actor="owner")


def settle(db: Session, amount: str, at: datetime) -> None:
    portfolio.add_ledger_entry(
        db, kind=LedgerKind.CORRECTION, amount=D(amount), now=at, actor="system"
    )


def test_ledger_keeps_a_running_balance(db: Session, clock: FakeClock) -> None:
    assert portfolio.bankroll(db) == 0
    deposit(db, "2000", clock())
    portfolio.add_ledger_entry(
        db, kind=LedgerKind.WITHDRAWAL, amount=D("-150.505"), now=clock(), actor="owner"
    )
    assert portfolio.bankroll(db) == D("1849.49")  # amounts are rounded to the cent


def test_ledger_refuses_nonsense(db: Session, clock: FakeClock) -> None:
    deposit(db, "100", clock())
    with pytest.raises(ValueError, match="more than \\$0"):
        deposit(db, "0", clock())
    with pytest.raises(ValueError, match="negative"):
        portfolio.add_ledger_entry(
            db, kind=LedgerKind.WITHDRAWAL, amount=D("50"), now=clock(), actor="owner"
        )
    with pytest.raises(ValueError, match="more than the bankroll"):
        portfolio.add_ledger_entry(
            db, kind=LedgerKind.WITHDRAWAL, amount=D("-100.01"), now=clock(), actor="owner"
        )


def test_drawdown_stop_pauses_once_and_resume_resets_the_peak(
    db: Session, clock: FakeClock
) -> None:
    deposit(db, "1000", clock())
    clock.advance(minutes=1)
    settle(db, "200", clock())  # peak 1200
    clock.advance(minutes=1)
    settle(db, "-170", clock())  # 1030: -14.2%
    assert portfolio.peak_since_resume(db) == D("1200")
    assert not portfolio.enforce_drawdown_stop(db, now=clock(), limits=DEFAULT_LIMITS)
    clock.advance(minutes=1)
    settle(db, "-10", clock())  # 1020: exactly -15%
    assert portfolio.enforce_drawdown_stop(db, now=clock(), limits=DEFAULT_LIMITS)
    assert not portfolio.enforce_drawdown_stop(db, now=clock(), limits=DEFAULT_LIMITS)
    assert [p.reason for p in portfolio.open_pauses(db)] == [PauseReason.DRAWDOWN_STOP]

    # Recovering does not lift the pause: only the owner can.
    clock.advance(minutes=1)
    settle(db, "100", clock())
    assert portfolio.open_pauses(db)

    clock.advance(minutes=1)
    assert portfolio.resume_alerts(db, now=clock()) == 1
    assert portfolio.open_pauses(db) == []
    assert portfolio.peak_since_resume(db) == D("1120")  # the peak restarts at resume
    clock.advance(minutes=1)
    settle(db, "50", clock())
    assert portfolio.peak_since_resume(db) == D("1170")


def test_withdrawals_are_not_losses(db: Session, clock: FakeClock) -> None:
    deposit(db, "2000", clock())
    clock.advance(minutes=1)
    portfolio.add_ledger_entry(
        db, kind=LedgerKind.WITHDRAWAL, amount=D("-500"), now=clock(), actor="owner"
    )
    assert portfolio.bankroll(db) == D("1500.00")
    assert portfolio.peak_since_resume(db) == D("1500.00")  # the peak moved with the money
    assert not portfolio.enforce_drawdown_stop(db, now=clock(), limits=DEFAULT_LIMITS)
    # Real losses still count: 300 lost from a 1500 peak is -20%.
    clock.advance(minutes=1)
    settle(db, "-300", clock())
    assert portfolio.peak_since_resume(db) == D("1500.00")
    assert portfolio.enforce_drawdown_stop(db, now=clock(), limits=DEFAULT_LIMITS)


def test_deposits_raise_the_peak_without_counting_as_wins(db: Session, clock: FakeClock) -> None:
    deposit(db, "1000", clock())
    clock.advance(minutes=1)
    settle(db, "-140", clock())  # -14% of 1000
    assert portfolio.peak_since_resume(db) == D("1000.00")
    clock.advance(minutes=1)
    deposit(db, "1000", clock())
    # Same $140 loss, now measured against a $2000 peak: -7%, nowhere near the stop.
    assert portfolio.bankroll(db) == D("1860.00")
    assert portfolio.peak_since_resume(db) == D("2000.00")


def test_owner_pause_blocks_the_finder(db: Session, clock: FakeClock) -> None:
    deposit(db, "1000", clock())
    portfolio.pause_alerts(db, PauseReason.OWNER, now=clock(), actor="owner")
    assert portfolio.pause_alerts(db, PauseReason.OWNER, now=clock(), actor="owner") is None
    state = portfolio.portfolio_state(db, now=clock(), tz=SYDNEY)
    assert state.alerts_paused is True


def test_exposure_counts_today_in_sydney_plus_awaiting(db: Session, clock: FakeClock) -> None:
    deposit(db, "2186.90", clock())
    book = make_bookmaker(db)
    event, sel = make_match(db, kickoff=clock() + timedelta(hours=8))
    now = clock()
    state = portfolio.portfolio_state(db, now=now, tz=SYDNEY)
    result = find_value([candidate_for(event, sel[next(iter(sel))], book.id, now)], state, now=now)
    (signal,) = signals.record_suggestions(db, result, now=now, bankroll=state.bankroll)
    assert portfolio.exposure_today(db, now=now, tz=SYDNEY) == D("33.00")  # awaiting

    signals.mark_placed(db, signal.id, odds_taken=D("1.95"), stake=D("30"), now=now)
    assert portfolio.exposure_today(db, now=now, tz=SYDNEY) == D("30.00")  # placed, actual

    # 2026-11-07 09:00 UTC is 20:00 in Sydney. Sydney midnight is 13:00 UTC.
    assert portfolio.start_of_owner_day(now, SYDNEY) == datetime(2026, 11, 6, 13, 0, tzinfo=UTC)
    next_morning = datetime(2026, 11, 7, 13, 30, tzinfo=UTC)  # 00:30 Sydney, next day
    assert portfolio.exposure_today(db, now=next_morning, tz=SYDNEY) == 0


def test_portfolio_state_feeds_the_correlation_guard(db: Session, clock: FakeClock) -> None:
    deposit(db, "1000", clock())
    book = make_bookmaker(db)
    limited = make_bookmaker(
        db, "ladbrokes", account_status=AccountStatus.LIMITED, stake_limit=D("15")
    )
    closed = make_bookmaker(db, "neds", account_status=AccountStatus.CLOSED)
    event, sel = make_match(db, kickoff=clock() + timedelta(hours=8))
    now = clock()
    state = portfolio.portfolio_state(db, now=now, tz=SYDNEY)
    assert state.bookmakers[book.id].available
    assert state.bookmakers[limited.id].stake_limit == D("15")
    assert not state.bookmakers[closed.id].available

    result = find_value([candidate_for(event, sel[next(iter(sel))], book.id, now)], state, now=now)
    signals.record_suggestions(db, result, now=now, bankroll=state.bankroll)
    state = portfolio.portfolio_state(db, now=now, tz=SYDNEY)
    assert state.bets_per_event == {event.id: 1}
    assert state.extra_bets_allowed == frozenset()
    event.allow_extra_bets = True
    db.flush()
    assert portfolio.portfolio_state(db, now=now, tz=SYDNEY).extra_bets_allowed == {event.id}


def test_bet_rows_record_actual_odds(db: Session, clock: FakeClock) -> None:
    deposit(db, "1000", clock())
    book = make_bookmaker(db)
    event, sel = make_match(db, kickoff=clock() + timedelta(hours=8))
    now = clock()
    state = portfolio.portfolio_state(db, now=now, tz=SYDNEY)
    result = find_value([candidate_for(event, sel[next(iter(sel))], book.id, now)], state, now=now)
    (signal,) = signals.record_suggestions(db, result, now=now, bankroll=state.bankroll)
    bet = signals.mark_placed(db, signal.id, odds_taken=D("1.85"), stake=D("15"), now=now)
    assert isinstance(bet, Bet)
    assert bet.warnings == ["below_min_odds"]
