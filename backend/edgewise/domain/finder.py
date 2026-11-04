"""The value finder: decides which bookmaker prices become suggested bets.

HIGH-RISK CODE (CLAUDE.md rules 3 and 4): this is where the safety limits are applied.
Changes must be listed on their own under "High-risk changes" in the release notes.

A suggestion is only a suggestion. Nothing here places a bet (CLAUDE.md rule 1).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from edgewise.domain.freshness import DEFAULT_FRESHNESS, FreshnessPolicy
from edgewise.domain.limits import DEFAULT_LIMITS, SafetyLimits
from edgewise.domain.staking import (
    StakeCap,
    drawdown_breached,
    edge,
    min_acceptable_odds,
    size_stake,
)

STRATEGY_VERSION = "reference-price-v1"
CLOCK_SKEW = timedelta(seconds=60)  # a price stamped further in the future is not trusted


@dataclass(frozen=True)
class Candidate:
    """A bookmaker price for one selection, next to the fair probability for it."""

    event_id: int
    selection_id: int
    bookmaker_id: int
    offered_odds: Decimal
    offered_at: datetime  # when the bookmaker price was observed
    fair_prob: float
    fair_as_of: datetime  # when the exchange prices behind the fair price were observed
    kickoff: datetime
    bookmaker_name: str = ""
    selection_label: str = ""  # e.g. "Brighton" or "Under 2.5"
    market_label: str = ""  # e.g. "Match result"


@dataclass(frozen=True)
class BookmakerState:
    available: bool = True  # the owner has a usable account
    stake_limit: Decimal | None = None  # the most this bookmaker accepts from the owner


@dataclass(frozen=True)
class PortfolioState:
    bankroll: Decimal  # settled balance
    peak_bankroll: Decimal  # highest balance since alerts were last resumed
    alerts_paused: bool  # paused by the owner or by an earlier drawdown stop
    exposure_today: Decimal  # stake placed today + stake awaiting approval
    bookmakers: Mapping[int, BookmakerState]
    bets_per_event: Mapping[int, int] = field(default_factory=dict)  # awaiting + placed
    selections_with_bets: frozenset[int] = frozenset()  # awaiting + placed
    extra_bets_allowed: frozenset[int] = frozenset()  # matches the owner allowed more bets on


class Reject(StrEnum):
    ALERTS_PAUSED = "alerts_paused"
    DRAWDOWN_STOP = "drawdown_stop"
    NO_BANKROLL = "no_bankroll"
    KICKED_OFF = "kicked_off"
    STALE_BOOKMAKER_PRICE = "stale_bookmaker_price"
    STALE_FAIR_PRICE = "stale_fair_price"
    ODDS_OUT_OF_RANGE = "odds_out_of_range"
    EDGE_TOO_SMALL = "edge_too_small"
    BOOKMAKER_UNAVAILABLE = "bookmaker_unavailable"
    ALREADY_SUGGESTED = "already_suggested"
    ONE_BET_PER_MATCH = "one_bet_per_match"
    STAKE_TOO_SMALL = "stake_too_small"


@dataclass(frozen=True)
class Suggestion:
    candidate: Candidate
    edge: Decimal
    stake: Decimal
    kelly_stake: Decimal
    capped_by: StakeCap | None
    min_odds: Decimal
    expires_at: datetime
    reason: str
    strategy_version: str = STRATEGY_VERSION


@dataclass(frozen=True)
class Rejection:
    candidate: Candidate
    reasons: tuple[Reject, ...]
    edge: Decimal | None


@dataclass(frozen=True)
class FinderResult:
    suggestions: tuple[Suggestion, ...]
    rejections: tuple[Rejection, ...]
    # True when this run found the drawdown stop breached. The caller must persist the
    # pause so alerts stay off until the owner resumes them.
    drawdown_breached: bool


def find_value(
    candidates: Iterable[Candidate],
    state: PortfolioState,
    *,
    now: datetime,
    limits: SafetyLimits = DEFAULT_LIMITS,
    freshness: FreshnessPolicy = DEFAULT_FRESHNESS,
) -> FinderResult:
    pool = list(candidates)
    breached = drawdown_breached(state.bankroll, state.peak_bankroll, limits)

    blocking: list[Reject] = []
    if state.alerts_paused:
        blocking.append(Reject.ALERTS_PAUSED)
    if breached:
        blocking.append(Reject.DRAWDOWN_STOP)
    if state.bankroll <= 0:
        blocking.append(Reject.NO_BANKROLL)
    if blocking:
        return FinderResult(
            suggestions=(),
            rejections=tuple(Rejection(c, tuple(blocking), _safe_edge(c)) for c in pool),
            drawdown_breached=breached,
        )

    rejections: list[Rejection] = []
    passed: list[tuple[Candidate, Decimal]] = []
    for cand in pool:
        reasons, cand_edge = _static_checks(cand, state, now, limits, freshness)
        if reasons:
            rejections.append(Rejection(cand, tuple(reasons), cand_edge))
        else:
            assert cand_edge is not None
            passed.append((cand, cand_edge))

    # Best opportunities first: expected profit at full size, then edge, then price.
    def priority(item: tuple[Candidate, Decimal]) -> tuple[Decimal, Decimal, Decimal, int, int]:
        cand, cand_edge = item
        book = state.bookmakers[cand.bookmaker_id]
        full = size_stake(
            odds=cand.offered_odds,
            fair_prob=cand.fair_prob,
            bankroll=state.bankroll,
            limits=limits,
            exposure_today=Decimal(0),
            bookmaker_limit=book.stake_limit,
        )
        return (
            -(cand_edge * full.stake),
            -cand_edge,
            -cand.offered_odds,
            cand.event_id,
            cand.bookmaker_id,
        )

    passed.sort(key=priority)

    exposure = state.exposure_today
    per_event: Counter[int] = Counter(state.bets_per_event)
    taken_selections = set(state.selections_with_bets)
    suggestions: list[Suggestion] = []

    for cand, cand_edge in passed:
        if cand.selection_id in taken_selections:
            rejections.append(Rejection(cand, (Reject.ALREADY_SUGGESTED,), cand_edge))
            continue
        if _match_full(cand.event_id, per_event, state, limits):
            rejections.append(Rejection(cand, (Reject.ONE_BET_PER_MATCH,), cand_edge))
            continue
        decision = size_stake(
            odds=cand.offered_odds,
            fair_prob=cand.fair_prob,
            bankroll=state.bankroll,
            limits=limits,
            exposure_today=exposure,
            bookmaker_limit=state.bookmakers[cand.bookmaker_id].stake_limit,
        )
        if decision.stake < limits.min_stake:
            rejections.append(Rejection(cand, (Reject.STAKE_TOO_SMALL,), cand_edge))
            continue

        min_odds = min_acceptable_odds(cand.fair_prob, limits.min_odds_edge)
        suggestions.append(
            Suggestion(
                candidate=cand,
                edge=cand_edge,
                stake=decision.stake,
                kelly_stake=decision.kelly_stake,
                capped_by=decision.capped_by,
                min_odds=min_odds,
                expires_at=min(now + limits.approval_window, cand.kickoff),
                reason=describe(cand, cand_edge, decision.capped_by),
            )
        )
        exposure += decision.stake
        per_event[cand.event_id] += 1
        taken_selections.add(cand.selection_id)

    return FinderResult(
        suggestions=tuple(suggestions), rejections=tuple(rejections), drawdown_breached=False
    )


def _static_checks(
    cand: Candidate,
    state: PortfolioState,
    now: datetime,
    limits: SafetyLimits,
    freshness: FreshnessPolicy,
) -> tuple[list[Reject], Decimal | None]:
    reasons: list[Reject] = []
    if now >= cand.kickoff:
        reasons.append(Reject.KICKED_OFF)
    if cand.offered_at > now + CLOCK_SKEW or not freshness.bookmaker_fresh(
        cand.offered_at, now, cand.kickoff
    ):
        reasons.append(Reject.STALE_BOOKMAKER_PRICE)
    if cand.fair_as_of > now + CLOCK_SKEW or not freshness.exchange_fresh(
        cand.fair_as_of, now, cand.kickoff
    ):
        reasons.append(Reject.STALE_FAIR_PRICE)
    if not limits.min_odds <= cand.offered_odds <= limits.max_odds:
        reasons.append(Reject.ODDS_OUT_OF_RANGE)
    cand_edge = _safe_edge(cand)
    if cand_edge is None or cand_edge < limits.min_edge:
        reasons.append(Reject.EDGE_TOO_SMALL)
    book = state.bookmakers.get(cand.bookmaker_id)
    if book is None or not book.available:
        reasons.append(Reject.BOOKMAKER_UNAVAILABLE)
    if cand.selection_id in state.selections_with_bets:
        reasons.append(Reject.ALREADY_SUGGESTED)
    elif _match_full(cand.event_id, Counter(state.bets_per_event), state, limits):
        reasons.append(Reject.ONE_BET_PER_MATCH)
    return reasons, cand_edge


def _match_full(
    event_id: int, per_event: Mapping[int, int], state: PortfolioState, limits: SafetyLimits
) -> bool:
    if event_id in state.extra_bets_allowed:
        return False
    return per_event.get(event_id, 0) >= limits.max_bets_per_match


def _safe_edge(cand: Candidate) -> Decimal | None:
    try:
        return edge(cand.offered_odds, cand.fair_prob)
    except ValueError:
        return None


_CAP_TEXT = {
    StakeCap.MAX_STAKE: "capped at the 2%-of-bankroll limit",
    StakeCap.BOOKMAKER_LIMIT: "capped by your account limit at this bookmaker",
    StakeCap.DAILY_EXPOSURE: "capped by today's exposure limit",
}


def describe(cand: Candidate, cand_edge: Decimal, capped_by: StakeCap | None) -> str:
    """One plain-English sentence on why this is value, for the owner."""
    fair_odds = 1 / cand.fair_prob
    who = cand.bookmaker_name or "The bookmaker"
    what = cand.selection_label or "this selection"
    market = f" ({cand.market_label})" if cand.market_label else ""
    text = (
        f"{who} pays {cand.offered_odds:.2f} on {what}{market}. Betfair's fair price is "
        f"{fair_odds:.2f} ({cand.fair_prob:.1%} chance), so the edge is {cand_edge:+.1%}."
    )
    if capped_by is not None:
        text += f" Stake {_CAP_TEXT[capped_by]}."
    return text
