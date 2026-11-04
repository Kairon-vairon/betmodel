"""Betfair Exchange API, read-only: the reference prices for fair probabilities.

Phase 1 never places a bet on Betfair: this client can only log in and read markets and
prices (CLAUDE.md rule 1). Login uses the certificate endpoint when a certificate folder
is configured (recommended for unattended use), otherwise the username/password one.
"""

from __future__ import annotations

import ssl
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

from edgewise import __version__
from edgewise.domain.markets import MarketType, Selection
from edgewise.feeds.common import (
    FeedAuthError,
    FeedError,
    FeedRateLimited,
    parse_time,
    to_odds,
)
from edgewise.feeds.matching import split_event_name

IDENTITY_URL = "https://identitysso.betfair.com.au/api"
CERT_IDENTITY_URL = "https://identitysso-cert.betfair.com.au/api"
BETTING_URL = "https://api.betfair.com/exchange/betting/rest/v1.0"
SOCCER = "1"
MARKET_TYPES = (
    "MATCH_ODDS",
    "OVER_UNDER_25",
    "BOTH_TEAMS_TO_SCORE",
    "DRAW_NO_BET",
    "ASIAN_HANDICAP",
)
BOOK_BATCH = 40  # stays inside Betfair's per-request data limit for best prices
_SESSION_ERRORS = {"INVALID_SESSION_INFORMATION", "NO_SESSION"}
_KEY_ERRORS = {"INVALID_APP_KEY", "NO_APP_KEY", "APP_KEY_CREATION_FAILED", "ACCESS_DENIED"}


@dataclass(frozen=True)
class CatalogueRunner:
    selection_id: int
    name: str
    handicap: Decimal
    sort_priority: int


@dataclass(frozen=True)
class CatalogueMarket:
    market_id: str
    market_type: str
    start_time: datetime
    event_id: str
    event_name: str
    competition_id: str | None
    runners: tuple[CatalogueRunner, ...]


@dataclass(frozen=True)
class RunnerBook:
    selection_id: int
    handicap: Decimal
    status: str
    back: Decimal | None
    back_size: Decimal | None
    lay: Decimal | None
    lay_size: Decimal | None


@dataclass(frozen=True)
class MarketBook:
    market_id: str
    status: str
    inplay: bool
    delayed: bool  # True with a delayed (development) app key
    total_matched: Decimal | None
    runners: tuple[RunnerBook, ...]


def certificate_context(cert_dir: Path) -> ssl.SSLContext:
    """TLS context with the Betfair client certificate (one .crt and one .key file)."""
    crts, keys = sorted(cert_dir.glob("*.crt")), sorted(cert_dir.glob("*.key"))
    if len(crts) != 1 or len(keys) != 1:
        raise FeedAuthError(f"Put exactly one .crt and one .key file in {cert_dir}")
    context = ssl.create_default_context()
    context.load_cert_chain(certfile=str(crts[0]), keyfile=str(keys[0]))
    return context


