from __future__ import annotations

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from edgewise.config import Settings
from edgewise.db.models import LedgerKind
from edgewise.db.session import transaction
from edgewise.services import limits as limits_service
from edgewise.services import portfolio
from edgewise.worker.main import Worker
from tests.conftest import FakeClock, OwnerLogin


def _sign_in(client: TestClient, owner: OwnerLogin, clock: FakeClock) -> None:
    body = {"username": owner.username, "password": owner.password, "code": owner.code(clock())}
    assert client.post("/api/auth/login", json=body).status_code == 200


def test_limits_show_defaults_and_owner_changes(
    client: TestClient, owner: OwnerLogin, clock: FakeClock, session_factory: sessionmaker[Session]
) -> None:
    _sign_in(client, owner, clock)
    data = client.get("/api/limits").json()
    assert data["valid"] is True
    by_name = {item["name"]: item for item in data["limits"]}
    assert Decimal(by_name["max_stake_fraction"]["value"]) == Decimal("0.02")
    assert by_name["max_stake_fraction"]["changed"] is False

    with transaction(session_factory) as session:
        limits_service.set_limit(
            session, "max_stake_fraction", Decimal("0.015"), changed_by="owner", now=clock()
        )
    by_name = {item["name"]: item for item in client.get("/api/limits").json()["limits"]}
    assert Decimal(by_name["max_stake_fraction"]["value"]) == Decimal("0.015")
    assert by_name["max_stake_fraction"]["changed"] is True


def test_overview_reports_bankroll_limits_and_worker(
    client: TestClient,
    owner: OwnerLogin,
    clock: FakeClock,
    settings: Settings,
    session_factory: sessionmaker[Session],
) -> None:
    _sign_in(client, owner, clock)
    empty = client.get("/api/overview").json()
    assert Decimal(empty["bankroll"]) == 0
    assert empty["alerts_paused"] is False
    assert empty["feeds"] == [] and empty["workers"] == []

    with transaction(session_factory) as session:
        portfolio.add_ledger_entry(
            session,
            kind=LedgerKind.DEPOSIT,
            amount=Decimal("2186.90"),
            now=clock(),
            actor="owner",
        )
    Worker(settings, session_factory, clock=clock, name="worker-test").heartbeat()

    data = client.get("/api/overview").json()
    assert Decimal(data["bankroll"]) == Decimal("2186.90")
    assert Decimal(data["daily_exposure_limit"]) == Decimal("174.95")
    assert Decimal(data["max_stake"]) == Decimal("43")
    assert data["workers"][0]["worker"] == "worker-test"
    assert data["workers"][0]["healthy"] is True
    clock.advance(minutes=5)
    assert client.get("/api/overview").json()["workers"][0]["healthy"] is False
