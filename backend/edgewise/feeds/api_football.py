"""API-Football (api-football.com, v3): fixtures and full-time results.

The reference list of matches. Results come from `score.fulltime`: the score after 90
minutes plus stoppage time, which is what every Phase 1 market is graded on.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import httpx

from edgewise.db.models import EventStatus
from edgewise.feeds.common import (
    FeedAuthError,
    FeedError,
    FeedRateLimited,
    Quota,
    error_message,
    to_int,
)

DEFAULT_BASE_URL = "https://v3.football.api-sports.io"

STATUS: dict[str, EventStatus] = {
    "TBD": EventStatus.SCHEDULED,
    "NS": EventStatus.SCHEDULED,
    "1H": EventStatus.LIVE,
    "HT": EventStatus.LIVE,
    "2H": EventStatus.LIVE,
    "ET": EventStatus.LIVE,
    "BT": EventStatus.LIVE,
    "P": EventStatus.LIVE,
    "SUSP": EventStatus.LIVE,
    "INT": EventStatus.LIVE,
    "LIVE": EventStatus.LIVE,
    "FT": EventStatus.FINISHED,
    "AET": EventStatus.FINISHED,
    "PEN": EventStatus.FINISHED,
    "PST": EventStatus.POSTPONED,
    "CANC": EventStatus.CANCELLED,
    "ABD": EventStatus.ABANDONED,
    # Awarded result / walkover: bookmakers usually void these. The owner can correct it.
    "AWD": EventStatus.ABANDONED,
    "WO": EventStatus.ABANDONED,
}


@dataclass(frozen=True)
class TeamRef:
    feed_id: int
    name: str


@dataclass(frozen=True)
class FixtureRecord:
    feed_id: int
    league_id: int
    kickoff: datetime
    status: EventStatus
    home: TeamRef
    away: TeamRef
    home_goals: int | None  # full time (90 minutes + stoppage), finished matches only
    away_goals: int | None


@dataclass(frozen=True)
class FixturesResponse:
    fixtures: list[FixtureRecord]
    quota: Quota


def season_for(day: date) -> int:
    """European seasons are named by the year they start (August)."""
    return day.year if day.month >= 7 else day.year - 1


class ApiFootballClient:
    def __init__(
        self, api_key: str, *, http: httpx.Client, base_url: str = DEFAULT_BASE_URL
    ) -> None:
        self._key = api_key
        self._http = http
        self._base = base_url.rstrip("/")

    def fixtures(
        self, *, league_id: int, season: int, date_from: date, date_to: date
    ) -> FixturesResponse:
        params: dict[str, str | int] = {
            "league": league_id,
            "season": season,
            "from": date_from.isoformat(),
            "to": date_to.isoformat(),
            "timezone": "UTC",
        }
        try:
            response = self._http.get(
                f"{self._base}/fixtures", params=params, headers={"x-apisports-key": self._key}
            )
        except httpx.HTTPError as exc:
            raise FeedError(f"Couldn't reach API-Football ({type(exc).__name__})") from None
        quota = Quota(remaining=to_int(response.headers.get("x-ratelimit-requests-remaining")))
        if response.status_code in (401, 403):
            raise FeedAuthError(error_message(response, "API-Football refused the key"))
        if response.status_code == 429:
            raise FeedRateLimited(error_message(response, "API-Football allowance is used up"))
        if response.status_code >= 400:
            raise FeedError(error_message(response, "API-Football request failed"))
        try:
            body = response.json()
        except ValueError:
            raise FeedError("API-Football sent something that isn't JSON") from None
        _raise_for_body_errors(body)
        items = body.get("response") if isinstance(body, dict) else None
        if not isinstance(items, list):
            raise FeedError("unexpected reply from API-Football")
        fixtures = [f for f in (parse_fixture(item) for item in items) if f is not None]
        return FixturesResponse(fixtures=fixtures, quota=quota)


def _raise_for_body_errors(body: Any) -> None:
    """API-Football reports some errors (bad key, daily limit) with HTTP 200."""
    errors = body.get("errors") if isinstance(body, dict) else None
    if not errors:
        return
    items = errors.items() if isinstance(errors, dict) else enumerate(errors)
    text = "; ".join(f"{k}: {v}" for k, v in items)
    lowered = text.lower()
    if any(word in lowered for word in ("token", "key", "access", "subscription")):
        raise FeedAuthError(f"API-Football refused the request: {text}")
    if any(word in lowered for word in ("requests", "limit")):
        raise FeedRateLimited(f"API-Football allowance is used up: {text}")
    raise FeedError(f"API-Football error: {text}")


def parse_fixture(item: Any) -> FixtureRecord | None:
    try:
        fixture, teams, league = item["fixture"], item["teams"], item["league"]
        kickoff = datetime.fromtimestamp(int(fixture["timestamp"]), UTC)
        status = STATUS.get(str(fixture["status"]["short"]), EventStatus.SCHEDULED)
        home = TeamRef(int(teams["home"]["id"]), str(teams["home"]["name"]))
        away = TeamRef(int(teams["away"]["id"]), str(teams["away"]["name"]))
        feed_id, league_id = int(fixture["id"]), int(league["id"])
    except (KeyError, TypeError, ValueError):
        return None
    home_goals = away_goals = None
    if status is EventStatus.FINISHED:
        fulltime = (item.get("score") or {}).get("fulltime") or {}
        home_goals, away_goals = fulltime.get("home"), fulltime.get("away")
        if home_goals is None or away_goals is None:
            goals = item.get("goals") or {}
            home_goals, away_goals = goals.get("home"), goals.get("away")
        if not isinstance(home_goals, int) or not isinstance(away_goals, int):
            # Finished but no score yet: keep it unfinished until the score arrives.
            status, home_goals, away_goals = EventStatus.LIVE, None, None
    return FixtureRecord(feed_id, league_id, kickoff, status, home, away, home_goals, away_goals)
