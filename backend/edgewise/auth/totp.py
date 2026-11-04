"""Six-digit authenticator-app codes (TOTP, RFC 6238)."""

from __future__ import annotations

import hmac
from datetime import datetime

import pyotp

ISSUER = "Edgewise"
INTERVAL_SECONDS = 30


def new_secret() -> str:
    return pyotp.random_base32(length=32)


def provisioning_uri(secret: str, username: str) -> str:
    return pyotp.TOTP(secret, interval=INTERVAL_SECONDS).provisioning_uri(
        name=username, issuer_name=ISSUER
    )


def code_at(secret: str, at: datetime) -> str:
    return pyotp.TOTP(secret, interval=INTERVAL_SECONDS).at(int(at.timestamp()))


def verify(
    secret: str, code: str, *, now: datetime, last_step: int | None, window: int = 1
) -> int | None:
    """Return the time step the code belongs to, or None if it is wrong or already used.

    Accepts the previous and next 30-second code to allow for clock drift. A code (or an
    older one) that was already used to log in is refused, so a stolen code can't be
    replayed.
    """
    cleaned = code.replace(" ", "").strip()
    if len(cleaned) != 6 or not cleaned.isdigit():
        return None
    totp = pyotp.TOTP(secret, interval=INTERVAL_SECONDS)
    current = int(now.timestamp()) // INTERVAL_SECONDS
    for step in range(current - window, current + window + 1):
        if last_step is not None and step <= last_step:
            continue
        if hmac.compare_digest(totp.at(step * INTERVAL_SECONDS), cleaned):
            return step
    return None
