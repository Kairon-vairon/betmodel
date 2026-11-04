"""Storing what the feeds return: fixtures, results, bookmaker odds, exchange prices.

Prices are kept in two forms:
- latest_prices: the newest price per selection/source/bookmaker/side with the time it
  was last confirmed. Freshness checks use this (CLAUDE.md rule 7).
- price_snapshots: append-only history, one row each time a price changes.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from edgewise.db.models import (
    Bookmaker,
    Competition,
    Event,
    EventStatus,
    ExchangeMarket,
    FairPrice,
    LatestFairPrice,
    LatestPrice,
    Market,
    MarketSelection,
    PriceSide,
    PriceSnapshot,
    PriceSource,
    Team,
    TeamAlias,
)
from edgewise.domain.markets import MarketType, Selection
from edgewise.domain.pricing import (
    ExchangeRunner,
    MarginMethod,
    MarketUnusable,
    exchange_fair_price,
)
from edgewise.feeds.api_football import FixtureRecord, TeamRef
from edgewise.feeds.betfair import CatalogueMarket, CatalogueRunner, MarketBook, to_groups
from edgewise.feeds.matching import FixtureCandidate, match_event, split_event_name
from edgewise.feeds.odds_api import OddsEvent
from edgewise.services import audit

log = logging.getLogger(__name__)

# team_aliases.source values
REFERENCE_ID = "api_football_id"  # API-Football's numeric team id
REFERENCE_NAME = "api_football"
ODDS_API = "odds_api"
BETFAIR = "betfair"
NAME_SOURCES = (REFERENCE_NAME, ODDS_API, BETFAIR)

# With a delayed (development) Betfair key, prices can be a few minutes old.
DELAYED_KEY_AGE = timedelta(minutes=3)
FAIR_CHANGE = 1e-4  # a fair probability moving less than this is "unchanged"
_VOID_STATUSES = {EventStatus.POSTPONED, EventStatus.CANCELLED, EventStatus.ABANDONED}


# --- Prices -------------------------------------------------------------------------------


def record_price(
    session: Session,
    *,
    selection_id: int,
    source: PriceSource,
    bookmaker_id: int | None,
    side: PriceSide,
    odds: Decimal,
    seen_at: datetime,
    size: Decimal | None = None,
    price_time: datetime | None = None,
) -> bool:
    """Store a price seen now. Returns True when it is new or changed (history row added)."""
    query = select(LatestPrice).where(
        LatestPrice.selection_id == selection_id,
        LatestPrice.source == source,
        LatestPrice.side == side,
        LatestPrice.bookmaker_id.is_(None)
        if bookmaker_id is None
        else LatestPrice.bookmaker_id == bookmaker_id,
    )
    latest = session.scalar(query)
    changed = latest is None or latest.odds != odds
    if latest is None:
        latest = LatestPrice(
            selection_id=selection_id,
            source=source,
            bookmaker_id=bookmaker_id,
            side=side,
            odds=odds,
            first_seen_at=seen_at,
            last_seen_at=seen_at,
        )
        session.add(latest)
    elif changed:
        latest.odds = odds
        latest.first_seen_at = seen_at
    if latest.last_seen_at is None or seen_at >= latest.last_seen_at:
        latest.last_seen_at = seen_at
    latest.size = size
    latest.price_time = price_time
    if changed:
        session.add(
            PriceSnapshot(
                selection_id=selection_id,
                source=source,
                bookmaker_id=bookmaker_id,
                side=side,
                odds=odds,
                size=size,
                captured_at=seen_at,
            )
        )
    return changed


def record_fair_price(
    session: Session,
    *,
    selection_id: int,
    fair_prob: float,
    method: str,
    mid_overround: float,
    as_of: datetime,
    inputs: dict[str, Any] | None = None,
) -> bool:
    """Store a fair probability confirmed at `as_of`. History only when it changes."""
    latest = session.get(LatestFairPrice, selection_id)
    if (
        latest is not None
        and latest.method == method
        and abs(latest.fair_prob - fair_prob) < FAIR_CHANGE
    ):
        latest.as_of = max(latest.as_of, as_of)
        latest.mid_overround = mid_overround
        return False
    row = FairPrice(
        selection_id=selection_id,
        fair_prob=fair_prob,
        method=method,
        mid_overround=mid_overround,
        inputs=inputs or {},
        as_of=as_of,
    )
    session.add(row)
    session.flush()
    if latest is None:
        session.add(
            LatestFairPrice(
                selection_id=selection_id,
                fair_prob=fair_prob,
                method=method,
                mid_overround=mid_overround,
                fair_price_id=row.id,
                changed_at=as_of,
                as_of=as_of,
            )
        )
    else:
        latest.fair_prob, latest.method, latest.mid_overround = fair_prob, method, mid_overround
        latest.fair_price_id, latest.changed_at, latest.as_of = row.id, as_of, as_of
    return True


# --- Markets and selections ---------------------------------------------------------------


MINUS = "−"


def _line_text(line: Decimal) -> str:
    """-0.25 -> "−0.25" (a real minus sign), 0.5 -> "+0.5", 0 -> "0"."""
    text = format(abs(line).normalize(), "f")
    return f"{MINUS}{text}" if line < 0 else f"+{text}" if line > 0 else "0"


def selection_label(
    market_type: MarketType, line: Decimal | None, selection: Selection, home: str, away: str
) -> str:
    if market_type in (MarketType.MATCH_RESULT, MarketType.DRAW_NO_BET):
        return {Selection.HOME: home, Selection.AWAY: away}.get(selection, "Draw")
    if market_type is MarketType.TOTAL_GOALS and line is not None:
        return f"{selection.value.title()} {format(line.normalize(), 'f')}"
    if market_type is MarketType.ASIAN_HANDICAP and line is not None:
        if selection is Selection.HOME:
            return f"{home} {_line_text(line)}"
        return f"{away} {_line_text(-line)}"
    return selection.value.title()


class MarketCache:
    """Finds or creates markets and selections, remembering them for one batch."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self._markets: dict[tuple[int, MarketType, Decimal | None], Market] = {}
        self._selections: dict[tuple[int, Selection], MarketSelection] = {}

    def selection(
        self,
        event: Event,
        market_type: MarketType,
        line: Decimal | None,
        selection: Selection,
        *,
        betfair_selection_id: int | None = None,
    ) -> MarketSelection:
        key = (event.id, market_type, None if line is None else line.normalize())
        market = self._markets.get(key)
        if market is None:
            query = select(Market).where(
                Market.event_id == event.id,
                Market.type == market_type,
                Market.line.is_(None) if line is None else Market.line == line,
            )
            market = self.session.scalar(query)
            if market is None:
                market = Market(event_id=event.id, type=market_type, line=line)
                self.session.add(market)
                self.session.flush()
            self._markets[key] = market
        sel_key = (market.id, selection)
        found = self._selections.get(sel_key)
        if found is None:
            found = self.session.scalar(
                select(MarketSelection).where(
                    MarketSelection.market_id == market.id, MarketSelection.code == selection
                )
            )
            if found is None:
                found = MarketSelection(
                    market_id=market.id,
                    code=selection,
                    label=selection_label(
                        market_type, line, selection, event.home_team.name, event.away_team.name
                    ),
                )
                self.session.add(found)
                self.session.flush()
            self._selections[sel_key] = found
        if betfair_selection_id is not None and found.betfair_selection_id is None:
            found.betfair_selection_id = betfair_selection_id
        return found


