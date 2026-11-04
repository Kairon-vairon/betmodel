"""Behaviour that only the real database can prove."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from zoneinfo import ZoneInfo

import pytest
from alembic import command
from alembic.util.exc import CommandError
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from edgewise.api.main import create_app
from edgewise.auth import totp
from edgewise.config import Settings
from edgewise.db.models import (
    AuditEntry,
    Bookmaker,
    Competition,
    Event,
    LedgerKind,
    Market,
    ModelVersion,
    PriceSide,
    PriceSnapshot,
    PriceSource,
)
from edgewise.domain.finder import find_value
from edgewise.domain.limits import DEFAULT_LIMITS
from edgewise.domain.markets import MarketType, Selection
from edgewise.services import audit, portfolio, signals
from edgewise.services import auth as auth_service
from tests.conftest import SECRET_KEY, FakeClock
from tests.factories import add_book_price, candidate_for, make_match
from tests.integration.conftest import alembic_config

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 7, 9, 0, tzinfo=UTC)


def refused(session: Session, statement: str | Callable[[], None]) -> str:
    """Run something that the database must refuse; return the error text."""
    with pytest.raises((DBAPIError, IntegrityError)) as info, session.begin_nested():
        if callable(statement):
            statement()
        else:
            session.execute(text(statement))
        session.flush()
    return str(info.value)


def test_migrations_match_the_models(pg_engine: Engine, pg_url: str) -> None:
    try:
        command.check(alembic_config(pg_url))
    except CommandError as exc:  # pragma: no cover - only on drift
        pytest.fail(f"models and migrations differ: {exc}")


def test_reference_data_is_seeded(pg: Session) -> None:
    codes = set(pg.scalars(select(Competition.code)))
    assert codes == {"EPL", "LALIGA", "SERIEA", "BUNDESLIGA", "LIGUE1"}
    keys = set(pg.scalars(select(Bookmaker.key)))
    assert keys == {"sportsbet", "tab", "ladbrokes_au", "neds", "bet365_au"}
    live = pg.scalars(select(ModelVersion).where(ModelVersion.mode == "live")).one()
    assert (live.name, live.version) == ("reference-price", "v1")


def test_price_history_is_append_only(pg: Session) -> None:
    _, sel = make_match(pg, kickoff=NOW + timedelta(days=1))
    book = pg.scalars(select(Bookmaker).where(Bookmaker.key == "sportsbet")).one()
    add_book_price(pg, sel[Selection.HOME], book.id, "1.95", NOW)
    pg.flush()
    assert "append-only" in refused(pg, "UPDATE price_snapshots SET odds = 2.5")
    assert "append-only" in refused(pg, "DELETE FROM price_snapshots")
    assert "append-only" in refused(pg, "TRUNCATE price_snapshots CASCADE")
    assert pg.scalar(select(PriceSnapshot.odds)) == D("1.950")


def test_bankroll_ledger_and_audit_log_are_append_only(pg: Session) -> None:
    portfolio.add_ledger_entry(
        pg, kind=LedgerKind.DEPOSIT, amount=D("1000"), now=NOW, actor="owner"
    )
    pg.flush()
    assert "append-only" in refused(pg, "UPDATE bankroll_ledger SET amount = 1")
    assert "append-only" in refused(pg, "DELETE FROM bankroll_ledger")
    assert "append-only" in refused(pg, "UPDATE audit_log SET actor = 'someone'")
    assert "append-only" in refused(pg, "DELETE FROM audit_log")
    assert portfolio.bankroll(pg) == D("1000.00")


def test_check_constraints(pg: Session) -> None:
    _, sel = make_match(pg, kickoff=NOW + timedelta(days=1))
    book = pg.scalars(select(Bookmaker).where(Bookmaker.key == "tab")).one()

    def exchange_price_with_bookmaker() -> None:
        pg.add(
            PriceSnapshot(
                selection_id=sel[Selection.HOME],
                source=PriceSource.BETFAIR,
                bookmaker_id=book.id,
                side=PriceSide.BACK,
                odds=D("2"),
                captured_at=NOW,
            )
        )

    assert "bookmaker_matches_source" in refused(pg, exchange_price_with_bookmaker)
    assert "deposit_positive" in refused(
        pg,
        "INSERT INTO bankroll_ledger (kind, amount, balance_after) VALUES ('deposit', -5, -5)",
    )
    assert "pause_reason" in refused(pg, "INSERT INTO alert_pauses (reason) VALUES ('maybe')")


def test_one_match_result_market_per_event(pg: Session) -> None:
    event, _ = make_match(pg, kickoff=NOW + timedelta(days=1))

    def duplicate() -> None:
        pg.add(Market(event_id=event.id, type=MarketType.MATCH_RESULT))

    assert "uq_markets_event_id" in refused(pg, duplicate)
    pg.add(Market(event_id=event.id, type=MarketType.TOTAL_GOALS, line=D("2.5")))
    pg.add(Market(event_id=event.id, type=MarketType.TOTAL_GOALS, line=D("3.5")))
    pg.flush()


def test_times_round_trip_in_utc(pg: Session) -> None:
    sydney = datetime(2026, 11, 8, 2, 0, tzinfo=ZoneInfo("Australia/Sydney"))
    event, _ = make_match(pg, kickoff=sydney)
    pg.flush()
    pg.expire(event)
    assert event.kickoff_at == datetime(2026, 11, 7, 15, 0, tzinfo=UTC)
    assert event.kickoff_at.tzinfo is UTC

    def naive() -> None:
        event.kickoff_at = datetime(2026, 11, 8, 2, 0)
        pg.flush()

    with pytest.raises(Exception, match="naive datetime"):
        naive()
    pg.rollback()


def test_signal_lifecycle_on_postgres(pg: Session) -> None:
    portfolio.add_ledger_entry(
        pg, kind=LedgerKind.DEPOSIT, amount=D("2186.90"), now=NOW, actor="owner"
    )
    book = pg.scalars(select(Bookmaker).where(Bookmaker.key == "sportsbet")).one()
    event, sel = make_match(pg, kickoff=NOW + timedelta(hours=8))
    state = portfolio.portfolio_state(pg, now=NOW, tz=ZoneInfo("Australia/Sydney"))
    result = find_value([candidate_for(event, sel[Selection.HOME], book.id, NOW)], state, now=NOW)
    (signal,) = signals.record_suggestions(pg, result, now=NOW, bankroll=state.bankroll)
    assert signal.suggested_stake == D("33.00")
    add_book_price(pg, sel[Selection.HOME], book.id, "1.80", NOW + timedelta(minutes=5))
    pg.flush()
    expired = signals.expire_due(pg, now=NOW + timedelta(minutes=5), limits=DEFAULT_LIMITS)
    assert expired == [signal]
    assert pg.scalar(select(Event.allow_extra_bets).where(Event.id == event.id)) is False


def test_audit_details_are_stored_as_json(pg: Session) -> None:
    audit.record(pg, actor="owner", action="test", at=NOW, amount=D("12.50"), tags=["a", "b"])
    pg.flush()
    entry = pg.scalars(select(AuditEntry).where(AuditEntry.action == "test")).one()
    assert entry.details == {"amount": "12.5", "tags": ["a", "b"]}


def test_full_login_flow_on_postgres(pg_factory: sessionmaker[Session]) -> None:
    settings = Settings(app_secret_key=SECRET_KEY, database_url="unused", cookie_secure=True)
    clock = FakeClock(NOW)
    secret = totp.new_secret()
    with pg_factory() as session:
        auth_service.create_owner(
            session,
            settings,
            username="owner@example.com",
            password="a long enough password",
            totp_secret=secret,
            now=clock(),
        )
        session.commit()
    app = create_app(settings, pg_factory, clock)
    with TestClient(app, base_url="https://testserver") as client:
        body = {
            "username": "owner@example.com",
            "password": "a long enough password",
            "code": totp.code_at(secret, clock()),
        }
        assert client.post("/api/auth/login", json=body).status_code == 200
        assert client.get("/api/auth/me").json() == {"username": "owner@example.com"}
        assert client.get("/api/overview").status_code == 200
        assert client.get("/api/health").json()["status"] == "ok"
        assert client.post("/api/auth/logout").status_code == 204
        assert client.get("/api/auth/me").status_code == 401


def test_downgrade_and_upgrade_again(pg_engine: Engine, pg_url: str) -> None:
    config = alembic_config(pg_url)
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    with pg_engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM competitions")) == 5
