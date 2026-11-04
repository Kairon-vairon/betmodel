"""Small helpers to create fixtures and prices in tests."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from edgewise.db.models import (
    Bookmaker,
    Competition,
    Event,
    Market,
    MarketSelection,
    PriceSide,
    PriceSource,
    Team,
)
from edgewise.domain.finder import Candidate
from edgewise.domain.markets import MarketType, Selection
from edgewise.services.ingest import record_fair_price, record_price

_counter = 0


def _n() -> int:
    global _counter
    _counter += 1
    return _counter


def make_match(session: Session, *, kickoff: datetime) -> tuple[Event, dict[Selection, int]]:
    """An EPL-style match with a match-result market. Returns the event and selection ids."""
    n = _n()
    competition = session.query(Competition).filter_by(code="EPL").one_or_none()
    if competition is None:
        competition = Competition(code="EPL", name="Premier League", country="England")
        session.add(competition)
    home, away = Team(name=f"Home {n}"), Team(name=f"Away {n}")
    session.add_all([home, away])
    session.flush()
    event = Event(
        competition_id=competition.id,
        home_team_id=home.id,
        away_team_id=away.id,
        kickoff_at=kickoff,
    )
    session.add(event)
    session.flush()
    market = Market(event_id=event.id, type=MarketType.MATCH_RESULT)
    session.add(market)
    session.flush()
    ids: dict[Selection, int] = {}
    for code in (Selection.HOME, Selection.DRAW, Selection.AWAY):
        sel = MarketSelection(market_id=market.id, code=code, label=code.value.title())
        session.add(sel)
        session.flush()
        ids[code] = sel.id
    return event, ids


def make_bookmaker(session: Session, key: str = "sportsbet", **kwargs: object) -> Bookmaker:
    book = Bookmaker(key=f"{key}-{_n()}", name=key.title(), **kwargs)
    session.add(book)
    session.flush()
    return book


def add_book_price(
    session: Session, selection_id: int, bookmaker_id: int, odds: str, at: datetime
) -> None:
    """A bookmaker price seen at `at`, stored the way the odds feed stores it."""
    record_price(
        session,
        selection_id=selection_id,
        source=PriceSource.ODDS_FEED,
        bookmaker_id=bookmaker_id,
        side=PriceSide.BACK,
        odds=Decimal(odds),
        seen_at=at,
    )


def add_fair_price(session: Session, selection_id: int, prob: float, at: datetime) -> None:
    """A fair probability confirmed at `at`, stored the way the exchange feed stores it."""
    record_fair_price(
        session,
        selection_id=selection_id,
        fair_prob=prob,
        method="multiplicative",
        mid_overround=1.0,
        as_of=at,
    )


def candidate_for(
    event: Event,
    selection_id: int,
    bookmaker_id: int,
    now: datetime,
    *,
    odds: str = "1.95",
    prob: float = 0.542,
) -> Candidate:
    return Candidate(
        event_id=event.id,
        selection_id=selection_id,
        bookmaker_id=bookmaker_id,
        offered_odds=Decimal(odds),
        offered_at=now - timedelta(minutes=1),
        fair_prob=prob,
        fair_as_of=now - timedelta(minutes=1),
        kickoff=event.kickoff_at,
        bookmaker_name="Sportsbet",
        selection_label="Home",
        market_label="Match result",
    )
