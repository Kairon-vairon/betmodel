"""How old a price may be before it is treated as stale (CLAUDE.md rule 7).

Thresholds follow the adaptive scan schedule in docs/ARCHITECTURE.md, with room for the
odds feed's own refresh interval (about 5 minutes before kick-off). A stale price never
produces a suggestion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass(frozen=True)
class FreshnessBand:
    min_time_to_kickoff: timedelta  # band applies when at least this long before kick-off
    bookmaker_max_age: timedelta
    exchange_max_age: timedelta


def _default_bands() -> tuple[FreshnessBand, ...]:
    return (
        FreshnessBand(timedelta(hours=48), timedelta(minutes=75), timedelta(minutes=45)),
        FreshnessBand(timedelta(hours=6), timedelta(minutes=30), timedelta(minutes=15)),
        FreshnessBand(timedelta(hours=1), timedelta(minutes=15), timedelta(minutes=5)),
        FreshnessBand(timedelta(0), timedelta(minutes=10), timedelta(minutes=2)),
    )


@dataclass(frozen=True)
class FreshnessPolicy:
    bands: tuple[FreshnessBand, ...] = field(default_factory=_default_bands)

    def __post_init__(self) -> None:
        starts = [b.min_time_to_kickoff for b in self.bands]
        if not starts or starts != sorted(starts, reverse=True) or starts[-1] != timedelta(0):
            raise ValueError("bands must be sorted from furthest to nearest and end at 0")

    def band(self, now: datetime, kickoff: datetime) -> FreshnessBand:
        to_go = kickoff - now
        for band in self.bands:
            if to_go >= band.min_time_to_kickoff:
                return band
        return self.bands[-1]  # after kick-off: strictest band

    def bookmaker_fresh(self, as_of: datetime, now: datetime, kickoff: datetime) -> bool:
        return now - as_of <= self.band(now, kickoff).bookmaker_max_age

    def exchange_fresh(self, as_of: datetime, now: datetime, kickoff: datetime) -> bool:
        return now - as_of <= self.band(now, kickoff).exchange_max_age


DEFAULT_FRESHNESS = FreshnessPolicy()
