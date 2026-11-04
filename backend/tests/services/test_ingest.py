"""Storing feed data: fixtures, results, bookmaker odds, exchange prices, then value."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from edgewise.db.models import (
    AuditEntry,
    Bookmaker,
    Competition,
    Event,
    EventStatus,
    ExchangeMarket,
    FairPrice,
    LatestFairPrice,
    LatestPrice,
    LedgerKind,
    MarketSelection,
    Notification,
    PriceSide,
    PriceSnapshot,
    PriceSource,
    Team,
    TeamAlias,
)
from edgewise.domain.markets import MarketType as M
from edgewise.domain.markets import Selection as S
from edgewise.domain.pricing import ExchangeRunner, exchange_fair_price
from edgewise.domain.staking import edge
from edgewise.feeds.api_football import FixtureRecord, TeamRef
from edgewise.feeds.betfair import CatalogueMarket, CatalogueRunner, MarketBook, RunnerBook
from edgewise.feeds.common import FeedAuthError
from edgewise.feeds.odds_api import BookPrice, OddsEvent
from edgewise.services import portfolio
from edgewise.services.feeds import BETFAIR, feed_failed
from edgewise.services.ingest import (
    ingest_books,
    ingest_catalogue,
    ingest_odds,
    sync_fixtures,
)
from edgewise.services.value import run_value_finder

NOW = datetime(2026, 11, 7, 9, 0, tzinfo=UTC)
KICKOFF = datetime(2026, 11, 7, 15, 0, tzinfo=UTC)
SYDNEY = ZoneInfo("Australia/Sydney")
TEAM_IDS = {"Brighton": 51, "Everton": 45, "Manchester United": 33, "Manchester City": 50}


@pytest.fixture
def epl(db: Session) -> Competition:
    competition = Competition(
        code="EPL",
        name="Premier League",
        country="England",
        betfair_competition_id="10932509",
        odds_api_sport_key="soccer_epl",
        api_football_league_id=39,
    )
    db.add(competition)
    db.add_all([Bookmaker(key="sportsbet", name="Sportsbet"), Bookmaker(key="tab", name="TAB")])
    db.flush()
    return competition


def fixture(
    fid: int,
    home: str,
    away: str,
    *,
    status: EventStatus = EventStatus.SCHEDULED,
    kickoff: datetime = KICKOFF,
    goals: tuple[int | None, int | None] = (None, None),
) -> FixtureRecord:
    return FixtureRecord(
        fid,
        39,
        kickoff,
        status,
        TeamRef(TEAM_IDS[home], home),
        TeamRef(TEAM_IDS[away], away),
        goals[0],
        goals[1],
    )


MATCHES = [fixture(1, "Brighton", "Everton"), fixture(2, "Manchester United", "Manchester City")]


def count(db: Session, model: type) -> int:
    return db.scalar(select(func.count()).select_from(model)) or 0


def brighton_event(db: Session) -> Event:
    return db.scalars(select(Event).where(Event.api_football_fixture_id == 1)).one()


# --- Fixtures and results -----------------------------------------------------------------


def test_fixtures_create_teams_and_events_once(db: Session, epl: Competition) -> None:
    stats = sync_fixtures(db, epl, MATCHES, now=NOW)
    assert (stats.created, stats.updated) == (2, 0)
    assert count(db, Team) == 4 and count(db, Event) == 2
    again = sync_fixtures(db, epl, MATCHES, now=NOW)
    assert (again.created, again.updated) == (0, 0)
    moved = sync_fixtures(
        db, epl, [fixture(1, "Brighton", "Everton", kickoff=KICKOFF + timedelta(hours=2))], now=NOW
    )
    assert moved.updated == 1
    assert brighton_event(db).kickoff_at == KICKOFF + timedelta(hours=2)


def test_other_leagues_are_ignored(db: Session, epl: Competition) -> None:
    other = FixtureRecord(
        9,
        140,
        KICKOFF,
        EventStatus.SCHEDULED,
        TeamRef(529, "Barcelona"),
        TeamRef(541, "Real Madrid"),
        None,
        None,
    )
    assert sync_fixtures(db, epl, [other], now=NOW).created == 0


def test_results_are_recorded_and_corrections_audited(db: Session, epl: Competition) -> None:
    sync_fixtures(db, epl, MATCHES, now=NOW)
    final = fixture(1, "Brighton", "Everton", status=EventStatus.FINISHED, goals=(2, 1))
    assert sync_fixtures(db, epl, [final], now=NOW).results == 1
    event = brighton_event(db)
    assert (event.status, event.home_goals, event.away_goals) == (EventStatus.FINISHED, 2, 1)
    assert event.result_source == "api_football"
    corrected = fixture(1, "Brighton", "Everton", status=EventStatus.FINISHED, goals=(2, 2))
    sync_fixtures(db, epl, [corrected], now=NOW)
    changes = list(db.scalars(select(AuditEntry).where(AuditEntry.action == "result_changed")))
    assert len(changes) == 1 and changes[0].details == {"old": "2-1", "new": "2-2"}


def test_postponed_matches(db: Session, epl: Competition) -> None:
    sync_fixtures(
        db, epl, [fixture(1, "Brighton", "Everton", status=EventStatus.POSTPONED)], now=NOW
    )
    assert brighton_event(db).status is EventStatus.POSTPONED


# --- Bookmaker odds -----------------------------------------------------------------------


def odds_events(home_price: str = "1.95", seen: datetime = NOW) -> list[OddsEvent]:
    prices = (
        BookPrice("sportsbet", M.MATCH_RESULT, None, S.HOME, D(home_price), seen),
        BookPrice("sportsbet", M.MATCH_RESULT, None, S.DRAW, D("3.6"), seen),
        BookPrice("pointsbetau", M.MATCH_RESULT, None, S.HOME, D("2.0"), seen),  # not in scope
        BookPrice("tab", M.TOTAL_GOALS, D("2.5"), S.OVER, D("1.9"), seen),
        BookPrice("sportsbet", M.ASIAN_HANDICAP, D("-0.25"), S.HOME, D("1.95"), seen),
        BookPrice("sportsbet", M.ASIAN_HANDICAP, D("-0.25"), S.AWAY, D("1.9"), seen),
    )
    return [
        OddsEvent("oa1", "Brighton and Hove Albion", "Everton", KICKOFF, prices),
        OddsEvent("oa2", "Liverpool", "Arsenal", KICKOFF, ()),
    ]


def test_bookmaker_odds_are_linked_and_stored(db: Session, epl: Competition) -> None:
    sync_fixtures(db, epl, MATCHES, now=NOW)
    stats = ingest_odds(db, epl, odds_events(), seen_at=NOW)
    assert stats.matched == 1 and stats.unmatched == ["Liverpool v Arsenal"]
    assert (stats.prices, stats.changed) == (5, 5)
    assert brighton_event(db).odds_api_event_id == "oa1"
    labels = set(db.scalars(select(MarketSelection.label)))
    assert labels == {"Brighton", "Draw", "Over 2.5", "Brighton −0.25", "Everton +0.25"}
    learned = db.scalars(
        select(TeamAlias).where(
            TeamAlias.source == "odds_api", TeamAlias.alias == "Brighton and Hove Albion"
        )
    ).one()
    assert learned.team.name == "Brighton"
    assert count(db, LatestPrice) == 5 and count(db, PriceSnapshot) == 5


def test_unchanged_prices_add_no_history(db: Session, epl: Competition) -> None:
    sync_fixtures(db, epl, MATCHES, now=NOW)
    ingest_odds(db, epl, odds_events(), seen_at=NOW)
    later = NOW + timedelta(minutes=10)
    assert ingest_odds(db, epl, odds_events(seen=later), seen_at=later).changed == 0
    assert count(db, PriceSnapshot) == 5
    home = db.scalars(
        select(LatestPrice)
        .join(MarketSelection, MarketSelection.id == LatestPrice.selection_id)
        .where(MarketSelection.label == "Brighton", LatestPrice.source == PriceSource.ODDS_FEED)
    ).one()
    assert (home.first_seen_at, home.last_seen_at) == (NOW, later)
    moved = NOW + timedelta(minutes=20)
    assert ingest_odds(db, epl, odds_events("2.00", moved), seen_at=moved).changed == 1
    assert count(db, PriceSnapshot) == 6
    db.refresh(home)
    assert (home.odds, home.first_seen_at) == (D("2.00"), moved)


def test_matches_that_have_started_get_no_prices(db: Session, epl: Competition) -> None:
    sync_fixtures(db, epl, MATCHES, now=NOW)
    after_kickoff = KICKOFF + timedelta(minutes=1)
    assert ingest_odds(db, epl, odds_events(), seen_at=after_kickoff).prices == 0


# --- Betfair Exchange ---------------------------------------------------------------------

CATALOGUE = [
    CatalogueMarket(
        "1.1",
        "MATCH_ODDS",
        KICKOFF,
        "bf-1",
        "Brighton v Everton",
        "10932509",
        (
            CatalogueRunner(51, "Brighton", D(0), 1),
            CatalogueRunner(45, "Everton", D(0), 2),
            CatalogueRunner(58805, "The Draw", D(0), 3),
        ),
    )
]
PRICES = {51: ("1.84", "1.85"), 45: ("4.9", "5.0"), 58805: ("3.75", "3.8")}


def book(*, delayed: bool = False, draw_lay: str = "3.8") -> MarketBook:
    runners = []
    for sid, (back, lay) in PRICES.items():
        lay = draw_lay if sid == 58805 else lay
        runners.append(RunnerBook(sid, D(0), "ACTIVE", D(back), D("120"), D(lay), D("98")))
    return MarketBook("1.1", "OPEN", False, delayed, D("98765"), tuple(runners))


def expected_fair() -> dict[str, float]:
    runners = [
        ExchangeRunner(key, D(PRICES[sid][0]), D(PRICES[sid][1]))
        for key, sid in (("home", 51), ("away", 45), ("draw", 58805))
    ]
    return dict(exchange_fair_price(runners).probabilities)


def fair_by_label(db: Session) -> dict[str | None, LatestFairPrice]:
    rows = db.execute(
        select(MarketSelection.label, LatestFairPrice).join(
            LatestFairPrice, LatestFairPrice.selection_id == MarketSelection.id
        )
    ).all()
    return {label: fair for label, fair in rows}


def test_exchange_prices_give_fair_probabilities(db: Session, epl: Competition) -> None:
    sync_fixtures(db, epl, MATCHES, now=NOW)
    linked = ingest_catalogue(db, CATALOGUE, {"10932509": epl}, seen_at=NOW)
    assert linked.matched == 1 and brighton_event(db).betfair_event_id == "bf-1"
    assert db.get(ExchangeMarket, "1.1") is not None
    stats = ingest_books(db, [book()], seen_at=NOW)
    assert (stats.markets, stats.fair_prices, stats.unusable) == (1, 3, 0)
    fair = fair_by_label(db)
    assert fair["Brighton"].fair_prob == pytest.approx(expected_fair()["home"])
    assert sum(f.fair_prob for f in fair.values()) == pytest.approx(1.0)
    backs = db.scalars(select(LatestPrice).where(LatestPrice.source == PriceSource.BETFAIR))
    assert {p.side for p in backs} == {PriceSide.BACK, PriceSide.LAY}
    # The same prices a minute later: confirmed, but no new history.
    later = NOW + timedelta(minutes=1)
    assert ingest_books(db, [book()], seen_at=later).fair_prices == 0
    assert count(db, FairPrice) == 3
    assert fair_by_label(db)["Brighton"].as_of == later


def test_delayed_key_prices_count_as_older(db: Session, epl: Competition) -> None:
    sync_fixtures(db, epl, MATCHES, now=NOW)
    ingest_catalogue(db, CATALOGUE, {"10932509": epl}, seen_at=NOW)
    stats = ingest_books(db, [book(delayed=True)], seen_at=NOW)
    assert stats.delayed is True
    assert fair_by_label(db)["Brighton"].as_of == NOW - timedelta(minutes=3)


def test_thin_market_gives_no_fair_price(db: Session, epl: Competition) -> None:
    sync_fixtures(db, epl, MATCHES, now=NOW)
    ingest_catalogue(db, CATALOGUE, {"10932509": epl}, seen_at=NOW)
    stats = ingest_books(db, [book(draw_lay="4.2")], seen_at=NOW)  # draw gap 12%
    assert (stats.fair_prices, stats.unusable) == (0, 1)
    assert count(db, LatestFairPrice) == 0
    assert count(db, LatestPrice) == 6  # prices are still kept


# --- From feeds to a suggested bet --------------------------------------------------------


def load_everything(db: Session, epl: Competition) -> None:
    portfolio.add_ledger_entry(
        db, kind=LedgerKind.DEPOSIT, amount=D("2186.90"), now=NOW, actor="owner"
    )
    sync_fixtures(db, epl, MATCHES, now=NOW)
    ingest_catalogue(db, CATALOGUE, {"10932509": epl}, seen_at=NOW)
    ingest_books(db, [book()], seen_at=NOW)
    ingest_odds(db, epl, odds_events(), seen_at=NOW)


def test_value_bet_from_feed_data(db: Session, epl: Competition) -> None:
    load_everything(db, epl)
    run = run_value_finder(db, now=NOW + timedelta(seconds=30), tz=SYDNEY)
    assert run.considered >= 2
    (signal,) = run.created
    home_fair = expected_fair()["home"]
    assert signal.edge == edge(D("1.95"), home_fair)
    assert signal.edge >= D("0.03")
    assert signal.fair_price_id is not None
    assert signal.reason.startswith("Sportsbet pays 1.95 on Brighton (Match result).")
    notice = db.scalars(select(Notification).where(Notification.kind == "value_bet")).one()
    assert notice.title == f"Value bet: Brighton 1.95 at Sportsbet ({signal.edge:+.1%})"
    assert notice.body == signal.reason
    # Running again doesn't suggest the same bet twice.
    assert run_value_finder(db, now=NOW + timedelta(seconds=60), tz=SYDNEY).created == []


def test_a_paused_feed_stops_suggestions(db: Session, epl: Competition) -> None:
    load_everything(db, epl)
    feed_failed(db, BETFAIR, FeedAuthError("refused"), now=NOW)
    run = run_value_finder(db, now=NOW + timedelta(seconds=30), tz=SYDNEY)
    assert run.created == [] and run.skipped_because == "feeds paused: betfair"


def test_stale_prices_give_no_suggestion(db: Session, epl: Competition) -> None:
    load_everything(db, epl)
    run = run_value_finder(db, now=NOW + timedelta(minutes=20), tz=SYDNEY)  # 6h out: 15 min max
    assert run.created == []
