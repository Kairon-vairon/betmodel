"""Betfair Exchange client (read-only), against sample replies in its documented format."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal as D
from pathlib import Path
from typing import Any

import httpx
import pytest

from edgewise.domain.markets import MarketType as M
from edgewise.domain.markets import Selection as S
from edgewise.feeds.betfair import (
    BetfairClient,
    certificate_context,
    parse_catalogue_market,
    parse_market_book,
    to_groups,
)
from edgewise.feeds.common import FeedAuthError, make_http

START = "2026-11-07T15:00:00.000Z"


def catalogue_item(market_id: str, runners: list[tuple[int, str, float]]) -> dict[str, Any]:
    return {
        "marketId": market_id,
        "marketName": "x",
        "marketStartTime": START,
        "totalMatched": 1234.5,
        "runners": [
            {"selectionId": sid, "runnerName": name, "handicap": hc, "sortPriority": i}
            for i, (sid, name, hc) in enumerate(runners, start=1)
        ],
        "event": {
            "id": "34567890",
            "name": "Brighton v Everton",
            "countryCode": "GB",
            "openDate": START,
        },
        "competition": {"id": "10932509", "name": "English Premier League"},
    }


def book_item(
    market_id: str, prices: list[tuple[int, float, float | None, float | None]], **extra: Any
) -> dict[str, Any]:
    return {
        "marketId": market_id,
        "isMarketDataDelayed": extra.get("delayed", False),
        "status": extra.get("status", "OPEN"),
        "inplay": extra.get("inplay", False),
        "totalMatched": 98765.4,
        "runners": [
            {
                "selectionId": sid,
                "handicap": hc,
                "status": "ACTIVE",
                "ex": {
                    "availableToBack": [] if back is None else [{"price": back, "size": 120.5}],
                    "availableToLay": [] if lay is None else [{"price": lay, "size": 98.0}],
                    "tradedVolume": [],
                },
            }
            for sid, hc, back, lay in prices
        ],
    }


MATCH_ODDS = catalogue_item(
    "1.1", [(51, "Brighton", 0), (45, "Everton", 0), (58805, "The Draw", 0)]
)
MATCH_BOOK = book_item("1.1", [(51, 0, 1.84, 1.85), (45, 0, 4.9, 5.0), (58805, 0, 3.75, 3.8)])


def test_match_odds_become_one_market_with_three_outcomes() -> None:
    market = parse_catalogue_market(MATCH_ODDS, "MATCH_ODDS")
    book = parse_market_book(MATCH_BOOK)
    assert market is not None and book is not None
    assert market.start_time == datetime(2026, 11, 7, 15, 0, tzinfo=UTC)
    (group,) = to_groups(market, book)
    assert (group.market_type, group.line) == (M.MATCH_RESULT, None)
    quotes = {q.selection: (q.back, q.lay) for q in group.quotes}
    assert quotes == {
        S.HOME: (D("1.84"), D("1.85")),
        S.AWAY: (D("4.9"), D("5.0")),
        S.DRAW: (D("3.75"), D("3.8")),
    }


@pytest.mark.parametrize(
    ("market_type", "runners", "expected"),
    [
        (
            "OVER_UNDER_25",
            [(1, "Under 2.5 Goals", 0), (2, "Over 2.5 Goals", 0)],
            (M.TOTAL_GOALS, D("2.5"), {S.UNDER, S.OVER}),
        ),
        (
            "BOTH_TEAMS_TO_SCORE",
            [(1, "Yes", 0), (2, "No", 0)],
            (M.BOTH_TEAMS_TO_SCORE, None, {S.YES, S.NO}),
        ),
        (
            "DRAW_NO_BET",
            [(51, "Brighton", 0), (45, "Everton", 0)],
            (M.DRAW_NO_BET, None, {S.HOME, S.AWAY}),
        ),
    ],
)
def test_two_way_markets(
    market_type: str, runners: list[tuple[int, str, float]], expected: tuple[M, D | None, set[S]]
) -> None:
    market = parse_catalogue_market(catalogue_item("1.2", runners), market_type)
    book = parse_market_book(book_item("1.2", [(sid, 0, 1.9, 1.92) for sid, _, _ in runners]))
    assert market is not None and book is not None
    (group,) = to_groups(market, book)
    assert (group.market_type, group.line, {q.selection for q in group.quotes}) == expected


def test_asian_handicap_lines_are_paired_on_the_home_handicap() -> None:
    runners = [
        (51, "Brighton", -0.25),
        (45, "Everton", 0.25),
        (51, "Brighton", -0.5),
        (45, "Everton", 0.5),
        (51, "Brighton", -0.75),
    ]  # -0.75 has no away side
    market = parse_catalogue_market(catalogue_item("1.3", runners), "ASIAN_HANDICAP")
    book = parse_market_book(book_item("1.3", [(sid, hc, 1.9, 1.94) for sid, _, hc in runners]))
    assert market is not None and book is not None
    groups = to_groups(market, book)
    assert [(g.market_type, g.line) for g in groups] == [
        (M.ASIAN_HANDICAP, D("-0.5")),
        (M.ASIAN_HANDICAP, D("-0.25")),
    ]
    assert {q.selection for q in groups[0].quotes} == {S.HOME, S.AWAY}


@pytest.mark.parametrize(
    "book",
    [
        book_item(
            "1.1",
            [(51, 0, 1.84, 1.85), (45, 0, 4.9, 5.0), (58805, 0, 3.75, 3.8)],
            status="SUSPENDED",
        ),
        book_item(
            "1.1", [(51, 0, 1.84, 1.85), (45, 0, 4.9, 5.0), (58805, 0, 3.75, 3.8)], inplay=True
        ),
        book_item("1.1", [(51, 0, 1.84, 1.85), (45, 0, 4.9, 5.0)]),  # draw not priced
    ],
)
def test_unusable_markets_give_nothing(book: dict[str, Any]) -> None:
    market = parse_catalogue_market(MATCH_ODDS, "MATCH_ODDS")
    parsed = parse_market_book(book)
    assert market is not None and parsed is not None
    assert to_groups(market, parsed) == []


def test_unknown_runner_name_gives_nothing() -> None:
    odd = catalogue_item(
        "1.1", [(51, "Brighton & HA", 0), (45, "Everton", 0), (58805, "The Draw", 0)]
    )
    market = parse_catalogue_market(odd, "MATCH_ODDS")
    book = parse_market_book(MATCH_BOOK)
    assert market is not None and book is not None
    assert to_groups(market, book) == []


def test_delayed_key_is_flagged() -> None:
    book = parse_market_book(book_item("1.1", [(51, 0, 1.84, 1.85)], delayed=True))
    assert book is not None and book.delayed is True


class FakeBetfair:
    """Plays the identity and betting endpoints."""

    def __init__(self, *, expire_first_call: bool = False, login_ok: bool = True) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.logins = 0
        self.expire_first_call = expire_first_call
        self.login_ok = login_ok

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/login") or path.endswith("/certlogin"):
            self.logins += 1
            form = dict(x.split("=") for x in request.content.decode().split("&"))
            self.calls.append((path, form))
            if not self.login_ok:
                return httpx.Response(
                    200,
                    json={"token": "", "status": "FAIL", "error": "INVALID_USERNAME_OR_PASSWORD"},
                )
            if path.endswith("/certlogin"):
                return httpx.Response(
                    200, json={"sessionToken": f"S{self.logins}", "loginStatus": "SUCCESS"}
                )
            return httpx.Response(
                200, json={"token": f"T{self.logins}", "status": "SUCCESS", "error": ""}
            )
        body = json.loads(request.content)
        self.calls.append(
            (
                path,
                {
                    "body": body,
                    "auth": request.headers.get("x-authentication"),
                    "app": request.headers.get("x-application"),
                },
            )
        )
        if self.expire_first_call:
            self.expire_first_call = False
            return httpx.Response(
                400,
                json={
                    "faultcode": "Client",
                    "faultstring": "ANGX-0003",
                    "detail": {"APINGException": {"errorCode": "INVALID_SESSION_INFORMATION"}},
                },
            )
        if path.endswith("/listMarketCatalogue/"):
            return httpx.Response(
                200,
                json=[MATCH_ODDS] if body["filter"]["marketTypeCodes"] == ["MATCH_ODDS"] else [],
            )
        if path.endswith("/listMarketBook/"):
            return httpx.Response(200, json=[book_item(m, []) for m in body["marketIds"]])
        return httpx.Response(404)


def client(fake: FakeBetfair, *, cert: bool = False) -> BetfairClient:
    http = make_http(transport=httpx.MockTransport(fake))
    return BetfairClient(
        app_key="APPKEY",
        username="owner",
        password="pw",
        http=http,
        cert_http=http if cert else None,
    )


def test_login_then_catalogue_one_call_per_market_type() -> None:
    fake = FakeBetfair()
    bf = client(fake)
    markets = bf.catalogue(
        ["10932509"], datetime(2026, 11, 7, tzinfo=UTC), datetime(2026, 11, 14, tzinfo=UTC)
    )
    assert [m.market_id for m in markets] == ["1.1"]
    login_path, form = fake.calls[0]
    assert login_path.endswith("/api/login") and form == {"username": "owner", "password": "pw"}
    catalogue_calls = [c for c in fake.calls if c[0].endswith("/listMarketCatalogue/")]
    assert len(catalogue_calls) == 5
    first = catalogue_calls[0][1]
    assert first["auth"] == "T1" and first["app"] == "APPKEY"
    assert first["body"]["filter"]["eventTypeIds"] == ["1"]
    assert first["body"]["filter"]["marketStartTime"] == {
        "from": "2026-11-07T00:00:00Z",
        "to": "2026-11-14T00:00:00Z",
    }


def test_certificate_login_when_configured() -> None:
    fake = FakeBetfair()
    bf = client(fake, cert=True)
    bf.login()
    assert fake.calls[0][0].endswith("/api/certlogin") and bf.session_token == "S1"


def test_books_are_fetched_in_batches_of_40() -> None:
    fake = FakeBetfair()
    books = client(fake).books([f"1.{i}" for i in range(45)])
    batches = [
        len(c[1]["body"]["marketIds"]) for c in fake.calls if c[0].endswith("/listMarketBook/")
    ]
    assert batches == [40, 5] and len(books) == 45


def test_expired_session_logs_in_again_once() -> None:
    fake = FakeBetfair(expire_first_call=True)
    bf = client(fake)
    bf.books(["1.1"])
    assert fake.logins == 2 and bf.session_token == "T2"


def test_refused_login_is_an_auth_error() -> None:
    with pytest.raises(FeedAuthError, match="INVALID_USERNAME_OR_PASSWORD"):
        client(FakeBetfair(login_ok=False)).login()


def test_certificate_folder_must_hold_one_pair(tmp_path: Path) -> None:
    with pytest.raises(FeedAuthError, match=r"exactly one \.crt and one \.key"):
        certificate_context(tmp_path)
