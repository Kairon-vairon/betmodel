"""Feed health: pause after repeated failures, exactly one notice per outage."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from edgewise.db.models import FeedStatus, Notification
from edgewise.feeds.common import FeedAuthError, FeedError, FeedRateLimited
from edgewise.services.feeds import ODDS, feed_failed, feed_succeeded, paused_feeds

NOW = datetime(2026, 11, 7, 9, 0, tzinfo=UTC)


def notices(db: Session) -> list[Notification]:
    return list(db.scalars(select(Notification).order_by(Notification.id)))


def test_three_failures_in_a_row_pause_with_one_notice(db: Session) -> None:
    assert feed_failed(db, ODDS, FeedError("timeout"), now=NOW) is False
    assert feed_failed(db, ODDS, FeedError("timeout"), now=NOW + timedelta(minutes=5)) is False
    assert paused_feeds(db) == set()
    assert feed_failed(db, ODDS, FeedError("timeout"), now=NOW + timedelta(minutes=10)) is True
    assert paused_feeds(db) == {ODDS}
    for minutes in (15, 20, 25):  # still failing: no more notices
        feed_failed(db, ODDS, FeedError("timeout"), now=NOW + timedelta(minutes=minutes))
    (notice,) = notices(db)
    assert notice.kind == "feed_paused"
    assert notice.title == "Bookmaker odds (The Odds API) has stopped"
    assert "retried automatically" in notice.body


def test_a_success_resets_the_count(db: Session) -> None:
    feed_failed(db, ODDS, FeedError("timeout"), now=NOW)
    feed_failed(db, ODDS, FeedError("timeout"), now=NOW)
    feed_succeeded(db, ODDS, now=NOW)
    feed_failed(db, ODDS, FeedError("timeout"), now=NOW)
    assert paused_feeds(db) == set() and notices(db) == []


def test_a_refused_key_pauses_at_once(db: Session) -> None:
    assert feed_failed(db, ODDS, FeedAuthError("The Odds API refused the key"), now=NOW)
    (notice,) = notices(db)
    assert "check it in the settings file" in notice.body


def test_used_up_allowance_says_so(db: Session) -> None:
    for _ in range(3):
        feed_failed(db, ODDS, FeedRateLimited("allowance used up"), now=NOW)
    assert "allowance is used up" in notices(db)[0].body


def test_recovery_unpauses_with_one_notice(db: Session) -> None:
    feed_failed(db, ODDS, FeedAuthError("refused"), now=NOW)
    feed_succeeded(db, ODDS, now=NOW + timedelta(hours=1), details={"credits_remaining": 400})
    feed_succeeded(db, ODDS, now=NOW + timedelta(hours=2))
    assert paused_feeds(db) == set()
    assert [n.kind for n in notices(db)] == ["feed_paused", "feed_recovered"]
    status = db.get(FeedStatus, ODDS)
    assert status is not None and status.details == {"credits_remaining": 400}
    assert status.last_error is None and status.consecutive_failures == 0
