"""Fair probabilities from prices.

Every market price includes a margin: the implied probabilities (1 / odds) of all
outcomes add up to more than 100%. Removing that margin gives the "fair" probability
of each outcome. Phase 1 uses Betfair Exchange prices as the reference.

Method (docs/PHASE_1_PLAN.md, M3):
1. For each runner take the best back and best lay price and use the midpoint of their
   implied probabilities: (1/back + 1/lay) / 2. The true price sits between the two.
2. Refuse the market if any runner is missing a side or the back/lay gap is too wide
   (a thin market's price is not a reliable estimate; CLAUDE.md rule 7).
3. Scale the midpoints so they add up to exactly 100%. The baseline is the
   multiplicative method (divide each by the total). Power and Shin are available for
   the lab to compare against it.

For Asian handicap and whole goal lines, where a push refunds the stake, the result is
the win probability *given no push*. That is what a two-way price means and it is the
correct input for both the edge and the Kelly stake.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class MarginMethod(StrEnum):
    MULTIPLICATIVE = "multiplicative"  # Phase 1 baseline
    POWER = "power"
    SHIN = "shin"


class MarketUnusable(ValueError):
    """The prices cannot be trusted as a fair-price reference right now."""


def implied_probabilities(odds: Sequence[Decimal | float]) -> list[float]:
    if len(odds) < 2:
        raise ValueError("a market needs at least two outcomes")
    out: list[float] = []
    for price in odds:
        value = float(price)
        if not value > 1.0:
            raise ValueError(f"decimal odds must be above 1.0, got {price}")
        out.append(1.0 / value)
    return out


def remove_margin(
    implied: Sequence[float], method: MarginMethod = MarginMethod.MULTIPLICATIVE
) -> list[float]:
    """Turn implied probabilities (which include a margin) into probabilities summing to 1."""
    probs = [float(p) for p in implied]
    if len(probs) < 2:
        raise ValueError("a market needs at least two outcomes")
    if any(not 0.0 < p < 1.0 for p in probs):
        raise ValueError("implied probabilities must be between 0 and 1")
    if method is MarginMethod.MULTIPLICATIVE:
        result = _multiplicative(probs)
    elif method is MarginMethod.POWER:
        result = _power(probs)
    else:
        result = _shin(probs)
    return _normalise(result)


def _normalise(probs: list[float]) -> list[float]:
    total = math.fsum(probs)
    return [p / total for p in probs]


def _multiplicative(probs: list[float]) -> list[float]:
    total = math.fsum(probs)
    return [p / total for p in probs]


def _power(probs: list[float]) -> list[float]:
    """Find k so that sum(p_i ** k) == 1. Shrinks longshots more than favourites."""
    total = math.fsum(probs)
    if math.isclose(total, 1.0, rel_tol=0.0, abs_tol=1e-12):
        return list(probs)

    def excess(k: float) -> float:
        return math.fsum(p**k for p in probs) - 1.0

    # excess() falls as k rises. k > 1 when there is a margin, k < 1 when under 100%.
    lo, hi = (1.0, 2.0) if total > 1.0 else (0.5, 1.0)
    while excess(hi) > 0:
        hi *= 2.0
    while excess(lo) < 0:
        lo /= 2.0
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if excess(mid) > 0:
            lo = mid
        else:
            hi = mid
    k = (lo + hi) / 2.0
    return [p**k for p in probs]


def _shin(probs: list[float]) -> list[float]:
    """Shin (1992/1993): assumes part of the margin protects against insider bettors.

    Only defined when there is a margin (total above 100%); otherwise falls back to the
    multiplicative method.
    """
    total = math.fsum(probs)
    if total <= 1.0:
        return _multiplicative(probs)

    def shin_probs(z: float) -> list[float]:
        return [
            (math.sqrt(z * z + 4.0 * (1.0 - z) * p * p / total) - z) / (2.0 * (1.0 - z))
            for p in probs
        ]

    def excess(z: float) -> float:
        return math.fsum(shin_probs(z)) - 1.0

    lo, hi = 0.0, 0.999
    if excess(hi) > 0:  # pathological margin; do not guess
        raise ValueError("margin too large for the Shin method")
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if excess(mid) > 0:
            lo = mid
        else:
            hi = mid
    return shin_probs((lo + hi) / 2.0)


@dataclass(frozen=True)
class ExchangeRunner:
    """Best available prices for one outcome on the exchange."""

    key: str  # selection code, e.g. "home"
    best_back: Decimal | None
    best_lay: Decimal | None


@dataclass(frozen=True)
class FairPrice:
    probabilities: Mapping[str, float]
    mid_overround: float  # sum of midpoint implied probabilities before scaling
    method: MarginMethod

    def odds(self, key: str) -> float:
        return 1.0 / self.probabilities[key]


DEFAULT_MAX_SPREAD = Decimal("0.05")  # lay may be at most 5% above back


def exchange_fair_price(
    runners: Sequence[ExchangeRunner],
    *,
    method: MarginMethod = MarginMethod.MULTIPLICATIVE,
    max_spread: Decimal | None = DEFAULT_MAX_SPREAD,
) -> FairPrice:
    """Fair probabilities for a complete exchange market (all outcomes present)."""
    if len(runners) < 2:
        raise MarketUnusable("a market needs at least two outcomes")
    keys = [r.key for r in runners]
    if len(set(keys)) != len(keys):
        raise MarketUnusable("duplicate outcomes in market")

    mids: list[float] = []
    for runner in runners:
        back, lay = runner.best_back, runner.best_lay
        if back is None or lay is None:
            raise MarketUnusable(f"no {'back' if back is None else 'lay'} price for {runner.key}")
        if back <= 1 or lay <= 1:
            raise MarketUnusable(f"invalid price for {runner.key}")
        if lay < back:
            raise MarketUnusable(f"crossed prices for {runner.key} (lay below back)")
        if max_spread is not None and lay / back - 1 > max_spread:
            raise MarketUnusable(
                f"back/lay gap too wide for {runner.key} ({back} / {lay}); market too thin"
            )
        mids.append((1.0 / float(back) + 1.0 / float(lay)) / 2.0)

    probs = remove_margin(mids, method)
    return FairPrice(
        probabilities=dict(zip(keys, probs, strict=True)),
        mid_overround=math.fsum(mids),
        method=method,
    )