# --- Fixtures and results -----------------------------------------------------------------


@dataclass
class FixtureSync:
    created: int = 0
    updated: int = 0
    results: int = 0


def _team_for(session: Session, ref: TeamRef) -> Team:
    alias = session.scalar(
        select(TeamAlias).where(
            TeamAlias.source == REFERENCE_ID, TeamAlias.alias == str(ref.feed_id)
        )
    )
    if alias is not None:
        return alias.team
    team = session.scalar(select(Team).where(Team.name == ref.name))
    if team is None:
        team = Team(name=ref.name)
        session.add(team)
        session.flush()
    session.add(TeamAlias(team_id=team.id, source=REFERENCE_ID, alias=str(ref.feed_id)))
    _remember_alias(session, team, REFERENCE_NAME, ref.name)
    return team


def _remember_alias(session: Session, team: Team, source: str, name: str) -> None:
    existing = session.scalar(
        select(TeamAlias).where(TeamAlias.source == source, TeamAlias.alias == name)
    )
    if existing is None:
        session.add(TeamAlias(team_id=team.id, source=source, alias=name))
        session.flush()
    elif existing.team_id != team.id:
        log.warning("Alias %r (%s) already belongs to another team; not changed", name, source)


def sync_fixtures(
    session: Session, competition: Competition, fixtures: Iterable[FixtureRecord], *, now: datetime
) -> FixtureSync:
    stats = FixtureSync()
    for record in fixtures:
        if record.league_id != competition.api_football_league_id:
            continue
        event = session.scalar(select(Event).where(Event.api_football_fixture_id == record.feed_id))
        home, away = _team_for(session, record.home), _team_for(session, record.away)
        if event is None:
            event = Event(
                competition_id=competition.id,
                home_team_id=home.id,
                away_team_id=away.id,
                kickoff_at=record.kickoff,
                status=record.status,
                api_football_fixture_id=record.feed_id,
            )
            session.add(event)
            session.flush()
            stats.created += 1
        else:
            if event.kickoff_at != record.kickoff or event.status != record.status:
                stats.updated += 1
            event.kickoff_at = record.kickoff
            event.status = record.status
        if record.status is EventStatus.FINISHED and record.home_goals is not None:
            new_score = (record.home_goals, record.away_goals)
            if (event.home_goals, event.away_goals) != new_score:
                if event.home_goals is not None:
                    audit.record(
                        session,
                        actor="worker",
                        action="result_changed",
                        at=now,
                        entity_type="event",
                        entity_id=event.id,
                        old=f"{event.home_goals}-{event.away_goals}",
                        new=f"{new_score[0]}-{new_score[1]}",
                    )
                event.home_goals, event.away_goals = new_score
                event.result_source, event.result_recorded_at = REFERENCE_NAME, now
                stats.results += 1
        elif record.status in _VOID_STATUSES:
            event.home_goals = event.away_goals = None
    session.flush()
    return stats


