from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from edgewise.domain.lifecycle import (
    ExpiryReason,
    InvalidTransition,
    OpenSignal,
    PlacementWarning,
    SignalStatus,
    can_undo,
    check_placement,
    check_transition,
    expiry_reason,
)

NOW = datetime(2026, 11, 7, 10, 0, tzinfo=UTC)
OPEN = OpenSignal(
    status=SignalStatus.AWAITING,
    expires_at=NOW + timedelta(minutes=30),
    kickoff=NOW + timedelta(hours=5),
    min_odds=D("1.89"),
)


@pytest.mark.parametrize(
    "target", [SignalStatus.PLACED, SignalStatus.SKIPPED, SignalStatus.EXPIRED]
)
def test_awaiting_can_be_decided(target: SignalStatus) -> None:
    check_transition(SignalStatus.AWAITING, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (SignalStatus.PLACED, SignalStatus.SKIPPED),
        (SignalStatus.EXPIRED, SignalStatus.PLACED),
        (SignalStatus.SKIPPED, SignalStatus.EXPIRED),
        (SignalStatus.AWAITING, SignalStatus.AWAITING),
    ],
)
def test_decided_signals_are_final(current: SignalStatus, target: SignalStatus) -> None:
    with pytest.raises(InvalidTransition):
        check_transition(current, target)


def test_stays_open_while_price_holds() -> None:
    assert expiry_reason(OPEN, now=NOW, current_odds=D("1.95"), current_fair_prob=0.542) is None
    assert expiry_reason(OPEN, now=NOW) is None  # no fresh price: only time can expire it


def test_expires_when_window_ends() -> None:
    assert expiry_reason(OPEN, now=OPEN.expires_at) is ExpiryReason.APPROVAL_WINDOW


def test_expires_at_kickoff() -> None:
    sig = OpenSignal(
        SignalStatus.AWAITING, NOW + timedelta(hours=9), NOW + timedelta(hours=1), D("2")
    )
    assert expiry_reason(sig, now=sig.kickoff) is ExpiryReason.KICKED_OFF


def test_expires_when_odds_fall_below_minimum() -> None:
    assert expiry_reason(OPEN, now=NOW, current_odds=D("1.88")) is ExpiryReason.ODDS_BELOW_MINIMUM
    assert expiry_reason(OPEN, now=NOW, current_odds=D("1.89")) is None


def test_expires_when_fair_price_moves_and_value_is_gone() -> None:
    # Price unchanged at 1.95, but Betfair now says 52%: 1.95 x 0.52 - 1 = 1.4% < 2%
    reason = expiry_reason(OPEN, now=NOW, current_odds=D("1.95"), current_fair_prob=0.52)
    assert reason is ExpiryReason.VALUE_GONE


def test_expires_when_alerts_are_paused() -> None:
    assert expiry_reason(OPEN, now=NOW, alerts_paused=True) is ExpiryReason.ALERTS_PAUSED


def test_only_awaiting_signals_expire() -> None:
    placed = OpenSignal(SignalStatus.PLACED, OPEN.expires_at, OPEN.kickoff, OPEN.min_odds)
    assert expiry_reason(placed, now=OPEN.kickoff + timedelta(hours=1)) is None


def test_undo_window() -> None:
    kw = {"now": NOW, "kickoff": NOW + timedelta(hours=1), "settled": False}
    assert can_undo(SignalStatus.PLACED, decided_at=NOW - timedelta(minutes=9), **kw)  # type: ignore[arg-type]
    assert not can_undo(SignalStatus.PLACED, decided_at=NOW - timedelta(minutes=11), **kw)  # type: ignore[arg-type]
    assert can_undo(SignalStatus.SKIPPED, decided_at=NOW, **kw)  # type: ignore[arg-type]
    assert not can_undo(SignalStatus.EXPIRED, decided_at=NOW, **kw)  # type: ignore[arg-type]
    assert not can_undo(SignalStatus.PLACED, decided_at=NOW, now=NOW, kickoff=NOW, settled=False)
    assert not can_undo(
        SignalStatus.PLACED, decided_at=NOW, now=NOW, kickoff=NOW + timedelta(1), settled=True
    )


def test_placement_records_the_truth_with_warnings() -> None:
    ok = check_placement(
        odds_taken=D("1.95"), stake=D("33"), min_odds=D("1.89"), suggested_stake=D("33")
    )
    assert ok == ()
    warned = check_placement(
        odds_taken=D("1.85"), stake=D("40"), min_odds=D("1.89"), suggested_stake=D("33")
    )
    assert warned == (PlacementWarning.BELOW_MIN_ODDS, PlacementWarning.ABOVE_SUGGESTED_STAKE)
    with pytest.raises(ValueError):
        check_placement(
            odds_taken=D("1"), stake=D("10"), min_odds=D("1.5"), suggested_stake=D("10")
        )
    with pytest.raises(ValueError):
        check_placement(odds_taken=D("2"), stake=D("0"), min_odds=D("1.5"), suggested_stake=D("10"))
