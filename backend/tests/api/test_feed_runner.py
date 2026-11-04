"""The worker's feed tick: fixtures, Betfair, bookmaker odds, then the value finder."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from edgewise.config import Settings
from edgewise.db.models import (
    Bookmaker,
    Competition,
    Event,
    EventStatus,
    LedgerKind,
    Notification,
    Signal,
)
from edgewise.db.session import transaction
from edgewise.domain.markets import MarketType as M
from edgewise.domain.markets import Selection as S
from edgewise.feeds.api_football import FixtureRecord, FixturesResponse, TeamRef
from edgewise.feeds.betfair import CatalogueMarket, CatalogueRunner, MarketBook, RunnerBook
from edgewise.feeds.common import FeedError, Quota
from edgewise.feeds.odds_api import BookPrice, OddsEvent, OddsResponse
from edgewise.services import portfolio
from edgewise.services.feeds import ODDS, paused_feeds
from edgewise.worker.feeds import FeedRunner
from tests.conftest import FakeClock

KICKOFF = datetime(2026, 11, 7, 15, 0, tzinfo=UTC)  # clock starts 7 hours before


class FakeFootball:
    def __init__(self) -> None:
        self.calls = 0
        self.status, self.goals = EventStatus.SCHEDULED, (None, None)

    def fixtures(self, *, league_id: int, season: int, date_from: date, date_to: date) -> Any:
        self.calls += 1
        record = FixtureRecord(
            1,
            league_id,
            KICKOFF,
            self.status,
            TeamRef(51, "Brighton"),
            TeamRef(45, "Everton"),
            self.goals[0],
            self.goals[1],
        )
        return FixturesResponse([record], Quota(remaining=99))


class FakeOdds:
    def __init__(self) -> None:
        self.calls = 0
        self.error: Exception | None = None

    def odds(self, sport_key: str) -> Any:
        self.calls += 1
        if self.error is not None:
            raise self.error
        prices = (BookPrice("sportsbet", M.MATCH_RESULT, None, S.HOME, D("1.95"), KICKOFF),)
        event = OddsEvent("oa1", "Brighton and Hove Albion", "Everton", KICKOFF, prices)
        return OddsResponse([event], Quota(remaining=450))


class FakeBetfair:
    def __init__(self) -> None:
        self.catalogue_calls = 0
        self.book_calls = 0

    def catalogue(self, ids: Any, start_from: datetime, start_to: datetime) -> Any:
        self.catalogue_calls += 1
        runners = (
            CatalogueRunner(51, "Brighton", D(0), 1),
            CatalogueRunner(45, "Everton", D(0), 2),
            CatalogueRunner(58805, "The Draw", D(0), 3),
        )
        return [
            CatalogueMarket(
                "1.1", "MATCH_ODDS", KICKOFF, "bf-1", "Brighton v Everton", "10932509", runners
            )
        ]

    def books(self, market_ids: Any) -> Any:
        self.book_calls += 1
        runners = (
            RunnerBook(51, D(0), "ACTIVE", D("1.84"), D("100"), D("1.85"), D("100")),
            RunnerBook(45, D(0), "ACTIVE", D("4.9"), D("100"), D("5.0"), D("100")),
            RunnerBook(58805, D(0), "ACTIVE", D("3.75"), D("100"), D("3.8"), D("100")),
        )
        return [MarketBook(m, "OPEN", False, False, D("5000"), runners) for m in market_ids]


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(KICKOFF - timedelta(hours=7))


@pytest.fixture
def world(session_factory: sessionmaker[Session], clock: FakeClock) -> None:
    with transaction(session_factory) as session:
        session.add(
            Competition(
                code="EPL",
                name="Premier League",
                country="England",
                betfair_competition_id="10932509",
                odds_api_sport_key="soccer_epl",
                api_football_league_id=39,
            )
        )
        session.add(Bookmaker(key="sportsbet", name="Sportsbet"))
        session.flush()
        portfolio.add_ledger_entry(
            session, kind=LedgerKind.DEPOSIT, amount=D("2186.90"), now=clock(), actor="owner"
        )


def runner(
    settings: Settings, factory: sessionmaker[Session], clock: FakeClock, **clients: Any
) -> FeedRunner:
    return FeedRunner(settings, factory, clock=clock, **clients)


def count(factory: sessionmaker[Session], model: type, *where: Any) -> int:
    with factory() as session:
        return session.scalar(select(func.count()).select_from(model).where(*where)) or 0


def test_one_tick_goes_from_fixtures_to_a_suggested_bet(
    world: None, settings: Settings, session_factory: sessionmaker[Session], clock: FakeClock
) -> None:
    football, odds, betfair = FakeFootball(), FakeOdds(), FakeBetfair()
    report = runner(
        settings, session_factory, clock, football=football, odds=odds, betfair=betfair
    ).tick()
    assert report.errors == []
    assert (report.fixtures, report.exchange_books, report.odds_events) == (1, 1, 1)
    assert report.signals == 1
    assert count(session_factory, Signal) == 1
    assert (football.calls, betfair.catalogue_calls, betfair.book_calls, odds.calls) == (1, 1, 1, 1)


def test_polling_follows_the_schedule(
    world: None, settings: Settings, session_factory: sessionmaker[Session], clock: FakeClock
) -> None:
    football, odds, betfair = FakeFootball(), FakeOdds(), FakeBetfair()
    feeds = runner(settings, session_factory, clock, football=football, odds=odds, betfair=betfair)
    feeds.tick()
    clock.advance(minutes=1)
    feeds.tick()  # 6-48 hours out: odds every 10 min, Betfair every 5 min
    assert (odds.calls, betfair.book_calls, football.calls) == (1, 1, 1)
    clock.advance(minutes=4)
    feeds.tick()
    assert (odds.calls, betfair.book_calls) == (1, 2)
    clock.advance(minutes=5)
    feeds.tick()
    assert (odds.calls, betfair.book_calls) == (2, 3)


def test_a_failing_feed_pauses_after_three_tries_with_one_notice(
    world: None, settings: Settings, session_factory: sessionmaker[Session], clock: FakeClock
) -> None:
    odds = FakeOdds()
    odds.error = FeedError("The Odds API request failed (HTTP 500)")
    feeds = runner(
        settings, session_factory, clock, football=FakeFootball(), odds=odds, betfair=FakeBetfair()
    )
    for _ in range(5):
        report = feeds.tick()
        clock.advance(minutes=10)
    assert odds.calls == 5 and report.errors
    with session_factory() as session:
        assert paused_feeds(session) == {ODDS}
    assert count(session_factory, Notification, Notification.kind == "feed_paused") == 1
    assert count(session_factory, Signal) == 0  # no bookmaker prices: nothing to suggest


def test_results_are_fetched_after_the_match(
    world: None, settings: Settings, session_factory: sessionmaker[Session], clock: FakeClock
) -> None:
    football = FakeFootball()
    feeds = runner(settings, session_factory, clock, football=football)
    feeds.tick()
    clock.now = KICKOFF + timedelta(minutes=110)
    football.status, football.goals = EventStatus.FINISHED, (2, 1)
    feeds.tick()
    assert football.calls == 2
    with session_factory() as session:
        event = session.scalars(select(Event)).one()
        assert (event.status, event.home_goals, event.away_goals) == (EventStatus.FINISHED, 2, 1)
    clock.advance(minutes=5)
    feeds.tick()  # result in: no more polling for it
    assert football.calls == 2


def test_feeds_without_keys_are_skipped(
    world: None, settings: Settings, session_factory: sessionmaker[Session], clock: FakeClock
) -> None:
    feeds = FeedRunner.from_settings(settings, session_factory, clock=clock)
    assert feeds.configured() == {"fixtures": False, "odds_feed": False, "betfair": False}
    report = feeds.tick()
    assert report.errors == [] and report.signals == 0


class DownFootball(FakeFootball):
    def fixtures(self, **kwargs: Any) -> Any:
        self.calls += 1
        raise FeedError("Couldn't reach API-Football (ConnectError)")


def test_an_outage_counts_once_per_tick_not_once_per_league(
    world: None, settings: Settings, session_factory: sessionmaker[Session], clock: FakeClock
) -> None:
    with transaction(session_factory) as session:
        for code, league in (("LALIGA", 140), ("SERIEA", 135), ("BUNDESLIGA", 78)):
            session.add(
                Competition(code=code, name=code, country="x", api_football_league_id=league)
            )
    football = DownFootball()
    feeds = runner(settings, session_factory, clock, football=football)
    feeds.tick()
    assert football.calls == 1  # the other three leagues aren't tried during the outage
    with session_factory() as session:
        assert paused_feeds(session) == set()
    for _ in range(2):
        clock.advance(minutes=1)
        feeds.tick()
    assert football.calls == 3
    with session_factory() as session:
        assert paused_feeds(session) == {"fixtures"}
    assert count(session_factory, Notification, Notification.kind == "feed_paused") == 1