# --- Linking other feeds' matches to fixtures ---------------------------------------------


class FixtureIndex:
    """Upcoming and recent fixtures of one competition, with every known team name."""

    def __init__(self, session: Session, competition_id: int, around: datetime) -> None:
        self.session = session
        self.competition_id = competition_id
        window_from, window_to = around - timedelta(days=2), around + timedelta(days=14)
        self.events = list(
            session.scalars(
                select(Event).where(
                    Event.competition_id == competition_id,
                    Event.kickoff_at >= window_from,
                    Event.kickoff_at <= window_to,
                )
            )
        )
        team_ids = {e.home_team_id for e in self.events} | {e.away_team_id for e in self.events}
        self.names: dict[int, list[str]] = {}
        for team in session.scalars(select(Team).where(Team.id.in_(team_ids))) if team_ids else []:
            self.names[team.id] = [team.name]
        if team_ids:
            for alias in session.scalars(
                select(TeamAlias).where(
                    TeamAlias.team_id.in_(team_ids), TeamAlias.source.in_(NAME_SOURCES)
                )
            ):
                self.names[alias.team_id].append(alias.alias)

    def candidates(self) -> list[FixtureCandidate]:
        return [
            FixtureCandidate(
                event_id=e.id,
                kickoff=e.kickoff_at,
                home_names=tuple(self.names.get(e.home_team_id, [])),
                away_names=tuple(self.names.get(e.away_team_id, [])),
            )
            for e in self.events
        ]

    def link(
        self, *, source: str, feed_event_id: str, home: str, away: str, kickoff: datetime
    ) -> Event | None:
        id_column = Event.odds_api_event_id if source == ODDS_API else Event.betfair_event_id
        known = next((e for e in self.events if getattr(e, id_column.key) == feed_event_id), None)
        if known is not None:
            return known
        match = match_event(home, away, kickoff, self.candidates())
        if match is None:
            return None
        event = next(e for e in self.events if e.id == match.event_id)
        if getattr(event, id_column.key) not in (None, feed_event_id):
            log.warning("Event %s is already linked to another %s match", event.id, source)
            return None
        setattr(event, id_column.key, feed_event_id)
        for team_id, name in ((event.home_team_id, home), (event.away_team_id, away)):
            team = self.session.get(Team, team_id)
            assert team is not None
            _remember_alias(self.session, team, source, name)
            if name not in self.names.setdefault(team_id, []):
                self.names[team_id].append(name)
        return event


