"""The Odds API (the-odds-api.com, v4): licensed bookmaker prices.

One request per league returns every upcoming match with each Australian bookmaker's
prices for the chosen markets. Each request costs (markets x regions) credits; the
remaining allowance comes back in the response headers.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

import httpx

from edgewise.domain.markets import MarketType, Selection, validate_line
from edgewise.feeds.common import (
    FeedAuthError,
    FeedError,
    FeedRateLimited,
    Quota,
    error_message,
    parse_time,
    to_int,
    to_odds,
)

DEFAULT_BASE_URL = "https://api.the-odds-api.com/v4"
MAIN_MARKETS = ("h2h", "totals", "spreads")


@dataclass(frozen=True)
class BookPrice:
    bookmaker_key: str
    market: MarketType
    line: Decimal | None
    selection: Selection
    odds: Decimal
    price_time: datetime  # when the feed last updated this price


@dataclass(frozen=True)
class OddsEvent:
    feed_event_id: str
    home: str
    away: str
    kickoff: datetime
    prices: tuple[BookPrice, ...]


@dataclass(frozen=True)
class OddsResponse:
    events: list[OddsEvent]
    quota: Quota


class OddsApiClient:
    def __init__(
        self,
        api_key: str,
        *,
        http: httpx.Client,
        base_url: str = DEFAULT_BASE_URL,
        regions: str = "au",
    ) -> None:
        self._key = api_key
        self._http = http
        self._base = base_url.rstrip("/")
        self._regions = regions

    def odds(self, sport_key: str, markets: Sequence[str] = MAIN_MARKETS) -> OddsResponse:
        params = {
            "apiKey": self._key,
            "regions": self._regions,
            "markets": ",".join(markets),
            "oddsFormat": "decimal",
            "dateFormat": "iso",
        }
        try:
            response = self._http.get(f"{self._base}/sports/{sport_key}/odds", params=params)
        except httpx.HTTPError as exc:
            raise FeedError(f"Couldn't reach The Odds API ({type(exc).__name__})") from None
        quota = Quota(
            remaining=to_int(response.headers.get("x-requests-remaining")),
            used=to_int(response.headers.get("x-requests-used")),
        )
        if response.status_code == 401:
            raise FeedAuthError(error_message(response, "The Odds API refused the key"))
        if response.status_code == 429:
            raise FeedRateLimited(error_message(response, "The Odds API allowance is used up"))
        if response.status_code >= 400:
            raise FeedError(error_message(response, "The Odds API request failed"))
        try:
            payload = response.json()
        except ValueError:
            raise FeedError("The Odds API sent something that isn't JSON") from None
        return OddsResponse(events=parse_odds_events(payload), quota=quota)


def parse_odds_events(payload: Any) -> list[OddsEvent]:
    if not isinstance(payload, list):
        raise FeedError("unexpected reply from The Odds API")
    events: list[OddsEvent] = []
    for item in payload:
        try:
            home, away = str(item["home_team"]), str(item["away_team"])
            kickoff = parse_time(item["commence_time"])
            event_id = str(item["id"])
        except (KeyError, TypeError, ValueError):
            continue  # a malformed match is skipped, not guessed at
        prices: list[BookPrice] = []
        for book in item.get("bookmakers") or []:
            book_key = book.get("key")
            if not isinstance(book_key, str):
                continue
            for market in book.get("markets") or []:
                stamp = market.get("last_update") or book.get("last_update")
                try:
                    price_time = parse_time(stamp)
                except (TypeError, ValueError):
                    continue
                for outcome in market.get("outcomes") or []:
                    parsed = _outcome(market.get("key"), outcome, home, away)
                    odds = to_odds(outcome.get("price"))
                    if parsed is None or odds is None:
                        continue
                    market_type, line, selection = parsed
                    prices.append(
                        BookPrice(book_key, market_type, line, selection, odds, price_time)
                    )
        events.append(OddsEvent(event_id, home, away, kickoff, tuple(prices)))
    return events


def _line(point: Any, market_type: MarketType) -> Decimal | None:
    try:
        return validate_line(market_type, Decimal(str(point)))
    except (ArithmeticError, TypeError, ValueError):
        return None


def _outcome(
    market_key: Any, outcome: dict[str, Any], home: str, away: str
) -> tuple[MarketType, Decimal | None, Selection] | None:
    name = outcome.get("name")
    if market_key == "h2h":
        if name == home:
            return MarketType.MATCH_RESULT, None, Selection.HOME
        if name == away:
            return MarketType.MATCH_RESULT, None, Selection.AWAY
        if isinstance(name, str) and name.lower() == "draw":
            return MarketType.MATCH_RESULT, None, Selection.DRAW
        return None
    if market_key == "totals":
        line = _line(outcome.get("point"), MarketType.TOTAL_GOALS)
        if line is None or name not in ("Over", "Under"):
            return None
        side = Selection.OVER if name == "Over" else Selection.UNDER
        return MarketType.TOTAL_GOALS, line, side
    if market_key == "spreads":
        point = _line(outcome.get("point"), MarketType.ASIAN_HANDICAP)
        if point is None:
            return None
        # Edgewise stores Asian handicap lines as the home team's handicap.
        if name == home:
            return MarketType.ASIAN_HANDICAP, point, Selection.HOME
        if name == away:
            return MarketType.ASIAN_HANDICAP, -point + 0, Selection.AWAY
        return None
    if market_key == "btts":
        if name in ("Yes", "No"):
            side = Selection.YES if name == "Yes" else Selection.NO
            return MarketType.BOTH_TEAMS_TO_SCORE, None, side
        return None
    if market_key == "draw_no_bet":
        if name == home:
            return MarketType.DRAW_NO_BET, None, Selection.HOME
        if name == away:
            return MarketType.DRAW_NO_BET, None, Selection.AWAY
    return None
