"""Tables. First cut of the data model in docs/ARCHITECTURE.md, plus login tables.

Append-only tables (price_snapshots, bankroll_ledger, audit_log) are protected by
database triggers in the migrations: rows can be added, never changed or deleted.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from edgewise.db.base import (
    Base,
    BigID,
    JSONType,
    Money,
    Odds,
    Probability,
    Ratio,
    UTCDateTime,
    str_enum,
    utcnow,
)
from edgewise.domain.lifecycle import ExpiryReason, SignalStatus
from edgewise.domain.markets import MarketType, Selection
from edgewise.domain.settlement import Outcome
from edgewise.domain.staking import StakeCap


def _created() -> Any:
    return mapped_column(UTCDateTime, default=utcnow, server_default=sa.func.now())


# --- Fixtures -----------------------------------------------------------------------------


class Competition(Base):
    __tablename__ = "competitions"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(sa.String(16), unique=True)
    name: Mapped[str] = mapped_column(sa.String(64))
    country: Mapped[str] = mapped_column(sa.String(32))
    betfair_competition_id: Mapped[str | None] = mapped_column(sa.String(32))
    odds_api_sport_key: Mapped[str | None] = mapped_column(sa.String(64))
    api_football_league_id: Mapped[int | None]
    active: Mapped[bool] = mapped_column(default=True, server_default=sa.true())


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(sa.String(80), unique=True)
    country: Mapped[str | None] = mapped_column(sa.String(32))

    aliases: Mapped[list[TeamAlias]] = relationship(back_populates="team")


class TeamAlias(Base):
    """How each data feed spells a team's name, so feeds can be matched up."""

    __tablename__ = "team_aliases"
    __table_args__ = (sa.UniqueConstraint("source", "alias"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(sa.ForeignKey("teams.id", ondelete="CASCADE"))
    source: Mapped[str] = mapped_column(sa.String(32))
    alias: Mapped[str] = mapped_column(sa.String(120))

    team: Mapped[Team] = relationship(back_populates="aliases")


class EventStatus(StrEnum):
    SCHEDULED = "scheduled"
    LIVE = "live"
    FINISHED = "finished"
    POSTPONED = "postponed"
    CANCELLED = "cancelled"
    ABANDONED = "abandoned"


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        sa.CheckConstraint("home_team_id <> away_team_id", name="different_teams"),
        sa.CheckConstraint("(home_goals IS NULL) = (away_goals IS NULL)", name="score_complete"),
        sa.CheckConstraint("home_goals >= 0 AND away_goals >= 0", name="score_not_negative"),
        sa.Index("ix_events_status_kickoff", "status", "kickoff_at"),
        sa.Index("ix_events_competition_kickoff", "competition_id", "kickoff_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    competition_id: Mapped[int] = mapped_column(sa.ForeignKey("competitions.id"))
    home_team_id: Mapped[int] = mapped_column(sa.ForeignKey("teams.id"))
    away_team_id: Mapped[int] = mapped_column(sa.ForeignKey("teams.id"))
    kickoff_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    status: Mapped[EventStatus] = mapped_column(
        str_enum(EventStatus, "event_status"), default=EventStatus.SCHEDULED
    )
    home_goals: Mapped[int | None]
    away_goals: Mapped[int | None]
    result_source: Mapped[str | None] = mapped_column(sa.String(32))
    result_recorded_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    betfair_event_id: Mapped[str | None] = mapped_column(sa.String(32), unique=True)
    odds_api_event_id: Mapped[str | None] = mapped_column(sa.String(64), unique=True)
    api_football_fixture_id: Mapped[int | None] = mapped_column(unique=True)
    # Correlation guard override: the owner allowed more than one bet on this match.
    allow_extra_bets: Mapped[bool] = mapped_column(default=False, server_default=sa.false())
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, onupdate=utcnow, server_default=sa.func.now()
    )

    competition: Mapped[Competition] = relationship()
    home_team: Mapped[Team] = relationship(foreign_keys=[home_team_id])
    away_team: Mapped[Team] = relationship(foreign_keys=[away_team_id])
    markets: Mapped[list[Market]] = relationship(back_populates="event")


class Market(Base):
    __tablename__ = "markets"
    __table_args__ = (
        sa.UniqueConstraint("event_id", "type", "line", postgresql_nulls_not_distinct=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(sa.ForeignKey("events.id", ondelete="CASCADE"))
    type: Mapped[MarketType] = mapped_column(str_enum(MarketType, "market_type"))
    line: Mapped[Decimal | None] = mapped_column(sa.Numeric(5, 2))
    betfair_market_id: Mapped[str | None] = mapped_column(sa.String(32), unique=True)

    event: Mapped[Event] = relationship(back_populates="markets")
    selections: Mapped[list[MarketSelection]] = relationship(back_populates="market")


class MarketSelection(Base):
    __tablename__ = "selections"
    __table_args__ = (sa.UniqueConstraint("market_id", "code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    market_id: Mapped[int] = mapped_column(sa.ForeignKey("markets.id", ondelete="CASCADE"))
    code: Mapped[Selection] = mapped_column(str_enum(Selection, "selection_code"))
    label: Mapped[str | None] = mapped_column(sa.String(80))  # e.g. "Brighton", "Under 2.5"
    betfair_selection_id: Mapped[int | None] = mapped_column(sa.BigInteger)

    market: Mapped[Market] = relationship(back_populates="selections")


# --- Bookmakers and prices ----------------------------------------------------------------


class AccountStatus(StrEnum):
    ACTIVE = "active"
    LIMITED = "limited"  # restricted stakes; see stake_limit
    CLOSED = "closed"
    NO_ACCOUNT = "no_account"


class Bookmaker(Base):
    __tablename__ = "bookmakers"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(sa.String(32), unique=True)  # odds-feed key
    name: Mapped[str] = mapped_column(sa.String(64))
    account_status: Mapped[AccountStatus] = mapped_column(
        str_enum(AccountStatus, "account_status"), default=AccountStatus.ACTIVE
    )
    stake_limit: Mapped[Decimal | None] = mapped_column(Money)
    notes: Mapped[str | None] = mapped_column(sa.Text)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, onupdate=utcnow, server_default=sa.func.now()
    )


class PriceSource(StrEnum):
    ODDS_FEED = "odds_feed"  # bookmaker prices from the licensed odds feed
    BETFAIR = "betfair"  # Betfair Exchange (read-only in Phase 1)


class PriceSide(StrEnum):
    BACK = "back"
    LAY = "lay"


class PriceSnapshot(Base):
    """Our own odds history. Append-only."""

    __tablename__ = "price_snapshots"
    __table_args__ = (
        sa.CheckConstraint("odds > 1", name="odds_above_one"),
        sa.CheckConstraint(
            "(source = 'betfair') = (bookmaker_id IS NULL)", name="bookmaker_matches_source"
        ),
        sa.Index(
            "ix_price_snapshots_lookup", "selection_id", "source", "bookmaker_id", "captured_at"
        ),
        sa.Index("ix_price_snapshots_captured_at", "captured_at"),
    )

    id: Mapped[int] = mapped_column(BigID, primary_key=True)
    selection_id: Mapped[int] = mapped_column(sa.ForeignKey("selections.id"))
    source: Mapped[PriceSource] = mapped_column(str_enum(PriceSource, "price_source"))
    bookmaker_id: Mapped[int | None] = mapped_column(sa.ForeignKey("bookmakers.id"))
    side: Mapped[PriceSide] = mapped_column(str_enum(PriceSide, "price_side"))
    odds: Mapped[Decimal] = mapped_column(Odds)
    size: Mapped[Decimal | None] = mapped_column(sa.Numeric(14, 2))  # money available
    captured_at: Mapped[datetime] = mapped_column(UTCDateTime)  # as-of time of the price
    received_at: Mapped[datetime] = _created()


class FairPrice(Base):
    __tablename__ = "fair_prices"
    __table_args__ = (
        sa.CheckConstraint("fair_prob > 0 AND fair_prob < 1", name="probability_range"),
        sa.Index("ix_fair_prices_lookup", "selection_id", "as_of"),
    )

    id: Mapped[int] = mapped_column(BigID, primary_key=True)
    selection_id: Mapped[int] = mapped_column(sa.ForeignKey("selections.id"))
    fair_prob: Mapped[float] = mapped_column(Probability)
    method: Mapped[str] = mapped_column(sa.String(32))
    mid_overround: Mapped[float] = mapped_column(Probability)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    as_of: Mapped[datetime] = mapped_column(UTCDateTime)  # when the exchange prices were seen
    computed_at: Mapped[datetime] = _created()


class LatestPrice(Base):
    """The newest price for each selection, source, bookmaker and side, with when it was
    last confirmed by the feed. Freshness checks use last_seen_at; price_snapshots keeps
    the history, one row per change."""

    __tablename__ = "latest_prices"
    __table_args__ = (
        sa.UniqueConstraint(
            "selection_id", "source", "bookmaker_id", "side", postgresql_nulls_not_distinct=True
        ),
        sa.CheckConstraint("odds > 1", name="odds_above_one"),
        sa.CheckConstraint(
            "(source = 'betfair') = (bookmaker_id IS NULL)", name="bookmaker_matches_source"
        ),
    )

    id: Mapped[int] = mapped_column(BigID, primary_key=True)
    selection_id: Mapped[int] = mapped_column(sa.ForeignKey("selections.id", ondelete="CASCADE"))
    source: Mapped[PriceSource] = mapped_column(str_enum(PriceSource, "latest_price_source"))
    bookmaker_id: Mapped[int | None] = mapped_column(sa.ForeignKey("bookmakers.id"))
    side: Mapped[PriceSide] = mapped_column(str_enum(PriceSide, "latest_price_side"))
    odds: Mapped[Decimal] = mapped_column(Odds)
    size: Mapped[Decimal | None] = mapped_column(sa.Numeric(14, 2))
    price_time: Mapped[datetime | None] = mapped_column(UTCDateTime)  # the feed's own stamp
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime)  # this price since
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime)  # last confirmed current


class LatestFairPrice(Base):
    """The current fair probability for a selection and when it was last confirmed."""

    __tablename__ = "latest_fair_prices"
    __table_args__ = (
        sa.CheckConstraint("fair_prob > 0 AND fair_prob < 1", name="probability_range"),
    )

    selection_id: Mapped[int] = mapped_column(
        sa.ForeignKey("selections.id", ondelete="CASCADE"), primary_key=True
    )
    fair_prob: Mapped[float] = mapped_column(Probability)
    method: Mapped[str] = mapped_column(sa.String(32))
    mid_overround: Mapped[float] = mapped_column(Probability)
    fair_price_id: Mapped[int] = mapped_column(sa.ForeignKey("fair_prices.id"))
    changed_at: Mapped[datetime] = mapped_column(UTCDateTime)  # this value since
    as_of: Mapped[datetime] = mapped_column(UTCDateTime)  # last confirmed by the exchange


class ExchangeMarket(Base):
    """A Betfair market linked to an Edgewise match, with what is needed to read it."""

    __tablename__ = "exchange_markets"
    __table_args__ = (sa.Index("ix_exchange_markets_event", "event_id"),)

    betfair_market_id: Mapped[str] = mapped_column(sa.String(32), primary_key=True)
    event_id: Mapped[int] = mapped_column(sa.ForeignKey("events.id", ondelete="CASCADE"))
    market_type: Mapped[str] = mapped_column(sa.String(32))  # Betfair code, e.g. MATCH_ODDS
    event_name: Mapped[str] = mapped_column(sa.String(200))  # "Home v Away" as Betfair has it
    start_time: Mapped[datetime] = mapped_column(UTCDateTime)
    runners: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    status: Mapped[str | None] = mapped_column(sa.String(16))
    total_matched: Mapped[Decimal | None] = mapped_column(sa.Numeric(16, 2))
    is_delayed: Mapped[bool] = mapped_column(default=False, server_default=sa.false())
    last_catalogue_at: Mapped[datetime] = mapped_column(UTCDateTime)
    last_book_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


# --- Signals, bets, settlement ------------------------------------------------------------


class Signal(Base):
    """Every bet the system generates, whatever happens to it."""

    __tablename__ = "signals"
    __table_args__ = (
        sa.CheckConstraint("offered_odds > 1 AND min_odds > 1", name="odds_above_one"),
        sa.CheckConstraint("suggested_stake > 0", name="stake_positive"),
        sa.Index(
            "uq_signals_one_awaiting_per_selection",
            "selection_id",
            unique=True,
            postgresql_where=sa.text("status = 'awaiting'"),
            sqlite_where=sa.text("status = 'awaiting'"),
        ),
        sa.Index("ix_signals_status_expires", "status", "expires_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(sa.ForeignKey("events.id"), index=True)
    selection_id: Mapped[int] = mapped_column(sa.ForeignKey("selections.id"))
    bookmaker_id: Mapped[int] = mapped_column(sa.ForeignKey("bookmakers.id"))
    offered_odds: Mapped[Decimal] = mapped_column(Odds)
    offered_at: Mapped[datetime] = mapped_column(UTCDateTime)
    fair_prob: Mapped[float] = mapped_column(Probability)
    fair_price_id: Mapped[int | None] = mapped_column(sa.ForeignKey("fair_prices.id"))
    model_prob: Mapped[float | None] = mapped_column(Probability)
    edge: Mapped[Decimal] = mapped_column(Ratio)
    kelly_stake: Mapped[Decimal] = mapped_column(Money)
    suggested_stake: Mapped[Decimal] = mapped_column(Money)
    capped_by: Mapped[StakeCap | None] = mapped_column(str_enum(StakeCap, "stake_cap"))
    min_odds: Mapped[Decimal] = mapped_column(Odds)
    bankroll_at_signal: Mapped[Decimal] = mapped_column(Money)
    reason: Mapped[str] = mapped_column(sa.Text)
    strategy_version: Mapped[str] = mapped_column(sa.String(64))
    status: Mapped[SignalStatus] = mapped_column(
        str_enum(SignalStatus, "signal_status"), default=SignalStatus.AWAITING
    )
    created_at: Mapped[datetime] = _created()
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    skip_reason: Mapped[str | None] = mapped_column(sa.String(64))
    expiry_reason: Mapped[ExpiryReason | None] = mapped_column(
        str_enum(ExpiryReason, "expiry_reason")
    )

    event: Mapped[Event] = relationship()
    selection: Mapped[MarketSelection] = relationship()
    bookmaker: Mapped[Bookmaker] = relationship()
    bet: Mapped[Bet | None] = relationship(back_populates="signal")


class Bet(Base):
    """A signal the owner placed, with what they actually got."""

    __tablename__ = "bets"
    __table_args__ = (
        sa.CheckConstraint("odds_taken > 1", name="odds_above_one"),
        sa.CheckConstraint("stake > 0", name="stake_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    signal_id: Mapped[int] = mapped_column(sa.ForeignKey("signals.id"), unique=True)
    bookmaker_id: Mapped[int] = mapped_column(sa.ForeignKey("bookmakers.id"))
    odds_taken: Mapped[Decimal] = mapped_column(Odds)
    stake: Mapped[Decimal] = mapped_column(Money)
    placed_at: Mapped[datetime] = mapped_column(UTCDateTime)
    closing_fair_prob: Mapped[float | None] = mapped_column(Probability)
    clv: Mapped[Decimal | None] = mapped_column(Ratio)
    warnings: Mapped[list[str]] = mapped_column(JSONType, default=list)
    notes: Mapped[str | None] = mapped_column(sa.Text)

    signal: Mapped[Signal] = relationship(back_populates="bet")


class Settlement(Base):
    """Grading of a signal. Placed bets move the bankroll; skipped ones are what-if only."""

    __tablename__ = "settlements"
    __table_args__ = (
        sa.CheckConstraint("is_what_if = (bet_id IS NULL)", name="what_if_has_no_bet"),
        sa.CheckConstraint(
            "NOT is_override OR override_reason IS NOT NULL", name="override_has_reason"
        ),
        sa.Index(
            "uq_settlements_current_per_signal",
            "signal_id",
            unique=True,
            postgresql_where=sa.text("superseded_by_id IS NULL"),
            sqlite_where=sa.text("superseded_by_id IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    signal_id: Mapped[int] = mapped_column(sa.ForeignKey("signals.id"))
    bet_id: Mapped[int | None] = mapped_column(sa.ForeignKey("bets.id"))
    outcome: Mapped[Outcome] = mapped_column(str_enum(Outcome, "outcome"))
    stake: Mapped[Decimal] = mapped_column(Money)
    odds: Mapped[Decimal] = mapped_column(Odds)
    profit: Mapped[Decimal] = mapped_column(Money)
    is_what_if: Mapped[bool]
    source: Mapped[str] = mapped_column(sa.String(32))  # results feed, or "manual"
    is_override: Mapped[bool] = mapped_column(default=False, server_default=sa.false())
    override_reason: Mapped[str | None] = mapped_column(sa.Text)
    graded_at: Mapped[datetime] = _created()
    superseded_by_id: Mapped[int | None] = mapped_column(sa.ForeignKey("settlements.id"))


class LedgerKind(StrEnum):
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    SETTLEMENT = "settlement"
    CORRECTION = "correction"


class BankrollEntry(Base):
    """Every change to the bankroll, with the reason. Append-only."""

    __tablename__ = "bankroll_ledger"
    __table_args__ = (
        sa.CheckConstraint(
            "(kind = 'settlement') = (settlement_id IS NOT NULL)", name="settlement_link"
        ),
        sa.CheckConstraint("kind <> 'deposit' OR amount > 0", name="deposit_positive"),
        sa.CheckConstraint("kind <> 'withdrawal' OR amount < 0", name="withdrawal_negative"),
    )

    id: Mapped[int] = mapped_column(BigID, primary_key=True)
    occurred_at: Mapped[datetime] = _created()
    kind: Mapped[LedgerKind] = mapped_column(str_enum(LedgerKind, "ledger_kind"))
    amount: Mapped[Decimal] = mapped_column(Money)
    balance_after: Mapped[Decimal] = mapped_column(Money)
    settlement_id: Mapped[int | None] = mapped_column(sa.ForeignKey("settlements.id"))
    note: Mapped[str | None] = mapped_column(sa.Text)


# --- Limits and pauses --------------------------------------------------------------------


class LimitSetting(Base):
    """Owner changes to safety limits, newest wins. Code defaults apply when absent."""

    __tablename__ = "limit_settings"
    __table_args__ = (sa.Index("ix_limit_settings_name_effective", "name", "effective_from"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(sa.String(64))
    value: Mapped[Decimal] = mapped_column(sa.Numeric(12, 6))
    effective_from: Mapped[datetime] = _created()
    changed_by: Mapped[str] = mapped_column(sa.String(32))
    reason: Mapped[str | None] = mapped_column(sa.Text)


class PauseReason(StrEnum):
    DRAWDOWN_STOP = "drawdown_stop"
    OWNER = "owner"


class AlertPause(Base):
    """Alerts are paused while any row has no resumed_at."""

    __tablename__ = "alert_pauses"
    __table_args__ = (
        sa.Index(
            "uq_alert_pauses_open_per_reason",
            "reason",
            unique=True,
            postgresql_where=sa.text("resumed_at IS NULL"),
            sqlite_where=sa.text("resumed_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    reason: Mapped[PauseReason] = mapped_column(str_enum(PauseReason, "pause_reason"))
    detail: Mapped[str | None] = mapped_column(sa.Text)
    paused_at: Mapped[datetime] = _created()
    resumed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


# --- Models -------------------------------------------------------------------------------


class ModelMode(StrEnum):
    LIVE = "live"
    SHADOW = "shadow"
    RETIRED = "retired"


class ModelVersion(Base):
    __tablename__ = "model_versions"
    __table_args__ = (
        sa.UniqueConstraint("name", "version"),
        sa.Index(
            "uq_model_versions_one_live",
            "mode",
            unique=True,
            postgresql_where=sa.text("mode = 'live'"),
            sqlite_where=sa.text("mode = 'live'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(sa.String(64))
    version: Mapped[str] = mapped_column(sa.String(32))
    mode: Mapped[ModelMode] = mapped_column(str_enum(ModelMode, "model_mode"))
    description: Mapped[str | None] = mapped_column(sa.Text)
    params: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = _created()
    promoted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    retired_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class ShadowSignal(Base):
    """What a shadow model would have bet. Never shown as an alert, never placed."""

    __tablename__ = "shadow_signals"

    id: Mapped[int] = mapped_column(BigID, primary_key=True)
    model_version_id: Mapped[int] = mapped_column(sa.ForeignKey("model_versions.id"), index=True)
    event_id: Mapped[int] = mapped_column(sa.ForeignKey("events.id"))
    selection_id: Mapped[int] = mapped_column(sa.ForeignKey("selections.id"))
    bookmaker_id: Mapped[int | None] = mapped_column(sa.ForeignKey("bookmakers.id"))
    offered_odds: Mapped[Decimal | None] = mapped_column(Odds)
    model_prob: Mapped[float] = mapped_column(Probability)
    fair_prob: Mapped[float | None] = mapped_column(Probability)
    edge: Mapped[Decimal | None] = mapped_column(Ratio)
    would_stake: Mapped[Decimal | None] = mapped_column(Money)
    created_at: Mapped[datetime] = _created()
    outcome: Mapped[Outcome | None] = mapped_column(str_enum(Outcome, "shadow_outcome"))
    profit: Mapped[Decimal | None] = mapped_column(Money)
    clv: Mapped[Decimal | None] = mapped_column(Ratio)
    graded_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


# --- Operations ---------------------------------------------------------------------------


class AuditEntry(Base):
    """Every owner action and every automated change. Append-only."""

    __tablename__ = "audit_log"
    __table_args__ = (sa.Index("ix_audit_log_entity", "entity_type", "entity_id"),)

    id: Mapped[int] = mapped_column(BigID, primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, server_default=sa.func.now(), index=True
    )
    actor: Mapped[str] = mapped_column(sa.String(32))  # owner / system / worker
    action: Mapped[str] = mapped_column(sa.String(64))
    entity_type: Mapped[str | None] = mapped_column(sa.String(32))
    entity_id: Mapped[str | None] = mapped_column(sa.String(64))
    details: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)


class FeedStatus(Base):
    __tablename__ = "feed_status"

    feed: Mapped[str] = mapped_column(sa.String(32), primary_key=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_success_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_error_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_error: Mapped[str | None] = mapped_column(sa.Text)
    consecutive_failures: Mapped[int] = mapped_column(default=0, server_default="0")
    paused: Mapped[bool] = mapped_column(default=False, server_default=sa.false())
    paused_since: Mapped[datetime | None] = mapped_column(UTCDateTime)
    owner_notified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    # e.g. remaining request allowance, matches that couldn't be matched
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONType, default=dict, server_default=sa.text("'{}'")
    )


class Notification(Base):
    """Messages for the owner. Shown in the app now; sent by push and Telegram once
    alerts arrive (Milestone 4)."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, server_default=sa.func.now(), index=True
    )
    kind: Mapped[str] = mapped_column(sa.String(32))  # e.g. feed_paused, feed_recovered
    title: Mapped[str] = mapped_column(sa.String(200))
    body: Mapped[str] = mapped_column(sa.Text)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"

    worker: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime)
    last_beat_at: Mapped[datetime] = mapped_column(UTCDateTime)
    version: Mapped[str] = mapped_column(sa.String(32))
    details: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)


# --- Login --------------------------------------------------------------------------------


class Owner(Base):
    """The single owner account. The lab copy strips these columns (credentials)."""

    __tablename__ = "owners"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(sa.String(254), unique=True)  # stored lower-case
    password_hash: Mapped[str] = mapped_column(sa.String(255))
    totp_secret_encrypted: Mapped[str] = mapped_column(sa.Text)
    totp_last_step: Mapped[int | None] = mapped_column(sa.BigInteger)  # blocks code reuse
    failed_login_count: Mapped[int] = mapped_column(default=0, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = _created()
    password_changed_at: Mapped[datetime] = _created()
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(sa.ForeignKey("owners.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(sa.String(64), unique=True)  # SHA-256, never raw
    created_at: Mapped[datetime] = _created()
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    user_agent: Mapped[str | None] = mapped_column(sa.String(255))
    ip_address: Mapped[str | None] = mapped_column(sa.String(64))

    owner: Mapped[Owner] = relationship()
