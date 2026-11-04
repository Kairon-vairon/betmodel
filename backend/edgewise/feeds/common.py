"""Shared pieces for the feed clients."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from edgewise import __version__


class FeedError(Exception):
    """The feed failed this time. Trying again later may work."""


class FeedAuthError(FeedError):
    """The key or login was refused. Retrying won't help until it is fixed."""


class FeedRateLimited(FeedError):
    """The feed's request allowance is used up for now."""


@dataclass(frozen=True)
class Quota:
    remaining: int | None = None
    used: int | None = None


def make_http(
    *, timeout: float = 20.0, transport: httpx.BaseTransport | None = None
) -> httpx.Client:
    return httpx.Client(
        timeout=timeout,
        headers={"User-Agent": f"Edgewise/{__version__}"},
        transport=transport,
    )


def parse_time(value: str) -> datetime:
    """ISO 8601 with a zone (Z or +hh:mm) to an aware UTC datetime."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"time without a zone: {value}")
    return parsed.astimezone(UTC)


def to_int(value: str | None) -> int | None:
    try:
        return int(float(value)) if value is not None else None
    except ValueError:
        return None


def to_odds(value: Any) -> Decimal | None:
    """Decimal odds above 1.0, or None for anything unusable."""
    try:
        odds = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return odds if odds.is_finite() and odds > 1 else None


def error_message(response: httpx.Response, fallback: str) -> str:
    """A short reason from an error response, never including the request URL (which
    may carry the API key)."""
    try:
        body = response.json()
    except ValueError:
        return f"{fallback} (HTTP {response.status_code})"
    if isinstance(body, dict):
        for key in ("message", "error", "detail"):
            if isinstance(body.get(key), str):
                return f"{body[key]} (HTTP {response.status_code})"
    return f"{fallback} (HTTP {response.status_code})"
