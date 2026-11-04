import math
from decimal import Decimal as D

import pytest

from edgewise.domain.pricing import (
    ExchangeRunner,
    MarginMethod,
    MarketUnusable,
    exchange_fair_price,
    implied_probabilities,
    remove_margin,
)

ALL_METHODS = list(MarginMethod)


def test_implied_probabilities() -> None:
    assert implied_probabilities([D("2.00"), D("4.00")]) == [0.5, 0.25]


@pytest.mark.parametrize("bad", [[D("2.0")], [D("1.00"), D("2.0")], [D("0.5"), D("2.0")]])
def test_implied_probabilities_rejects_bad_input(bad: list[D]) -> None:
    with pytest.raises(ValueError):
        implied_probabilities(bad)


@pytest.mark.parametrize("method", ALL_METHODS)
def test_every_method_sums_to_one(method: MarginMethod) -> None:
    implied = implied_probabilities([D("1.50"), D("4.20"), D("7.00")])  # 105% book
    fair = remove_margin(implied, method)
    assert math.isclose(sum(fair), 1.0, abs_tol=1e-12)
    assert fair[0] > fair[1] > fair[2]


@pytest.mark.parametrize("method", ALL_METHODS)
def test_even_two_way_market_is_fifty_fifty(method: MarginMethod) -> None:
    fair = remove_margin(implied_probabilities([D("1.90"), D("1.90")]), method)
    assert fair == pytest.approx([0.5, 0.5])


def test_multiplicative_keeps_ratios() -> None:
    implied = [0.55, 0.30, 0.20]
    fair = remove_margin(implied, MarginMethod.MULTIPLICATIVE)
    assert fair == pytest.approx([p / 1.05 for p in implied])


@pytest.mark.parametrize("method", [MarginMethod.POWER, MarginMethod.SHIN])
def test_power_and_shin_take_more_margin_from_longshots(method: MarginMethod) -> None:
    implied = implied_probabilities([D("1.40"), D("4.80"), D("8.50")])
    mult = remove_margin(implied, MarginMethod.MULTIPLICATIVE)
    other = remove_margin(implied, method)
    assert other[0] > mult[0]  # favourite keeps more probability
    assert other[2] < mult[2]  # longshot gives up more


def test_power_handles_book_under_100_percent() -> None:
    fair = remove_margin([0.49, 0.49], MarginMethod.POWER)
    assert fair == pytest.approx([0.5, 0.5])


def test_shin_falls_back_without_margin() -> None:
    implied = [0.6, 0.38]
    assert remove_margin(implied, MarginMethod.SHIN) == pytest.approx(
        remove_margin(implied, MarginMethod.MULTIPLICATIVE)
    )


def test_no_margin_is_unchanged() -> None:
    assert remove_margin([0.5, 0.3, 0.2], MarginMethod.POWER) == pytest.approx([0.5, 0.3, 0.2])


def _match(
    home: tuple[str, str], draw: tuple[str, str], away: tuple[str, str]
) -> list[ExchangeRunner]:
    return [
        ExchangeRunner("home", D(home[0]), D(home[1])),
        ExchangeRunner("draw", D(draw[0]), D(draw[1])),
        ExchangeRunner("away", D(away[0]), D(away[1])),
    ]


def test_exchange_fair_price_uses_back_lay_midpoint() -> None:
    fair = exchange_fair_price(_match(("1.84", "1.85"), ("3.75", "3.80"), ("4.90", "5.00")))
    mids = [
        (1 / 1.84 + 1 / 1.85) / 2,
        (1 / 3.75 + 1 / 3.80) / 2,
        (1 / 4.90 + 1 / 5.00) / 2,
    ]
    total = sum(mids)
    assert fair.mid_overround == pytest.approx(total)
    assert fair.probabilities["home"] == pytest.approx(mids[0] / total)
    assert sum(fair.probabilities.values()) == pytest.approx(1.0)
    assert fair.odds("home") == pytest.approx(total / mids[0])
    assert fair.method is MarginMethod.MULTIPLICATIVE


def test_exchange_refuses_missing_side() -> None:
    runners = [ExchangeRunner("yes", D("1.90"), None), ExchangeRunner("no", D("2.00"), D("2.02"))]
    with pytest.raises(MarketUnusable, match="no lay price for yes"):
        exchange_fair_price(runners)


def test_exchange_refuses_thin_market() -> None:
    runners = _match(("1.84", "1.85"), ("3.70", "4.10"), ("4.90", "5.00"))  # draw gap 10.8%
    with pytest.raises(MarketUnusable, match="too thin"):
        exchange_fair_price(runners)
    # The guard can be relaxed by configuration (e.g. in the lab).
    exchange_fair_price(runners, max_spread=D("0.20"))
    exchange_fair_price(runners, max_spread=None)


def test_exchange_refuses_crossed_and_duplicate_runners() -> None:
    with pytest.raises(MarketUnusable, match="crossed"):
        exchange_fair_price(
            [ExchangeRunner("a", D("2.10"), D("2.00")), ExchangeRunner("b", D("2"), D("2.02"))]
        )
    with pytest.raises(MarketUnusable, match="duplicate"):
        exchange_fair_price(
            [ExchangeRunner("a", D("2"), D("2.02")), ExchangeRunner("a", D("2"), D("2.02"))]
        )
    with pytest.raises(MarketUnusable, match="at least two"):
        exchange_fair_price([ExchangeRunner("a", D("2"), D("2.02"))])
