"""Owner login with 2FA (Milestone 1 acceptance: a working login)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from edgewise.db.models import AuditEntry, AuthSession
from tests.conftest import FakeClock, OwnerLogin

COOKIE = "__Host-edgewise_session"


def _login(client: TestClient, owner: OwnerLogin, clock: FakeClock, **overrides: str) -> object:
    body = {"username": owner.username, "password": owner.password, "code": owner.code(clock())}
    body.update(overrides)
    return client.post("/api/auth/login", json=body)


def test_health_is_public(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "stack": "live", "version": "0.1.0"}
    assert response.headers["cache-control"] == "no-store"


def test_login_sets_a_locked_down_cookie(
    client: TestClient, owner: OwnerLogin, clock: FakeClock
) -> None:
    response = _login(client, owner, clock)
    assert response.status_code == 200  # type: ignore[attr-defined]
    assert response.json() == {"username": owner.username}  # type: ignore[attr-defined]
    cookie = response.headers["set-cookie"]  # type: ignore[attr-defined]
    assert cookie.startswith(f"{COOKIE}=")
    for flag in ("HttpOnly", "Secure", "SameSite=strict", "Path=/"):
        assert flag.lower() in cookie.lower()
    assert "domain=" not in cookie.lower()
    assert client.get("/api/auth/me").json() == {"username": owner.username}


def test_username_is_case_insensitive(
    client: TestClient, owner: OwnerLogin, clock: FakeClock
) -> None:
    response = _login(client, owner, clock, username="  Owner@Example.COM ")
    assert response.status_code == 200  # type: ignore[attr-defined]


def test_everything_else_needs_a_session(client: TestClient) -> None:
    for path in ("/api/auth/me", "/api/limits", "/api/overview"):
        assert client.get(path).status_code == 401


def test_wrong_details_get_one_generic_answer(
    client: TestClient, owner: OwnerLogin, clock: FakeClock
) -> None:
    attempts = [
        {"password": "wrong password here"},
        {"code": "000000"},
        {"username": "someone@else.com"},
    ]
    for overrides in attempts:
        response = _login(client, owner, clock, **overrides)
        assert response.status_code == 401  # type: ignore[attr-defined]
        assert response.json() == {  # type: ignore[attr-defined]
            "detail": "That email, password or code isn't right."
        }
    assert "set-cookie" not in response.headers  # type: ignore[attr-defined]


def test_lockout_after_five_failures(
    client: TestClient, owner: OwnerLogin, clock: FakeClock, db: Session
) -> None:
    for _ in range(4):
        assert _login(client, owner, clock, password="nope nope nope").status_code == 401  # type: ignore[attr-defined]
    locked = _login(client, owner, clock, password="nope nope nope")
    assert locked.status_code == 429  # type: ignore[attr-defined]
    assert locked.json()["detail"] == "Too many attempts. Try again in 15 minutes."  # type: ignore[attr-defined]
    # Even the right details are refused while locked.
    assert _login(client, owner, clock).status_code == 429  # type: ignore[attr-defined]
    clock.advance(minutes=15, seconds=1)
    assert _login(client, owner, clock).status_code == 200  # type: ignore[attr-defined]
    actions = list(db.scalars(select(AuditEntry.action).order_by(AuditEntry.id)))
    assert actions.count("login_failed") == 5
    assert "login_locked" in actions
    assert actions[-1] == "login"


def test_a_code_cannot_be_used_twice(
    client: TestClient, owner: OwnerLogin, clock: FakeClock
) -> None:
    code = owner.code(clock())
    assert _login(client, owner, clock, code=code).status_code == 200  # type: ignore[attr-defined]
    client.post("/api/auth/logout")
    assert _login(client, owner, clock, code=code).status_code == 401  # type: ignore[attr-defined]
    clock.advance(seconds=30)
    assert _login(client, owner, clock).status_code == 200  # type: ignore[attr-defined]


def test_codes_from_the_neighbouring_30_seconds_are_accepted(
    client: TestClient, owner: OwnerLogin, clock: FakeClock
) -> None:
    previous = owner.code(clock() - __import__("datetime").timedelta(seconds=30))
    assert _login(client, owner, clock, code=previous).status_code == 200  # type: ignore[attr-defined]


def test_logout_revokes_the_session(
    client: TestClient, owner: OwnerLogin, clock: FakeClock, db: Session
) -> None:
    _login(client, owner, clock)
    token = client.cookies.get(COOKIE)
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401
    # The old token is dead on the server too, not just deleted from the browser.
    client.cookies.set(COOKIE, token or "", domain="testserver")
    assert client.get("/api/auth/me").status_code == 401
    assert db.scalar(select(AuthSession.revoked_at)) is not None


def test_sessions_expire_when_idle(client: TestClient, owner: OwnerLogin, clock: FakeClock) -> None:
    _login(client, owner, clock)
    clock.advance(hours=71)
    assert client.get("/api/auth/me").status_code == 200
    clock.advance(hours=71)  # idle timer restarted at the last visit
    assert client.get("/api/auth/me").status_code == 200
    clock.advance(hours=72)
    assert client.get("/api/auth/me").status_code == 401


def test_sessions_expire_after_seven_days_even_if_used(
    client: TestClient, owner: OwnerLogin, clock: FakeClock
) -> None:
    _login(client, owner, clock)
    for _ in range(6):
        clock.advance(hours=24)
        assert client.get("/api/auth/me").status_code == 200
    clock.advance(hours=24)
    assert client.get("/api/auth/me").status_code == 401


def test_session_tokens_are_stored_hashed(
    client: TestClient, owner: OwnerLogin, clock: FakeClock, db: Session
) -> None:
    _login(client, owner, clock)
    token = client.cookies.get(COOKIE)
    stored = db.scalar(select(AuthSession.token_hash))
    assert token and stored and token not in stored and len(stored) == 64


def test_cross_site_posts_are_refused(
    client: TestClient, owner: OwnerLogin, clock: FakeClock
) -> None:
    body = {"username": owner.username, "password": owner.password, "code": owner.code(clock())}
    response = client.post("/api/auth/login", json=body, headers={"Origin": "https://evil.example"})
    assert response.status_code == 403
    same = client.post("/api/auth/login", json=body, headers={"Origin": "https://testserver"})
    assert same.status_code == 200


def test_origin_may_match_the_forwarded_host(
    client: TestClient, owner: OwnerLogin, clock: FakeClock
) -> None:
    # A proxy that rewrites Host (e.g. a dev server) still passes the original host on.
    body = {"username": owner.username, "password": owner.password, "code": owner.code(clock())}
    headers = {"Origin": "http://localhost:5173", "X-Forwarded-Host": "localhost:5173"}
    assert client.post("/api/auth/login", json=body, headers=headers).status_code == 200
    evil = {"Origin": "https://evil.example", "X-Forwarded-Host": "localhost:5173"}
    assert client.post("/api/auth/logout", headers=evil).status_code == 403