# --- Bookmaker odds -----------------------------------------------------------------------


@dataclass
class IngestStats:
    matched: int = 0
    unmatched: list[str] = field(default_factory=list)
    prices: int = 0
    changed: int = 0


def ingest_odds(
    session: Session, competition: Competition, events: Sequence[OddsEvent], *, seen_at: datetime
) -> IngestStats:
    stats = IngestStats()
    books = {b.key: b for b in session.scalars(select(Bookmaker))}
    index = FixtureIndex(session, competition.id, seen_at)
    cache = MarketCache(session)
    for feed_event in events:
        event = index.link(
            source=ODDS_API,
            feed_event_id=feed_event.feed_event_id,
            home=feed_event.home,
            away=feed_event.away,
            kickoff=feed_event.kickoff,
        )
        if event is None:
            stats.unmatched.append(f"{feed_event.home} v {feed_event.away}")
            continue
        if event.status is not EventStatus.SCHEDULED or event.kickoff_at <= seen_at:
            continue  # pre-match prices only
        stats.matched += 1
        for price in feed_event.prices:
            book = books.get(price.bookmaker_key)
            if book is None:
                continue  # not a bookmaker in scope
            selection = cache.selection(event, price.market, price.line, price.selection)
            stats.prices += 1
            stats.changed += record_price(
                session,
                selection_id=selection.id,
                source=PriceSource.ODDS_FEED,
                bookmaker_id=book.id,
                side=PriceSide.BACK,
                odds=price.odds,
                seen_at=seen_at,
                price_time=price.price_time,
            )
    session.flush()
    return stats


# --- Betfair Exchange ---------------------------------------------------------------------


def ingest_catalogue(
    session: Session,
    markets: Sequence[CatalogueMarket],
    competitions: dict[str, Competition],
    *,
    seen_at: datetime,
) -> IngestStats:
    """Link Betfair markets to fixtures; competitions is keyed by Betfair competition id."""
    stats = IngestStats()
    indexes: dict[int, FixtureIndex] = {}
    for market in markets:
        competition = competitions.get(market.competition_id or "")
        names = split_event_name(market.event_name)
        if competition is None or names is None:
            continue
        index = indexes.get(competition.id)
        if index is None:
            index = indexes[competition.id] = FixtureIndex(session, competition.id, seen_at)
        event = index.link(
            source=BETFAIR,
            feed_event_id=market.event_id,
            home=names[0],
            away=names[1],
            kickoff=market.start_time,
        )
        if event is None:
            if market.event_name not in stats.unmatched:
                stats.unmatched.append(market.event_name)
            continue
        stats.matched += 1
        runners = [
            {
                "selection_id": r.selection_id,
                "name": r.name,
                "handicap": str(r.handicap),
                "sort_priority": r.sort_priority,
            }
            for r in market.runners
        ]
        row = session.get(ExchangeMarket, market.market_id)
        if row is None:
            row = ExchangeMarket(
                betfair_market_id=market.market_id,
                event_id=event.id,
                market_type=market.market_type,
                event_name=market.event_name,
                start_time=market.start_time,
                runners=runners,
                last_catalogue_at=seen_at,
            )
            session.add(row)
        else:
            row.event_id, row.start_time, row.runners = event.id, market.start_time, runners
            row.event_name, row.last_catalogue_at = market.event_name, seen_at
    session.flush()
    return stats


