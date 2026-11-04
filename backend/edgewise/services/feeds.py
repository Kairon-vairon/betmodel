"""Feed health (CLAUDE.md rule 7): a failing feed pauses the alerts that depend on it.

A feed is paused after three failures in a row, or at once if its key or login is
refused. The owner gets exactly one notice when it stops and one when it is back, not
one per failed request.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from edgewise.db.models import FeedStatus, Notification
from edgewise.feeds.common import FeedAuthError, FeedRateLimited
from edgewise.services import audit

FIXTURES = "fixtures"
ODDS = "odds_feed"
BETFAIR = "betfair"
FEEDS = (FIXTURES, ODDS, BETFAIR)
FEED_NAMES = {
    FIXTURES: "Fixtures and results (API-Football)",
    ODDS: "Bookmaker odds (The Odds API)",
    BETFAIR: "Betfair Exchange prices",
}
PAUSE_AFTER_FAILURES = 3


def notify(session: Session, *, kind: str, title: str, body: str, now: datetime) -> Notification:
    notice = Notification(kind=kind, title=title, body=body, created_at=now)
    session.add(notice)
    return notice


def _status(session: Session, feed: str) -> FeedStatus:
    status = session.get(FeedStatus, feed)
    if status is None:
        status = FeedStatus(feed=feed, consecutive_failures=0, paused=False, details={})
        session.add(status)
    return status


def feed_succeeded(
    session: Session, feed: str, *, now: datetime, details: dict[str, Any] | None = None
) -> None:
    status = _status(session, feed)
    status.last_attempt_at = status.last_success_at = now
    status.consecutive_failures = 0
    status.last_error = None
    if details:
        status.details = {**(status.details or {}), **details}
    if status.paused:
        status.paused, status.paused_since = False, None
        notify(
            session,
            kind="feed_recovered",
            now=now,
            title=f"{FEED_NAMES[feed]} is working again",
            body="Its prices are being used again.",
        )
        audit.record(
            session,
            actor="worker",
            action="feed_resumed",
            at=now,
            entity_type="feed",
            entity_id=feed,
        )


def feed_failed(session: Session, feed: str, error: Exception, *, now: datetime) -> bool:
    """Record a failure. Returns True if this failure paused the feed."""
    status = _status(session, feed)
    status.last_attempt_at = status.last_error_at = now
    status.last_error = str(error)[:500]
    status.consecutive_failures = (status.consecutive_failures or 0) + 1
    refused = isinstance(error, FeedAuthError)
    if status.paused or not (refused or status.consecutive_failures >= PAUSE_AFTER_FAILURES):
        return False
    status.paused, status.paused_since, status.owner_notified_at = True, now, now
    if refused:
        hint = "The key or login was refused: check it in the settings file, then restart."
    elif isinstance(error, FeedRateLimited):
        hint = "Its request allowance is used up: it resumes when the allowance resets."
    else:
        hint = "It will be retried automatically."
    notify(
        session,
        kind="feed_paused",
        now=now,
        title=f"{FEED_NAMES[feed]} has stopped",
        body=f"Value bets that need it are paused. {hint} ({status.last_error})",
    )
    audit.record(
        session,
        actor="worker",
        action="feed_paused",
        at=now,
        entity_type="feed",
        entity_id=feed,
        error=status.last_error,
    )
    return True


def paused_feeds(session: Session) -> set[str]:
    return set(session.scalars(select(FeedStatus.feed).where(FeedStatus.paused.is_(True))))
