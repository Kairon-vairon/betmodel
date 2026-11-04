from datetime import UTC, datetime, timedelta

import pytest

from edgewise.domain.freshness import DEFAULT_FRESHNESS, FreshnessBand, FreshnessPolicy

NOW = datetime(2026, 11, 7, 10, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("to_kickoff", "bookmaker", "exchange"),
    [
        (timedelta(hours=72), timedelta(minutes=75), timedelta(minutes=45)),
        (timedelta(hours=48), timedelta(minutes=75), timedelta(minutes=45)),
        (timedelta(hours=47), timedelta(minutes=30), timedelta(minutes=15)),
        (timedelta(hours=3), timedelta(minutes=15), timedelta(minutes=5)),
        (timedelta(minutes=30), timedelta(minutes=10), timedelta(minutes=2)),
        (timedelta(minutes=-5), timedelta(minutes=10), timedelta(minutes=2)),
    ],
)
def test_bands_follow_time_to_kickoff(
    to_kickoff: timedelta, bookmaker: timedelta, exchange: timedelta
) -> None:
    band = DEFAULT_FRESHNESS.band(NOW, NOW + to_kickoff)
    assert (band.bookmaker_max_age, band.exchange_max_age) == (bookmaker, exchange)


def test_fresh_and_stale() -> None:
    kickoff = NOW + timedelta(minutes=30)
    assert DEFAULT_FRESHNESS.exchange_fresh(NOW - timedelta(minutes=2), NOW, kickoff)
    assert not DEFAULT_FRESHNESS.exchange_fresh(NOW - timedelta(minutes=2, seconds=1), NOW, kickoff)
    assert DEFAULT_FRESHNESS.bookmaker_fresh(NOW - timedelta(minutes=10), NOW, kickoff)
    assert not DEFAULT_FRESHNESS.bookmaker_fresh(NOW - timedelta(minutes=11), NOW, kickoff)


def test_bands_must_be_ordered_and_complete() -> None:
    with pytest.raises(ValueError):
        FreshnessPolicy(bands=(FreshnessBand(timedelta(hours=1), timedelta(1), timedelta(1)),))