def _catalogue_from_row(row: ExchangeMarket) -> CatalogueMarket:
    return CatalogueMarket(
        market_id=row.betfair_market_id,
        market_type=row.market_type,
        start_time=row.start_time,
        event_id="",
        event_name=row.event_name,
        competition_id=None,
        runners=tuple(
            CatalogueRunner(
                int(r["selection_id"]),
                str(r["name"]),
                Decimal(r["handicap"]),
                int(r.get("sort_priority", 0)),
            )
            for r in row.runners
        ),
    )


@dataclass
class BookStats:
    markets: int = 0
    fair_prices: int = 0
    unusable: int = 0
    changed: int = 0
    delayed: bool = False


def ingest_books(
    session: Session,
    books: Sequence[MarketBook],
    *,
    seen_at: datetime,
    method: MarginMethod = MarginMethod.MULTIPLICATIVE,
    max_spread: Decimal | None = Decimal("0.05"),
) -> BookStats:
    stats = BookStats()
    cache = MarketCache(session)
    for book in books:
        row = session.get(ExchangeMarket, book.market_id)
        if row is None:
            continue
        row.status, row.total_matched = book.status, book.total_matched
        row.is_delayed, row.last_book_at = book.delayed, seen_at
        event = session.get(Event, row.event_id)
        if event is None or event.status is not EventStatus.SCHEDULED:
            continue
        stats.markets += 1
        stats.delayed |= book.delayed
        as_of = seen_at - DELAYED_KEY_AGE if book.delayed else seen_at
        for group in to_groups(_catalogue_from_row(row), book):
            selections = {
                q.selection: cache.selection(
                    event,
                    group.market_type,
                    group.line,
                    q.selection,
                    betfair_selection_id=q.selection_id,
                )
                for q in group.quotes
            }
            for quote in group.quotes:
                selection_id = selections[quote.selection].id
                for side, odds, size in (
                    (PriceSide.BACK, quote.back, quote.back_size),
                    (PriceSide.LAY, quote.lay, quote.lay_size),
                ):
                    if odds is not None:
                        stats.changed += record_price(
                            session,
                            selection_id=selection_id,
                            source=PriceSource.BETFAIR,
                            bookmaker_id=None,
                            side=side,
                            odds=odds,
                            size=size,
                            seen_at=as_of,
                        )
            try:
                fair = exchange_fair_price(
                    [ExchangeRunner(q.selection.value, q.back, q.lay) for q in group.quotes],
                    method=method,
                    max_spread=max_spread,
                )
            except MarketUnusable as reason:
                stats.unusable += 1
                log.debug("Market %s not used: %s", book.market_id, reason)
                continue
            for quote in group.quotes:
                stats.fair_prices += record_fair_price(
                    session,
                    selection_id=selections[quote.selection].id,
                    fair_prob=fair.probabilities[quote.selection.value],
                    method=fair.method.value,
                    mid_overround=fair.mid_overround,
                    as_of=as_of,
                    inputs={
                        "betfair_market_id": book.market_id,
                        "back": str(quote.back),
                        "lay": str(quote.lay),
                    },
                )
    session.flush()
    return stats
