"""Refusing state-changing requests from other websites (CSRF), behind any proxy."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from edgewise.api.main import is_cross_site
from tests.conftest import FakeClock, OwnerLogin

HOST = {"host": "edgewise.example.com"}


@pytest.mark.parametrize(
    ("headers", "refused"),
    [
        # Modern browsers: Sec-Fetch-Site decides, whatever a proxy did to Host.
        ({"sec-fetch-site": "same-origin", "origin": "https://edgewise.example.com"}, False),
        ({"sec-fetch-site": "same-origin", "origin": "https://preview.example"}, False),
        ({"sec-fetch-site": "none"}, False),
        ({"sec-fetch-site": "cross-site", "origin": "https://edgewise.example.com"}, True),
        ({"sec-fetch-site": "same-site", "origin": "https://evil.example.com"}, True),
        # Older browsers: Origin must match Host (or X-Forwarded-Host).
        ({"origin": "https://edgewise.example.com"}, False),
        ({"origin": "https://evil.example"}, True),
        ({"origin": "https://edgewise.example.com", "host": "api:8000"}, True),
        (
            {
                "origin": "https://edgewise.example.com",
                "host": "api:8000",
                "x-forwarded-host": "edgewise.example.com",
            },
            False,
        ),
        # No browser headers at all (curl, scripts): not a cross-site page.
        ({}, False),
    ],
)
def test_unsafe_methods(headers: dict[str, str], refused: bool) -> None:
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        assert is_cross_site(method, {**HOST, **headers}) is refused


def test_reading_is_never_refused() -> None:
    assert is_cross_site("GET", {**HOST, "sec-fetch-site": "cross-site"}) is False


def test_sign_in_through_a_proxy_that_rewrites_host(
    client: TestClient, owner: OwnerLogin, clock: FakeClock
) -> None:
    body = {"username": owner.username, "password": owner.password, "code": owner.code(clock())}
    # The browser is on https://preview.example; the proxy sent Host: testserver.
    headers = {"Origin": "https://preview.example", "Sec-Fetch-Site": "same-origin"}
    assert client.post("/api/auth/login", json=body, headers=headers).status_code == 200
    attack = {"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"}
    assert client.post("/api/auth/logout", headers=attack).status_code == 403
    assert client.get("/api/auth/me").status_code == 200  # still signed in
