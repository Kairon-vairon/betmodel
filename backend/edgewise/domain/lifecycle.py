"""Signal lifecycle: awaiting -> placed / skipped / expired.

A signal expires when the approval window ends, at kick-off, when the bookmaker's price
falls below the "don't take below" odds, when the value is gone at the latest fair price,
or when alerts are paused.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from edgewise.domain.limits import DEFAULT_LIMITS, SafetyLimits
from edgewise.domain.staking import edge


class SignalStatus(StrEnum):
    AWAITING = "awaiting"
    PLACED = "placed"
    SKIPPED = "skipped"
    EXPIRED = "expired"


class ExpiryReason(StrEnum):
    APPROVAL_WINDOW = "approval_window"
    KICKED_OFF = "kicked_off"
    ODDS_BELOW_MINIMUM = "odds_below_minimum"
    VALUE_GONE = "value_gone"
    ALERTS_PAUSED = "alerts_paused"


class InvalidTransition(ValueError):
    pass


_ALLOWED: dict[SignalStatus, frozenset[SignalStatus]] = {
    SignalStatus.AWAITING: frozenset(
        {SignalStatus.PLACED, SignalStatus.SKIPPED, SignalStatus.EXPIRED}
    ),
    SignalStatus.PLACED: frozenset(),
    SignalStatus.SKIPPED: frozenset(),
    SignalStatus.EXPIRED: frozenset(),
}

UNDO_WINDOW = timedelta(minutes=10)


@dataclass(frozen=True)
class OpenSignal:
    status: SignalStatus
    expires_at: datetime
    kickoff: datetime
    min_odds: Decimal


def check_transition(current: SignalStatus, target: SignalStatus) -> None:
    if target not in _ALLOWED[current]:
        raise InvalidTransition(f"a {current.value} signal cannot become {target.value}")


def expiry_reason(
    signal: OpenSignal,
    *,
    now: datetime,
    current_odds: Decimal | None = None,
    current_fair_prob: float | None = None,
    alerts_paused: bool = False,
    limits: SafetyLimits = DEFAULT_LIMITS,
) -> ExpiryReason | None:
    """Why an awaiting signal should expire now, or None if it should stay open.

    current_odds / current_fair_prob are the latest *fresh* prices; pass None when there is
    no fresh price (stale data never keeps a signal alive past its window, and never
    expires one early either).
    """
    if signal.status is not SignalStatus.AWAITING:
        return None
    if alerts_paused:
        return ExpiryReason.ALERTS_PAUSED
    if now >= signal.kickoff:
        return ExpiryReason.KICKED_OFF
    if now >= signal.expires_at:
        return ExpiryReason.APPROVAL_WINDOW
    if current_odds is not None and current_odds < signal.min_odds:
        return ExpiryReason.ODDS_BELOW_MINIMUM
    if (
        current_odds is not None
        and current_fair_prob is not None
        and edge(current_odds, current_fair_prob) < limits.min_odds_edge
    ):
        return ExpiryReason.VALUE_GONE
    return None


def can_undo(
    status: SignalStatus,
    *,
    decided_at: datetime | None,
    now: datetime,
    kickoff: datetime,
    settled: bool,
    undo_window: timedelta = UNDO_WINDOW,
) -> bool:
    """A placed or skipped tap can be undone for a few minutes, before kick-off."""
    if status not in (SignalStatus.PLACED, SignalStatus.SKIPPED) or decided_at is None:
        return False
    return not settled and now < kickoff and now - decided_at <= undo_window


class PlacementWarning(StrEnum):
    BELOW_MIN_ODDS = "below_min_odds"
    ABOVE_SUGGESTED_STAKE = "above_suggested_stake"


def check_placement(
    *,
    odds_taken: Decimal,
    stake: Decimal,
    min_odds: Decimal,
    suggested_stake: Decimal,
) -> tuple[PlacementWarning, ...]:
    """Validate what the owner says they placed. Records the truth, with warnings."""
    if odds_taken <= 1:
        raise ValueError("odds taken must be above 1.00")
    if stake <= 0:
        raise ValueError("stake must be above $0")
    warnings: list[PlacementWarning] = []
    if odds_taken < min_odds:
        warnings.append(PlacementWarning.BELOW_MIN_ODDS)
    if stake > suggested_stake:
        warnings.append(PlacementWarning.ABOVE_SUGGESTED_STAKE)
    return tuple(warnings)
