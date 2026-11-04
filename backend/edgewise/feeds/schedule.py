"""How often to ask each feed, by time to kick-off (docs/ARCHITECTURE.md).

Prices move most in the last hours, so polling speeds up as kick-off nears. The odds
feed refreshes about every 5 minutes before kick-off, so asking it more often than every
2 minutes only spends credits.
"""

from __future__ import annotations

from datetime import datetime, timedelta

Schedule = tuple[
    tuple[timedelta, timedelta], ...
]  # (at least this long before kick-off, poll every)

ODDS_SCHEDULE: Schedule = (
    (timedelta(hours=48), timedelta(minutes=30)),
    (timedelta(hours=6), timedelta(minutes=10)),
    (timedelta(hours=1), timedelta(minutes=5)),
    (timedelta(0), timedelta(minutes=2)),
)
BETFAIR_SCHEDULE: Schedule = (
    (timedelta(hours=48), timedelta(minutes=15)),
    (timedelta(hours=6), timedelta(minutes=5)),
    (timedelta(hours=1), timedelta(minutes=1)),
    (timedelta(0), timedelta(seconds=30)),
)
FIXTURES_EVERY = timedelta(hours=6)
RESULTS_EVERY = timedelta(minutes=15)  # while a match that should be over has no result
CATALOGUE_EVERY = timedelta(minutes=30)  # which Betfair markets exist
FINDER_EVERY = timedelta(minutes=1)
RETRY_AFTER_FAILURE = timedelta(minutes=1)
RESULTS_AFTER_KICKOFF = timedelta(minutes=105)  # 90 minutes, half-time and stoppage


def poll_interval(time_to_kickoff: timedelta, schedule: Schedule) -> timedelta:
    for starts_at, every in schedule:
        if time_to_kickoff >= starts_at:
            return every
    return schedule[-1][1]


def is_due(last: datetime | None, every: timedelta, now: datetime) -> bool:
    return last is None or now - last >= every
