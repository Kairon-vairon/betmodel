"""Stake formula and caps. HIGH-RISK: these tests pin the numbers in PROJECT_BRIEF.md."""

from decimal import Decimal as D

import pytest

from edgewise.domain.limits import DEFAULT_LIMITS, SafetyLimits
from edgewise.domain.staking import (
    StakeCap,
    drawdown_breached,
    edge,
    kelly_fraction,
    min_acceptable_odds,
    size_stake,
)


def test_edge_matches_brief_example() -> None:
    # Brighton: Sportsbet 1.95, Betfair fair probability 54.2% -> +5.7%
    assert edge(D("1.95"), 0.542) == D("0.0569")


def test_edge_negative_when_price_is_short() -> None:
    assert edge(D("1.80"), 0.542) == D("-0.0244")


def test_min_odds_is_where_edge_drops_to_two_percent_rounded_up() -> None:
    assert min_acceptable_odds(0.542, D("0.02")) == D("1.89")  # 1.8819 -> 1.89
    assert edge(D("1.89"), 0.542) >= D("0.02")
    assert edge(D("1.88"), 0.542) < D("0.02")


def test_min_odds_exact_value_is_not_bumped() -> None:
    assert min_acceptable_odds(0.51, D("0.02")) == D("2.00")


def test_kelly_fraction() -> None:
    assert kelly_fraction(D("1.95"), 0.542) == D("0.0569") / D("0.95")
    assert kelly_fraction(D("1.80"), 0.542) == 0


def _stake(**overrides: object) -> object:
    args: dict[str, object] = {
        "odds": D("1.95"),
        "fair_prob": 0.542,
        "bankroll": D("2186.90"),
        "limits": DEFAULT_LIMITS,
        "exposure_today": D("0"),
        "bookmaker_limit": None,
    }
    args.update(overrides)
    return size_stake(**args)  # type: ignore[arg-type]


def test_quarter_kelly_matches_brief_example() -> None:
    # 0.25 x 0.0569 / 0.95 x 2186.90 = 32.75 -> $33 (1.5% of bankroll)
    decision = _stake()
    assert decision.stake == D("33")
    assert decision.kelly_stake == D("32.75")
    assert decision.capped_by is None


def test_rounds_half_up_to_whole_dollars() -> None:
    # odds 2.00, p 0.6 -> edge 0.2, Kelly 0.2, quarter 0.05 x 210 = 10.50 -> $11
    limits = SafetyLimits(max_stake_fraction=D("0.10"))
    decision = _stake(odds=D("2.00"), fair_prob=0.6, bankroll=D("210"), limits=limits)
    assert decision.kelly_stake == D("10.50")
    assert decision.stake == D("11")


def test_capped_at_two_percent_of_bankroll_rounded_down() -> None:
    decision = _stake(odds=D("3.00"), fair_prob=0.5)  # quarter Kelly would be $137
    assert decision.stake == D("43")  # 2% of 2186.90 = 43.738 -> $43, never $44
    assert decision.capped_by is StakeCap.MAX_STAKE


def test_capped_by_bookmaker_account_limit() -> None:
    decision = _stake(bookmaker_limit=D("15"))
    assert decision.stake == D("15")
    assert decision.capped_by is StakeCap.BOOKMAKER_LIMIT


def test_bookmaker_limit_rounds_down() -> None:
    assert _stake(bookmaker_limit=D("15.99")).stake == D("15")


def test_capped_by_remaining_daily_exposure() -> None:
    # 8% of 2186.90 = 174.95; with 160 already used, $14 is left
    decision = _stake(exposure_today=D("160"))
    assert decision.stake == D("14")
    assert decision.capped_by is StakeCap.DAILY_EXPOSURE


def test_no_room_left_today_gives_no_stake() -> None:
    assert _stake(exposure_today=D("175")).stake <= 0


def test_smallest_cap_wins() -> None:
    decision = _stake(
        odds=D("3.00"), fair_prob=0.5, bookmaker_limit=D("50"), exposure_today=D("150")
    )
    assert decision.stake == D("24")  # daily room 24.95 < max stake 43 < bookmaker 50
    assert decision.capped_by is StakeCap.DAILY_EXPOSURE


def test_no_edge_no_stake() -> None:
    assert _stake(odds=D("1.80")).stake == 0


def test_no_bankroll_no_stake() -> None:
    assert _stake(bankroll=D("0")).stake == 0
    assert _stake(bankroll=D("-10")).stake == 0


@pytest.mark.parametrize(
    ("bankroll", "peak", "breached"),
    [
        ("850", "1000", True),
        ("850.01", "1000", False),
        ("700", "1000", True),
        ("1000", "1000", False),
    ],
)
def test_drawdown_stop_at_fifteen_percent(bankroll: str, peak: str, breached: bool) -> None:
    assert drawdown_breached(D(bankroll), D(peak), DEFAULT_LIMITS) is breached


def test_invalid_inputs_are_rejected() -> None:
    with pytest.raises(ValueError):
        edge(D("1.00"), 0.5)
    with pytest.raises(ValueError):
        edge(D("2.00"), 1.2)
    with pytest.raises(ValueError):
        min_acceptable_odds(0.0, D("0.02"))