class BetfairClient:
    def __init__(
        self,
        *,
        app_key: str,
        username: str,
        password: str,
        http: httpx.Client,
        cert_http: httpx.Client | None = None,
        identity_url: str = IDENTITY_URL,
        cert_identity_url: str = CERT_IDENTITY_URL,
        betting_url: str = BETTING_URL,
    ) -> None:
        self._app_key = app_key
        self._username = username
        self._password = password
        self._http = http
        self._cert_http = cert_http
        self._identity_url = identity_url.rstrip("/")
        self._cert_identity_url = cert_identity_url.rstrip("/")
        self._betting_url = betting_url.rstrip("/")
        self.session_token: str | None = None

    def login(self) -> None:
        headers = {"X-Application": self._app_key, "Accept": "application/json"}
        form = {"username": self._username, "password": self._password}
        try:
            if self._cert_http is not None:
                response = self._cert_http.post(
                    f"{self._cert_identity_url}/certlogin", data=form, headers=headers
                )
            else:
                response = self._http.post(
                    f"{self._identity_url}/login", data=form, headers=headers
                )
        except httpx.HTTPError as exc:
            raise FeedError(f"Couldn't reach Betfair to log in ({type(exc).__name__})") from None
        try:
            body = response.json()
        except ValueError:
            raise FeedError(f"Betfair login failed (HTTP {response.status_code})") from None
        status = body.get("loginStatus") or body.get("status")
        token = body.get("sessionToken") or body.get("token")
        if status != "SUCCESS" or not token:
            reason = body.get("error") or status or f"HTTP {response.status_code}"
            raise FeedAuthError(f"Betfair refused the login: {reason}")
        self.session_token = str(token)

    def _call(self, operation: str, body: dict[str, Any]) -> Any:
        if self.session_token is None:
            self.login()
        for attempt in (1, 2):
            headers = {
                "X-Application": self._app_key,
                "X-Authentication": self.session_token or "",
                "Accept": "application/json",
                "User-Agent": f"Edgewise/{__version__}",
            }
            try:
                response = self._http.post(
                    f"{self._betting_url}/{operation}/", json=body, headers=headers
                )
            except httpx.HTTPError as exc:
                raise FeedError(f"Couldn't reach Betfair ({type(exc).__name__})") from None
            if response.status_code == 200:
                return response.json()
            code = _api_error_code(response)
            if code in _SESSION_ERRORS and attempt == 1:
                self.session_token = None
                self.login()  # the session expired: log in again once
                continue
            if code in _KEY_ERRORS or response.status_code in (401, 403):
                raise FeedAuthError(f"Betfair refused the app key or session: {code}")
            if code == "TOO_MANY_REQUESTS" or response.status_code == 429:
                raise FeedRateLimited("Betfair says too many requests")
            raise FeedError(f"Betfair {operation} failed: {code or response.status_code}")
        raise FeedError(f"Betfair {operation} failed after logging in again")

    def catalogue(
        self, competition_ids: Sequence[str], start_from: datetime, start_to: datetime
    ) -> list[CatalogueMarket]:
        markets: list[CatalogueMarket] = []
        for market_type in MARKET_TYPES:  # one type per call keeps each request light
            body = {
                "filter": {
                    "eventTypeIds": [SOCCER],
                    "competitionIds": list(competition_ids),
                    "marketTypeCodes": [market_type],
                    "marketStartTime": {"from": _iso(start_from), "to": _iso(start_to)},
                },
                "marketProjection": [
                    "EVENT",
                    "COMPETITION",
                    "MARKET_START_TIME",
                    "RUNNER_DESCRIPTION",
                ],
                "maxResults": 1000,
                "sort": "FIRST_TO_START",
            }
            for item in self._call("listMarketCatalogue", body) or []:
                parsed = parse_catalogue_market(item, market_type)
                if parsed is not None:
                    markets.append(parsed)
        return markets

    def books(self, market_ids: Sequence[str]) -> list[MarketBook]:
        books: list[MarketBook] = []
        for start in range(0, len(market_ids), BOOK_BATCH):
            body = {
                "marketIds": list(market_ids[start : start + BOOK_BATCH]),
                "priceProjection": {
                    "priceData": ["EX_BEST_OFFERS"],
                    "exBestOffersOverrides": {"bestPricesDepth": 1},
                },
            }
            for item in self._call("listMarketBook", body) or []:
                parsed = parse_market_book(item)
                if parsed is not None:
                    books.append(parsed)
        return books


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _api_error_code(response: httpx.Response) -> str | None:
    try:
        body = response.json()
    except ValueError:
        return None
    detail = body.get("detail") if isinstance(body, dict) else None
    exception = (detail or {}).get("APINGException") if isinstance(detail, dict) else None
    code = (exception or {}).get("errorCode") if isinstance(exception, dict) else None
    return (
        str(code)
        if code
        else (
            str(body.get("faultstring"))
            if isinstance(body, dict) and body.get("faultstring")
            else None
        )
    )


def _decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value)) if value is not None else None
    except ArithmeticError:
        return None


def parse_catalogue_market(item: Any, market_type: str) -> CatalogueMarket | None:
    try:
        runners = tuple(
            CatalogueRunner(
                selection_id=int(r["selectionId"]),
                name=str(r["runnerName"]),
                handicap=Decimal(str(r.get("handicap", 0))) + 0,
                sort_priority=int(r.get("sortPriority", 0)),
            )
            for r in item["runners"]
        )
        competition = item.get("competition") or {}
        return CatalogueMarket(
            market_id=str(item["marketId"]),
            market_type=market_type,
            start_time=parse_time(item["marketStartTime"]),
            event_id=str(item["event"]["id"]),
            event_name=str(item["event"]["name"]),
            competition_id=str(competition["id"]) if competition.get("id") else None,
            runners=runners,
        )
    except (KeyError, TypeError, ValueError, ArithmeticError):
        return None


def _best(ladder: Any) -> tuple[Decimal | None, Decimal | None]:
    if not ladder:
        return None, None
    top = ladder[0]
    return to_odds(top.get("price")), _decimal(top.get("size"))


