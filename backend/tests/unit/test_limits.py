"""Safety limit defaults and bounds. HIGH-RISK: pins the defaults in CLAUDE.md rule 3."""

from datetime import timedelta
from decimal import Decimal as D

import pytest

from edgewise.domain.limits import BOUNDS, DEFAULT_LIMITS, SafetyLimits


def test_defaults_match_the_brief() -> None:
    limits = DEFAULT_LIMITS
    assert limits.max_stake_fraction == D("0.02")
    assert limits.max_daily_exposure_fraction == D("0.08")
    assert limits.drawdown_stop_fraction == D("0.15")
    assert limits.min_edge == D("0.03")
    assert limits.min_odds_edge == D("0.02")
    assert (limits.min_odds, limits.max_odds) == (D("1.50"), D("6.00"))
    assert limits.kelly_multiplier == D("0.25")
    assert limits.approval_window == timedelta(minutes=60)
    assert limits.max_bets_per_match == 1


def test_as_numbers_covers_every_bound() -> None:
    numbers = DEFAULT_LIMITS.as_numbers()
    assert set(numbers) == set(BOUNDS)
    assert numbers["approval_window_minutes"] == 60


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_stake_fraction": D("0.2")},  # a typo for 2%
        {"max_daily_exposure_fraction": D("0.5")},
        {"drawdown_stop_fraction": D("0.9")},
        {"min_edge": D("0.001")},
        {"kelly_multiplier": D("1")},
        {"min_odds": D("1.00")},
        {"min_odds": D("6.00"), "max_odds": D("6.00")},
        {"min_odds_edge": D("0.03")},  # must be below min_edge
        {"approval_window": timedelta(0)},
        {"max_bets_per_match": 0},
    ],
)
def test_out_of_bounds_values_are_refused(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        SafetyLimits(**kwargs)  # type: ignore[arg-type]


def test_overrides_apply_and_validate() -> None:
    limits = DEFAULT_LIMITS.with_overrides(
        {
            "max_stake_fraction": D("0.015"),
            "approval_window_minutes": D("30"),
            "max_bets_per_match": D("2"),
        }
    )
    assert limits.max_stake_fraction == D("0.015")
    assert limits.approval_window == timedelta(minutes=30)
    assert limits.max_bets_per_match == 2
    assert limits.min_edge == D("0.03")  # untouched
    with pytest.raises(ValueError, match="unknown limit"):
        DEFAULT_LIMITS.with_overrides({"max_stake": D("1")})
    with pytest.raises(ValueError):
        DEFAULT_LIMITS.with_overrides({"max_stake_fraction": D("0.5")})
