"""From stored prices to suggested bets: build candidates, run the value finder.

Every bookmaker price that has a fair probability for the same selection becomes a
candidate. The value finder (domain/finder.py) applies the edge rule and every safety
limit. Suggestions are stored as signals; nothing is placed (CLAUDE.md rule 1).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from edgewise.db.models import (
    Bookmaker,
    Event,
    EventStatus,
    LatestFairPrice,
    LatestPrice,
    Market,
    MarketSelection,
    PauseReason,
    PriceSide,
    PriceSource,
    Signal,
)
from edgewise.domain.finder import Candidate, find_value
from edgewise.domain.freshness import DEFAULT_FRESHNESS, FreshnessPolicy
from edgewise.domain.markets import MarketType
from edgewise.services import limits as limits_service
from edgewise.services import portfolio, signals
from edgewise.services.feeds import BETFAIR, ODDS, notify, paused_feeds

log = logging.getLogger(__name__)

MARKET_NAMES = {
    MarketType.MATCH_RESULT: "Match result",
    MarketType.TOTAL_GOALS: "Total goals",
    MarketType.BOTH_TEAMS_TO_SCORE: "Both teams to score",
    MarketType.ASIAN_HANDICAP: "Asian handicap",
    MarketType.DRAW_NO_BET: "Draw no bet",
}


def build_candidates(
    session: Session, *, now: datetime, horizon: timedelta = timedelta(days=7)
) -> tuple[list[Candidate], dict[int, int]]:
    """Candidates, and the fair-price history row behind each selection."""
    query = (
        select(MarketSelection, Market, Event, LatestFairPrice, LatestPrice, Bookmaker)
        .join(Market, MarketSelection.market_id == Market.id)
        .join(Event, Market.event_id == Event.id)
        .join(LatestFairPrice, LatestFairPrice.selection_id == MarketSelection.id)
        .join(
            LatestPrice,
            and_(
                LatestPrice.selection_id == MarketSelection.id,
                LatestPrice.source == PriceSource.ODDS_FEED,
                LatestPrice.side == PriceSide.BACK,
            ),
        )
        .join(Bookmaker, Bookmaker.id == LatestPrice.bookmaker_id)
        .where(
            Event.status == EventStatus.SCHEDULED,
            Event.kickoff_at > now,
            Event.kickoff_at <= now + horizon,
        )
    )
    candidates: list[Candidate] = []
    fair_rows: dict[int, int] = {}
    for selection, market, event, fair, price, book in session.execute(query):
        candidates.append(
            Candidate(
                event_id=event.id,
                selection_id=selection.id,
                bookmaker_id=book.id,
                offered_odds=price.odds,
                offered_at=price.last_seen_at,
                fair_prob=fair.fair_prob,
                fair_as_of=fair.as_of,
                kickoff=event.kickoff_at,
                bookmaker_name=book.name,
                selection_label=selection.label or selection.code.value,
                market_label=MARKET_NAMES[market.type],
            )
        )
        fair_rows[selection.id] = fair.fair_price_id
    return candidates, fair_rows


def value_bet_title(signal: Signal) -> str:
    """e.g. "Value bet: Brighton 1.95 at Sportsbet (+4.7%)"."""
    label = signal.selection.label or signal.selection.code.value
    return (
        f"Value bet: {label} {signal.offered_odds:.2f} at {signal.bookmaker.name} "
        f"({signal.edge:+.1%})"
    )


@dataclass
class FinderRun:
    created: list[Signal] = field(default_factory=list)
    considered: int = 0
    skipped_because: str | None = None


def run_value_finder(
    session: Session,
    *,
    now: datetime,
    tz: ZoneInfo,
    freshness: FreshnessPolicy = DEFAULT_FRESHNESS,
) -> FinderRun:
    paused = paused_feeds(session) & {ODDS, BETFAIR}
    if paused:
        return FinderRun(skipped_because=f"feeds paused: {', '.join(sorted(paused))}")
    try:
        limits = limits_service.current_limits(session)
    except ValueError:
        return FinderRun(skipped_because="stored safety limits are invalid")
    candidates, fair_rows = build_candidates(session, now=now)
    state = portfolio.portfolio_state(session, now=now, tz=tz)
    result = find_value(candidates, state, now=now, limits=limits, freshness=freshness)
    if result.drawdown_breached:
        portfolio.pause_alerts(
            session,
            PauseReason.DRAWDOWN_STOP,
            now=now,
            actor="system",
            detail="Drawdown stop reached while looking for value.",
        )
    if not result.suggestions:
        return FinderRun(considered=len(candidates))
    created = signals.record_suggestions(session, result, now=now, bankroll=state.bankroll)
    for signal in created:
        signal.fair_price_id = fair_rows.get(signal.selection_id)
        notify(
            session,
            kind="value_bet",
            now=now,
            title=value_bet_title(signal),
            body=signal.reason,
        )
    log.info("Value finder: %d candidates, %d new suggestion(s)", len(candidates), len(created))
    return FinderRun(created=created, considered=len(candidates))