def parse_market_book(item: Any) -> MarketBook | None:
    try:
        runners = []
        for r in item.get("runners") or []:
            ex = r.get("ex") or {}
            back, back_size = _best(ex.get("availableToBack"))
            lay, lay_size = _best(ex.get("availableToLay"))
            runners.append(
                RunnerBook(
                    selection_id=int(r["selectionId"]),
                    handicap=Decimal(str(r.get("handicap", 0))) + 0,
                    status=str(r.get("status", "")),
                    back=back,
                    back_size=back_size,
                    lay=lay,
                    lay_size=lay_size,
                )
            )
        return MarketBook(
            market_id=str(item["marketId"]),
            status=str(item.get("status", "")),
            inplay=bool(item.get("inplay", False)),
            delayed=bool(item.get("isMarketDataDelayed", False)),
            total_matched=_decimal(item.get("totalMatched")),
            runners=tuple(runners),
        )
    except (KeyError, TypeError, ValueError, ArithmeticError):
        return None


@dataclass(frozen=True)
class ExchangeQuote:
    selection: Selection
    selection_id: int
    back: Decimal | None
    back_size: Decimal | None
    lay: Decimal | None
    lay_size: Decimal | None


@dataclass(frozen=True)
class ExchangeGroup:
    """One Edgewise market (type and line) with the exchange prices for each outcome."""

    market_type: MarketType
    line: Decimal | None
    quotes: tuple[ExchangeQuote, ...]


def _quote(selection: Selection, book: RunnerBook) -> ExchangeQuote:
    return ExchangeQuote(
        selection, book.selection_id, book.back, book.back_size, book.lay, book.lay_size
    )


def to_groups(market: CatalogueMarket, book: MarketBook) -> list[ExchangeGroup]:
    """Translate a Betfair market into Edgewise markets. Empty if it can't be used now
    (suspended, in play, closed) or its runners can't be identified with certainty."""
    if book.status != "OPEN" or book.inplay:
        return []
    names = split_event_name(market.event_name)
    if names is None:
        return []
    home_name, away_name = names
    prices = {(r.selection_id, r.handicap): r for r in book.runners if r.status == "ACTIVE"}

    def price(runner: CatalogueRunner) -> RunnerBook | None:
        return prices.get((runner.selection_id, runner.handicap))

    def side(runner: CatalogueRunner) -> Selection | None:
        if runner.name == home_name:
            return Selection.HOME
        if runner.name == away_name:
            return Selection.AWAY
        return None

    simple: dict[str, tuple[MarketType, Decimal | None]] = {
        "MATCH_ODDS": (MarketType.MATCH_RESULT, None),
        "OVER_UNDER_25": (MarketType.TOTAL_GOALS, Decimal("2.5")),
        "BOTH_TEAMS_TO_SCORE": (MarketType.BOTH_TEAMS_TO_SCORE, None),
        "DRAW_NO_BET": (MarketType.DRAW_NO_BET, None),
    }
    if market.market_type in simple:
        market_type, line = simple[market.market_type]
        quotes: list[ExchangeQuote] = []
        for runner in market.runners:
            selection = _simple_selection(market.market_type, runner, side)
            runner_book = price(runner)
            if selection is None or runner_book is None:
                return []  # every outcome must be identified and priced
            quotes.append(_quote(selection, runner_book))
        if len({q.selection for q in quotes}) != len(quotes):
            return []
        return [ExchangeGroup(market_type, line, tuple(quotes))]

    if market.market_type == "ASIAN_HANDICAP":
        groups: list[ExchangeGroup] = []
        homes = {r.handicap: r for r in market.runners if side(r) is Selection.HOME}
        aways = {r.handicap: r for r in market.runners if side(r) is Selection.AWAY}
        for handicap, home_runner in sorted(homes.items()):
            away_runner = aways.get(-handicap + 0)
            if away_runner is None:
                continue
            home_book, away_book = price(home_runner), price(away_runner)
            if home_book is None or away_book is None:
                continue
            groups.append(
                ExchangeGroup(
                    MarketType.ASIAN_HANDICAP,
                    handicap,
                    (_quote(Selection.HOME, home_book), _quote(Selection.AWAY, away_book)),
                )
            )
        return groups
    return []


def _simple_selection(market_type: str, runner: CatalogueRunner, side: Any) -> Selection | None:
    name = runner.name.strip().lower()
    if market_type == "MATCH_ODDS":
        if name in ("the draw", "draw"):
            return Selection.DRAW
        result: Selection | None = side(runner)
        return result
    if market_type == "OVER_UNDER_25":
        if name.startswith("over"):
            return Selection.OVER
        if name.startswith("under"):
            return Selection.UNDER
        return None
    if market_type == "BOTH_TEAMS_TO_SCORE":
        return {"yes": Selection.YES, "no": Selection.NO}.get(name)
    if market_type == "DRAW_NO_BET":
        result = side(runner)
        return result
    return None


def competition_ids(ids: Iterable[str | None]) -> list[str]:
    return sorted({i for i in ids if i})
