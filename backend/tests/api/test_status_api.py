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
    assert [(f["feed"], f["state"]) for f in empty["feeds"]] == [
        ("fixtures", "not_configured"),
        ("odds_feed", "not_configured"),
        ("betfair", "not_configured"),
    ]
    assert empty["notices"] == [] and empty["workers"] == []

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


def test_overview_shows_each_feed_and_recent_notices(
    owner: OwnerLogin,
    clock: FakeClock,
    session_factory: sessionmaker[Session],
) -> None:
    from fastapi.testclient import TestClient as Client
    from pydantic import SecretStr

    from edgewise.api.main import create_app
    from edgewise.feeds.common import FeedAuthError
    from edgewise.services.feeds import BETFAIR, ODDS, feed_failed, feed_succeeded
    from tests.conftest import SECRET_KEY

    settings = Settings(
        app_secret_key=SECRET_KEY,
        database_url="sqlite://",
        cookie_secure=True,
        odds_api_key=SecretStr("k"),
        betfair_app_key=SecretStr("a"),
        betfair_username="u",
        betfair_password=SecretStr("p"),
    )
    with transaction(session_factory) as session:
        feed_succeeded(session, ODDS, now=clock(), details={"credits_remaining": 480})
        feed_failed(session, BETFAIR, FeedAuthError("Betfair refused the login"), now=clock())
    with Client(create_app(settings, session_factory, clock), base_url="https://testserver") as c:
        _sign_in(c, owner, clock)
        data = c.get("/api/overview").json()
    feeds = {f["feed"]: f for f in data["feeds"]}
    assert feeds["fixtures"]["state"] == "not_configured"
    assert feeds["odds_feed"]["state"] == "ok"
    assert feeds["odds_feed"]["details"] == {"credits_remaining": 480}
    assert feeds["betfair"]["state"] == "paused"
    assert feeds["betfair"]["last_error"] == "Betfair refused the login"
    (notice,) = data["notices"]
    assert notice["kind"] == "feed_paused"
    assert notice["title"] == "Betfair Exchange prices has stopped"
