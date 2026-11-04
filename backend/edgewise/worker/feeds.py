"""Polling the data feeds on the adaptive schedule, then looking for value.

One tick does, in order: fixtures and results, Betfair markets and prices, bookmaker
odds, then the value finder. Steps run one after another (never at the same time), each
in its own transaction. A feed that isn't configured (no key) is simply skipped.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import partial
from pathlib import Path
from typing import TypeVar

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from edgewise.config import Settings
from edgewise.db.models import Competition, Event, EventStatus, ExchangeMarket
from edgewise.db.session import transaction
from edgewise.feeds.api_football import ApiFootballClient, season_for
from edgewise.feeds.betfair import BetfairClient, certificate_context
from edgewise.feeds.common import FeedError, make_http
from edgewise.feeds.odds_api import OddsApiClient
from edgewise.feeds.schedule import (
    BETFAIR_SCHEDULE,
    CATALOGUE_EVERY,
    FINDER_EVERY,
    FIXTURES_EVERY,
    ODDS_SCHEDULE,
    RESULTS_AFTER_KICKOFF,
    RESULTS_EVERY,
    RETRY_AFTER_FAILURE,
    is_due,
    poll_interval,
)
from edgewise.services.feeds import BETFAIR, FIXTURES, ODDS, feed_failed, feed_succeeded
from edgewise.services.ingest import ingest_books, ingest_catalogue, ingest_odds, sync_fixtures
from edgewise.services.value import run_value_finder

log = logging.getLogger("edgewise.worker.feeds")
T = TypeVar("T")
Clock = Callable[[], datetime]


@dataclass
class TickReport:
    fixtures: int = 0
    odds_events: int = 0
    exchange_books: int = 0
    signals: int = 0
    changed: bool = False
    errors: list[str] = field(default_factory=list)


class FeedRunner:
    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker[Session],
        *,
        clock: Clock,
        football: ApiFootballClient | None = None,
        odds: OddsApiClient | None = None,
        betfair: BetfairClient | None = None,
        betfair_error: Exception | None = None,
    ) -> None:
        self.settings = settings
        self.factory = session_factory
        self.clock = clock
        self.football, self.odds, self.betfair = football, odds, betfair
        self.betfair_error = betfair_error  # e.g. a bad certificate folder
        self.horizon = timedelta(days=settings.feed_horizon_days)
        self._last: dict[tuple[str, str], datetime] = {}

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        session_factory: sessionmaker[Session],
        *,
        clock: Clock,
        transport: httpx.BaseTransport | None = None,
    ) -> FeedRunner:
        http = make_http(transport=transport)
        football = odds = betfair = None
        betfair_error: Exception | None = None
        if settings.football_data_api_key:
            football = ApiFootballClient(
                settings.football_data_api_key.get_secret_value(),
                http=http,
                base_url=settings.api_football_url,
            )
        if settings.odds_api_key:
            odds = OddsApiClient(
                settings.odds_api_key.get_secret_value(),
                http=http,
                base_url=settings.odds_api_url,
                regions=settings.odds_api_regions,
            )
        if settings.betfair_configured:
            assert settings.betfair_app_key and settings.betfair_password
            cert_http = None
            if settings.betfair_cert_path:
                try:
                    context = certificate_context(Path(settings.betfair_cert_path))
                    cert_http = httpx.Client(verify=context, timeout=20.0, transport=transport)
                except (FeedError, OSError) as exc:
                    betfair_error = exc
            betfair = BetfairClient(
                app_key=settings.betfair_app_key.get_secret_value(),
                username=settings.betfair_username or "",
                password=settings.betfair_password.get_secret_value(),
                http=http,
                cert_http=cert_http,
                identity_url=settings.betfair_identity_url,
                cert_identity_url=settings.betfair_cert_identity_url,
                betting_url=settings.betfair_betting_url,
            )
        return cls(
            settings,
            session_factory,
            clock=clock,
            football=football,
            odds=odds,
            betfair=betfair,
            betfair_error=betfair_error,
        )

    def configured(self) -> dict[str, bool]:
        return {
            FIXTURES: self.football is not None,
            ODDS: self.odds is not None,
            BETFAIR: self.betfair is not None,
        }

    # --- one tick -------------------------------------------------------------------------

    def tick(self) -> TickReport:
        now = self.clock()
        report = TickReport()
        if self.football is not None:
            self._fixtures(now, report)
        if self.betfair is not None:
            self._exchange(now, report)
        if self.odds is not None:
            self._bookmakers(now, report)
        if report.changed or is_due(self._last.get(("finder", "")), FINDER_EVERY, now):
            self._last[("finder", "")] = now
            with transaction(self.factory) as session:
                run = run_value_finder(session, now=now, tz=self.settings.owner_tz)
                report.signals = len(run.created)
        return report

    def _attempt(
        self, feed: str, fetch: Callable[[], T], now: datetime, report: TickReport
    ) -> T | None:
        try:
            return fetch()
        except FeedError as error:
            log.warning("%s failed: %s", feed, error)
            report.errors.append(f"{feed}: {error}")
            with transaction(self.factory) as session:
                feed_failed(session, feed, error, now=now)
            return None

    def _fixtures(self, now: datetime, report: TickReport) -> None:
        assert self.football is not None
        football = self.football
        with self.factory() as session:
            competitions = list(
                session.scalars(
                    select(Competition).where(
                        Competition.active.is_(True),
                        Competition.api_football_league_id.is_not(None),
                    )
                )
            )
            waiting = {
                c.id: bool(
                    session.scalar(
                        select(func.count())
                        .select_from(Event)
                        .where(
                            Event.competition_id == c.id,
                            Event.status.in_([EventStatus.SCHEDULED, EventStatus.LIVE]),
                            Event.kickoff_at <= now - RESULTS_AFTER_KICKOFF,
                            Event.kickoff_at >= now - timedelta(days=2),
                        )
                    )
                )
                for c in competitions
            }
        today = now.date()
        for competition in competitions:
            league_id = competition.api_football_league_id
            assert league_id is not None
            full = is_due(self._last.get(("fixtures", competition.code)), FIXTURES_EVERY, now)
            results = waiting[competition.id] and is_due(
                self._last.get(("results", competition.code)), RESULTS_EVERY, now
            )
            if not (full or results):
                continue
            self._last[("results", competition.code)] = now
            if full:
                self._last[("fixtures", competition.code)] = now
            response = self._attempt(
                FIXTURES,
                partial(
                    football.fixtures,
                    league_id=league_id,
                    season=season_for(today),
                    date_from=today - timedelta(days=2),
                    date_to=today + self.horizon + timedelta(days=3),
                ),
                now,
                report,
            )
            if response is None:
                self._last[("fixtures", competition.code)] = (
                    now - FIXTURES_EVERY + RETRY_AFTER_FAILURE
                )
                break  # one failure per tick: the other leagues wait for the next try
            with transaction(self.factory) as session:
                stored = session.get(Competition, competition.id)
                assert stored is not None
                sync_fixtures(session, stored, response.fixtures, now=now)
                feed_succeeded(
                    session,
                    FIXTURES,
                    now=now,
                    details={"requests_remaining": response.quota.remaining},
                )
            report.fixtures += len(response.fixtures)

    def _exchange(self, now: datetime, report: TickReport) -> None:
        assert self.betfair is not None
        betfair = self.betfair
        if self.betfair_error is not None:
            with transaction(self.factory) as session:
                feed_failed(session, BETFAIR, self.betfair_error, now=now)
            return
        with self.factory() as session:
            competition_ids = {
                c.betfair_competition_id: c.id
                for c in session.scalars(
                    select(Competition).where(
                        Competition.active.is_(True),
                        Competition.betfair_competition_id.is_not(None),
                    )
                )
                if c.betfair_competition_id
            }
        if competition_ids and is_due(self._last.get(("catalogue", "")), CATALOGUE_EVERY, now):
            self._last[("catalogue", "")] = now
            markets = self._attempt(
                BETFAIR,
                lambda: betfair.catalogue(
                    sorted(competition_ids), now - timedelta(hours=2), now + self.horizon
                ),
                now,
                report,
            )
            if markets is None:
                self._last[("catalogue", "")] = now - CATALOGUE_EVERY + RETRY_AFTER_FAILURE
            else:
                with transaction(self.factory) as session:
                    competitions = {
                        bf_id: c
                        for bf_id, cid in competition_ids.items()
                        if (c := session.get(Competition, cid)) is not None
                    }
                    stats = ingest_catalogue(session, markets, competitions, seen_at=now)
                    feed_succeeded(
                        session,
                        BETFAIR,
                        now=now,
                        details={"unmatched_matches": stats.unmatched[:10]},
                    )
        if not is_due(self._last.get(("books_failed", "")), RETRY_AFTER_FAILURE, now):
            return
        with self.factory() as session:
            rows = session.execute(
                select(
                    ExchangeMarket.betfair_market_id,
                    ExchangeMarket.start_time,
                    ExchangeMarket.last_book_at,
                ).where(
                    ExchangeMarket.start_time > now,
                    ExchangeMarket.start_time <= now + self.horizon,
                )
            ).all()
        due = [
            market_id
            for market_id, start, last in rows
            if is_due(last, poll_interval(start - now, BETFAIR_SCHEDULE), now)
        ]
        if not due:
            return
        books = self._attempt(BETFAIR, lambda: betfair.books(due), now, report)
        if books is None:
            self._last[("books_failed", "")] = now
            return
        with transaction(self.factory) as session:
            book_stats = ingest_books(
                session,
                books,
                seen_at=now,
                method=self.settings.fair_price_method,
                max_spread=self.settings.fair_price_max_spread,
            )
            feed_succeeded(
                session, BETFAIR, now=now, details={"delayed_prices": book_stats.delayed}
            )
        report.exchange_books += len(books)
        report.changed |= book_stats.changed > 0 or book_stats.fair_prices > 0

    def _bookmakers(self, now: datetime, report: TickReport) -> None:
        assert self.odds is not None
        odds = self.odds
        with self.factory() as session:
            leagues = session.execute(
                select(
                    Competition.id,
                    Competition.code,
                    Competition.odds_api_sport_key,
                    func.min(Event.kickoff_at),
                )
                .join(Event, Event.competition_id == Competition.id)
                .where(
                    Competition.active.is_(True),
                    Competition.odds_api_sport_key.is_not(None),
                    Event.status == EventStatus.SCHEDULED,
                    Event.kickoff_at > now,
                    Event.kickoff_at <= now + self.horizon,
                )
                .group_by(Competition.id, Competition.code, Competition.odds_api_sport_key)
            ).all()
        for competition_id, code, sport_key, next_kickoff in leagues:
            if not sport_key:
                continue
            every = poll_interval(next_kickoff - now, ODDS_SCHEDULE)
            if not is_due(self._last.get(("odds", code)), every, now):
                continue
            self._last[("odds", code)] = now
            response = self._attempt(ODDS, partial(odds.odds, sport_key), now, report)
            if response is None:
                break  # one failure per tick: the other leagues wait for the next try
            with transaction(self.factory) as session:
                competition = session.get(Competition, competition_id)
                assert competition is not None
                stats = ingest_odds(session, competition, response.events, seen_at=now)
                feed_succeeded(
                    session,
                    ODDS,
                    now=now,
                    details={
                        "credits_remaining": response.quota.remaining,
                        "unmatched_matches": stats.unmatched[:10],
                    },
                )
            report.odds_events += len(response.events)
            report.changed |= stats.changed > 0
