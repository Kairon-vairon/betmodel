"""Edge, minimum odds and stake size.

HIGH-RISK CODE (CLAUDE.md rule 4): stake sizing. Changes must be listed on their own
under "High-risk changes" in the release notes.

Formulas (docs/PROJECT_BRIEF.md):
- Edge         = bookmaker odds x fair probability - 1
- Minimum odds = the price at which the edge drops to 2%  -> (1 + 0.02) / fair probability
- Stake        = 1/4 Kelly = 0.25 x edge / (odds - 1) x bankroll, rounded to $1,
                 then capped by the safety limits and the bookmaker's limit on the account.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from enum import StrEnum

from edgewise.domain.limits import SafetyLimits

DOLLAR = Decimal("1")
CENT = Decimal("0.01")


def _prob(fair_prob: float) -> Decimal:
    if not 0.0 < fair_prob < 1.0:
        raise ValueError(f"probability must be between 0 and 1, got {fair_prob}")
    return Decimal(repr(fair_prob))


def _odds(odds: Decimal) -> Decimal:
    if odds <= 1:
        raise ValueError(f"decimal odds must be above 1, got {odds}")
    return odds


def edge(odds: Decimal, fair_prob: float) -> Decimal:
    """Expected profit per $1 staked, e.g. 0.057 for +5.7%. Six decimal places."""
    return (_odds(odds) * _prob(fair_prob) - 1).quantize(Decimal("0.000001"), ROUND_HALF_UP)


def min_acceptable_odds(fair_prob: float, min_odds_edge: Decimal) -> Decimal:
    """Lowest odds still worth taking, rounded UP to the cent so the edge never dips below."""
    return ((1 + min_odds_edge) / _prob(fair_prob)).quantize(CENT, ROUND_CEILING)


def kelly_fraction(odds: Decimal, fair_prob: float) -> Decimal:
    """Full-Kelly share of bankroll: edge / (odds - 1). Zero when there is no edge."""
    e = edge(odds, fair_prob)
    if e <= 0:
        return Decimal(0)
    return e / (_odds(odds) - 1)


class StakeCap(StrEnum):
    MAX_STAKE = "max_stake"  # 2% of bankroll per bet
    BOOKMAKER_LIMIT = "bookmaker_limit"  # the bookmaker restricted the account
    DAILY_EXPOSURE = "daily_exposure"  # 8% of bankroll per day, placed + awaiting


@dataclass(frozen=True)
class StakeDecision:
    stake: Decimal  # whole dollars; can be zero or less when a cap leaves no room
    kelly_stake: Decimal  # quarter Kelly before caps, to the cent (shown as "capped from")
    capped_by: StakeCap | None


def size_stake(
    *,
    odds: Decimal,
    fair_prob: float,
    bankroll: Decimal,
    limits: SafetyLimits,
    exposure_today: Decimal,
    bookmaker_limit: Decimal | None,
) -> StakeDecision:
    """Quarter-Kelly stake in whole dollars, never above any cap.

    Caps are rounded DOWN to the dollar so a rounded stake can never break a limit.
    """
    if bankroll <= 0:
        return StakeDecision(stake=Decimal(0), kelly_stake=Decimal(0), capped_by=None)

    kelly = limits.kelly_multiplier * kelly_fraction(odds, fair_prob) * bankroll
    stake = kelly.quantize(DOLLAR, ROUND_HALF_UP)

    caps: list[tuple[StakeCap, Decimal]] = []
    if bookmaker_limit is not None:
        caps.append((StakeCap.BOOKMAKER_LIMIT, bookmaker_limit.quantize(DOLLAR, ROUND_FLOOR)))
    caps.append(
        (StakeCap.MAX_STAKE, (bankroll * limits.max_stake_fraction).quantize(DOLLAR, ROUND_FLOOR))
    )
    daily_room = bankroll * limits.max_daily_exposure_fraction - exposure_today
    caps.append((StakeCap.DAILY_EXPOSURE, daily_room.quantize(DOLLAR, ROUND_FLOOR)))

    capped_by: StakeCap | None = None
    for cap_name, cap_value in caps:
        if cap_value < stake:
            stake, capped_by = cap_value, cap_name
    return StakeDecision(
        stake=stake, kelly_stake=kelly.quantize(CENT, ROUND_HALF_UP), capped_by=capped_by
    )


def drawdown_breached(bankroll: Decimal, peak: Decimal, limits: SafetyLimits) -> bool:
    """True when the bankroll has fallen by the drawdown-stop share (15%) or more from peak."""
    if peak <= 0:
        return bankroll < 0
    return bankroll <= peak * (1 - limits.drawdown_stop_fraction)
