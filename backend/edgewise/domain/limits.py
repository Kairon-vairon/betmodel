"""Safety limits.

HIGH-RISK CODE (CLAUDE.md rules 3 and 4). Any change to these defaults, their bounds,
or how they are applied must be listed on its own under "High-risk changes" in the
release notes, never bundled silently with other changes.

The limits are enforced on the server when bets are suggested. A bet that breaks a limit
is never suggested.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, fields, replace
from datetime import timedelta
from decimal import Decimal

# Bounds that no setting can go beyond. They exist to catch typos (for example "20"
# instead of "2" percent), not to second-guess the owner's choices inside them.
BOUNDS: dict[str, tuple[Decimal, Decimal]] = {
    "max_stake_fraction": (Decimal("0.001"), Decimal("0.10")),
    "max_daily_exposure_fraction": (Decimal("0.001"), Decimal("0.30")),
    "drawdown_stop_fraction": (Decimal("0.01"), Decimal("0.50")),
    "min_edge": (Decimal("0.01"), Decimal("0.20")),
    "min_odds_edge": (Decimal("0"), Decimal("0.20")),
    "min_odds": (Decimal("1.01"), Decimal("20")),
    "max_odds": (Decimal("1.01"), Decimal("20")),
    "kelly_multiplier": (Decimal("0.01"), Decimal("0.50")),
    "min_stake": (Decimal("1"), Decimal("1000")),
    "approval_window_minutes": (Decimal("1"), Decimal("720")),
    "max_bets_per_match": (Decimal("1"), Decimal("5")),
}


@dataclass(frozen=True)
class SafetyLimits:
    # Max stake per bet, as a share of the current bankroll.
    max_stake_fraction: Decimal = Decimal("0.02")
    # Max stake placed today plus stake awaiting approval, as a share of the bankroll.
    max_daily_exposure_fraction: Decimal = Decimal("0.08")
    # A fall of this much from the peak pauses all alerts until the owner resumes.
    drawdown_stop_fraction: Decimal = Decimal("0.15")
    # Minimum edge after the margin is removed.
    min_edge: Decimal = Decimal("0.03")
    # "Don't take below" odds are where the edge would fall to this.
    min_odds_edge: Decimal = Decimal("0.02")
    min_odds: Decimal = Decimal("1.50")
    max_odds: Decimal = Decimal("6.00")
    # Quarter Kelly.
    kelly_multiplier: Decimal = Decimal("0.25")
    # Stakes are whole dollars; anything smaller after the caps is not suggested.
    min_stake: Decimal = Decimal("1")
    approval_window: timedelta = field(default=timedelta(minutes=60))
    # Correlation guard: bets per match, unless the owner allows more for that match.
    max_bets_per_match: int = 1

    def __post_init__(self) -> None:
        for name, value in self.as_numbers().items():
            low, high = BOUNDS[name]
            if not low <= value <= high:
                raise ValueError(f"{name} must be between {low} and {high}, got {value}")
        if self.min_odds >= self.max_odds:
            raise ValueError("min_odds must be below max_odds")
        if self.min_odds_edge >= self.min_edge:
            raise ValueError("min_odds_edge must be below min_edge")

    def as_numbers(self) -> dict[str, Decimal]:
        """Every limit as a number, keyed by the name used in storage and the API."""
        values: dict[str, Decimal] = {}
        for f in fields(self):
            raw = getattr(self, f.name)
            if f.name == "approval_window":
                values["approval_window_minutes"] = Decimal(int(raw.total_seconds() // 60))
            else:
                values[f.name] = Decimal(raw)
        return values

    def with_overrides(self, overrides: Mapping[str, Decimal]) -> SafetyLimits:
        """Apply stored owner settings on top of these limits. Unknown names are an error."""
        changes: dict[str, object] = {}
        for name, value in overrides.items():
            if name not in BOUNDS:
                raise ValueError(f"unknown limit: {name}")
            if name == "approval_window_minutes":
                changes["approval_window"] = timedelta(minutes=int(value))
            elif name == "max_bets_per_match":
                changes[name] = int(value)
            else:
                changes[name] = Decimal(value)
        return replace(self, **changes)  # type: ignore[arg-type]


DEFAULT_LIMITS = SafetyLimits()
