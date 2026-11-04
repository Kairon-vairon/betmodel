"""The Odds API client, against sample replies in its documented v4 format."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal as D
from typing import Any

import httpx
import pytest

from edgewise.domain.markets import MarketType as M
from edgewise.domain.markets import Selection as S
from edgewise.feeds.common import FeedAuthError, FeedError, FeedRateLimited, make_http
from edgewise.feeds.odds_api import OddsApiClient, parse_odds_events

KEY = "secret-odds-key"

SAMPLE: list[dict[str, Any]] = [
    {
        "id": "e912304de2b2ce35b473ce2ecd3d1502",
        "sport_key": "soccer_epl",
        "sport_title": "EPL",
        "commence_time": "2026-11-07T15:00:00Z",
        "home_team": "Brighton and Hove Albion",
        "away_team": "Everton",
        "bookmakers": [
            {
                "key": "sportsbet",
                "title": "SportsBet",
                "last_update": "2026-11-07T08:58:10Z",
                "markets": [
                    {
                        "key": "h2h",
                        "last_update": "2026-11-07T08:58:10Z",
                        "outcomes": [
                            {"name": "Brighton and Hove Albion", "price": 1.95},
                            {"name": "Everton", "price": 4.2},
                            {"name": "Draw", "price": 3.6},
                        ],
                    },
                    {
                        "key": "totals",
                        "last_update": "2026-11-07T08:57:00Z",
                        "outcomes": [
                            {"name": "Over", "price": 1.9, "point": 2.5},
                            {"name": "Under", "price": 1.92, "point": 2.5},
                        ],
                    },
                    {
                        "key": "spreads",
                        "last_update": "2026-11-07T08:56:00Z",
                        "outcomes": [
                            {"name": "Brighton and Hove Albion", "price": 1.95, "point": -0.25},
                            {"name": "Everton", "price": 1.9, "point": 0.25},
                        ],
                    },
                ],
            },
            {
                "key": "tab",
                "title": "TAB",
                "last_update": "2026-11-07T08:55:00Z",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Brighton and Hove Albion", "price": 1.9},
                            {"name": "Everton", "price": 1.0},  # nonsense price: dropped
                            {"name": "Draw", "price": "x"},  # unreadable price: dropped
                        ],
                    }
                ],
            },
        ],
    },
    {"id": "broken", "home_team": "A", "away_team": "B"},  # no kick-off: skipped
]


def test_parses_every_market_into_edgewise_terms() -> None:
    (event,) = parse_odds_events(SAMPLE)
    assert event.home == "Brighton and Hove Albion" and event.away == "Everton"
    assert event.kickoff == datetime(2026, 11, 7, 15, 0, tzinfo=UTC)
    got = {(p.bookmaker_key, p.market, p.line, p.selection): p.odds for p in event.prices}
    assert got == {
        ("sportsbet", M.MATCH_RESULT, None, S.HOME): D("1.95"),
        ("sportsbet", M.MATCH_RESULT, None, S.AWAY): D("4.2"),
        ("sportsbet", M.MATCH_RESULT, None, S.DRAW): D("3.6"),
        ("sportsbet", M.TOTAL_GOALS, D("2.5"), S.OVER): D("1.9"),
        ("sportsbet", M.TOTAL_GOALS, D("2.5"), S.UNDER): D("1.92"),
        # Both sides of an Asian handicap are stored on the home team's line.
        ("sportsbet", M.ASIAN_HANDICAP, D("-0.25"), S.HOME): D("1.95"),
        ("sportsbet", M.ASIAN_HANDICAP, D("-0.25"), S.AWAY): D("1.9"),
        ("tab", M.MATCH_RESULT, None, S.HOME): D("1.9"),
    }


def test_price_time_comes_from_the_market_or_bookmaker() -> None:
    (event,) = parse_odds_events(SAMPLE)
    times = {(p.bookmaker_key, p.market): p.price_time for p in event.prices}
    assert times[("sportsbet", M.TOTAL_GOALS)] == datetime(2026, 11, 7, 8, 57, tzinfo=UTC)
    assert times[("tab", M.MATCH_RESULT)] == datetime(2026, 11, 7, 8, 55, tzinfo=UTC)


def client_for(handler: Any) -> OddsApiClient:
    return OddsApiClient(KEY, http=make_http(transport=httpx.MockTransport(handler)))


def test_request_and_allowance() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        headers = {"x-requests-remaining": "19450", "x-requests-used": "550"}
        return httpx.Response(200, json=SAMPLE, headers=headers)

    response = client_for(handler).odds("soccer_epl")
    (request,) = seen
    assert request.url.path == "/v4/sports/soccer_epl/odds"
    assert dict(request.url.params) == {
        "apiKey": KEY,
        "regions": "au",
        "markets": "h2h,totals,spreads",
        "oddsFormat": "decimal",
        "dateFormat": "iso",
    }
    assert (response.quota.remaining, response.quota.used) == (19450, 550)
    assert len(response.events) == 1


@pytest.mark.parametrize(
    ("status", "error"),
    [(401, FeedAuthError), (429, FeedRateLimited), (500, FeedError), (422, FeedError)],
)
def test_errors_never_show_the_key(status: int, error: type[Exception]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"message": "Something went wrong"})

    with pytest.raises(error) as info:
        client_for(handler).odds("soccer_epl")
    assert KEY not in str(info.value)
    assert "Something went wrong" in str(info.value)


def test_network_failure_is_a_feed_error_without_the_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot connect to {request.url}")

    with pytest.raises(FeedError) as info:
        client_for(handler).odds("soccer_epl")
    assert KEY not in str(info.value)


def test_non_json_reply_is_a_feed_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>maintenance</html>")

    with pytest.raises(FeedError, match="isn't JSON"):
        client_for(handler).odds("soccer_epl")
