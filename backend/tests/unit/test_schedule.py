from datetime import UTC, datetime, timedelta

import pytest

from edgewise.feeds.schedule import BETFAIR_SCHEDULE, ODDS_SCHEDULE, is_due, poll_interval

NOW = datetime(2026, 11, 7, 9, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("to_kickoff", "odds", "betfair"),
    [
        (timedelta(days=5), timedelta(minutes=30), timedelta(minutes=15)),
        (timedelta(hours=48), timedelta(minutes=30), timedelta(minutes=15)),
        (timedelta(hours=47), timedelta(minutes=10), timedelta(minutes=5)),
        (timedelta(hours=6), timedelta(minutes=10), timedelta(minutes=5)),
        (timedelta(hours=5), timedelta(minutes=5), timedelta(minutes=1)),
        (timedelta(minutes=59), timedelta(minutes=2), timedelta(seconds=30)),
        (timedelta(minutes=-5), timedelta(minutes=2), timedelta(seconds=30)),
    ],
)
def test_polling_speeds_up_towards_kickoff(
    to_kickoff: timedelta, odds: timedelta, betfair: timedelta
) -> None:
    assert poll_interval(to_kickoff, ODDS_SCHEDULE) == odds
    assert poll_interval(to_kickoff, BETFAIR_SCHEDULE) == betfair


def test_is_due() -> None:
    every = timedelta(minutes=10)
    assert is_due(None, every, NOW)
    assert not is_due(NOW - timedelta(minutes=9), every, NOW)
    assert is_due(NOW - timedelta(minutes=10), every, NOW)
