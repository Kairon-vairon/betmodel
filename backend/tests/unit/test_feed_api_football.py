"""API-Football client, against sample replies in its documented v3 format."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import httpx
import pytest

from edgewise.db.models import EventStatus
from edgewise.feeds.api_football import ApiFootballClient, parse_fixture, season_for
from edgewise.feeds.common import FeedAuthError, FeedRateLimited, make_http

KEY = "secret-football-key"
KICKOFF = int(datetime(2026, 11, 7, 15, 0, tzinfo=UTC).timestamp())


def fixture(
    fid: int,
    short: str,
    *,
    fulltime: tuple[Any, Any] = (None, None),
    goals: tuple[Any, Any] = (None, None),
) -> dict[str, Any]:
    return {
        "fixture": {
            "id": fid,
            "date": "2026-11-07T15:00:00+00:00",
            "timestamp": KICKOFF,
            "status": {"long": "", "short": short, "elapsed": None},
        },
        "league": {"id": 39, "season": 2026, "round": "Regular Season - 11"},
        "teams": {
            "home": {"id": 51, "name": "Brighton", "winner": None},
            "away": {"id": 45, "name": "Everton", "winner": None},
        },
        "goals": {"home": goals[0], "away": goals[1]},
        "score": {
            "halftime": {"home": None, "away": None},
            "fulltime": {"home": fulltime[0], "away": fulltime[1]},
            "extratime": {"home": None, "away": None},
            "penalty": {"home": None, "away": None},
        },
    }


def test_upcoming_match() -> None:
    record = parse_fixture(fixture(1001, "NS"))
    assert record is not None
    assert record.kickoff == datetime(2026, 11, 7, 15, 0, tzinfo=UTC)
    assert record.status is EventStatus.SCHEDULED
    assert (record.home.feed_id, record.home.name) == (51, "Brighton")
    assert (record.home_goals, record.away_goals) == (None, None)


def test_finished_match_uses_the_full_time_score() -> None:
    record = parse_fixture(fixture(1002, "FT", fulltime=(2, 1), goals=(2, 1)))
    assert record is not None and record.status is EventStatus.FINISHED
    assert (record.home_goals, record.away_goals) == (2, 1)


def test_after_extra_time_the_90_minute_score_counts() -> None:
    record = parse_fixture(fixture(1003, "AET", fulltime=(1, 1), goals=(2, 1)))
    assert record is not None and (record.home_goals, record.away_goals) == (1, 1)


def test_finished_without_a_score_waits_for_one() -> None:
    record = parse_fixture(fixture(1004, "FT"))
    assert record is not None and record.status is EventStatus.LIVE


@pytest.mark.parametrize(
    ("short", "status"),
    [
        ("PST", EventStatus.POSTPONED),
        ("CANC", EventStatus.CANCELLED),
        ("ABD", EventStatus.ABANDONED),
        ("AWD", EventStatus.ABANDONED),
        ("2H", EventStatus.LIVE),
    ],
)
def test_statuses(short: str, status: EventStatus) -> None:
    record = parse_fixture(fixture(1005, short))
    assert record is not None and record.status is status


def test_malformed_fixture_is_skipped() -> None:
    assert parse_fixture({"fixture": {"id": 1}}) is None


@pytest.mark.parametrize(
    ("day", "season"),
    [
        (date(2026, 11, 4), 2026),
        (date(2027, 3, 1), 2026),
        (date(2026, 7, 1), 2026),
        (date(2026, 6, 30), 2025),
    ],
)
def test_season_naming(day: date, season: int) -> None:
    assert season_for(day) == season


def client_for(handler: Any) -> ApiFootballClient:
    return ApiFootballClient(KEY, http=make_http(transport=httpx.MockTransport(handler)))


def test_request_uses_the_key_header_and_dates() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = {"get": "fixtures", "errors": [], "results": 1, "response": [fixture(1, "NS")]}
        return httpx.Response(200, json=body, headers={"x-ratelimit-requests-remaining": "97"})

    response = client_for(handler).fixtures(
        league_id=39, season=2026, date_from=date(2026, 11, 3), date_to=date(2026, 11, 14)
    )
    (request,) = seen
    assert request.url.path == "/fixtures"
    assert request.headers["x-apisports-key"] == KEY
    assert dict(request.url.params) == {
        "league": "39",
        "season": "2026",
        "from": "2026-11-03",
        "to": "2026-11-14",
        "timezone": "UTC",
    }
    assert response.quota.remaining == 97
    assert [f.feed_id for f in response.fixtures] == [1]


@pytest.mark.parametrize(
    ("errors", "error"),
    [
        ({"token": "Error/Missing application key."}, FeedAuthError),
        ({"requests": "You have reached the request limit for the day"}, FeedRateLimited),
    ],
)
def test_errors_reported_inside_a_200_reply(errors: dict[str, str], error: type[Exception]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errors": errors, "results": 0, "response": []})

    with pytest.raises(error) as info:
        client_for(handler).fixtures(
            league_id=39, season=2026, date_from=date(2026, 11, 3), date_to=date(2026, 11, 4)
        )
    assert KEY not in str(info.value)
