"""Initial schema: fixtures, prices, signals, bets, settlement, ledger, limits, login.

Revision ID: 0001
Revises:
Create Date: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPEND_ONLY_TABLES = ("price_snapshots", "bankroll_ledger", "audit_log")


def upgrade() -> None:
    op.create_table(
        "alert_pauses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "reason",
            sa.Enum(
                "drawdown_stop",
                "owner",
                name="pause_reason",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column(
            "paused_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("resumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alert_pauses")),
    )
    op.create_index(
        "uq_alert_pauses_open_per_reason",
        "alert_pauses",
        ["reason"],
        unique=True,
        postgresql_where=sa.text("resumed_at IS NULL"),
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("actor", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=True),
        sa.Column("entity_id", sa.String(length=64), nullable=True),
        sa.Column("details", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
    )
    op.create_index("ix_audit_log_entity", "audit_log", ["entity_type", "entity_id"], unique=False)
    op.create_index(op.f("ix_audit_log_occurred_at"), "audit_log", ["occurred_at"], unique=False)
    op.create_table(
        "bookmakers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column(
            "account_status",
            sa.Enum(
                "active",
                "limited",
                "closed",
                "no_account",
                name="account_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("stake_limit", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bookmakers")),
        sa.UniqueConstraint("key", name=op.f("uq_bookmakers_key")),
    )
    op.create_table(
        "competitions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("country", sa.String(length=32), nullable=False),
        sa.Column("betfair_competition_id", sa.String(length=32), nullable=True),
        sa.Column("odds_api_sport_key", sa.String(length=64), nullable=True),
        sa.Column("api_football_league_id", sa.Integer(), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_competitions")),
        sa.UniqueConstraint("code", name=op.f("uq_competitions_code")),
    )
    op.create_table(
        "feed_status",
        sa.Column("feed", sa.String(length=32), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), server_default="0", nullable=False),
        sa.Column("paused", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("paused_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("owner_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("feed", name=op.f("pk_feed_status")),
    )
    op.create_table(
        "limit_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column(
            "effective_from",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("changed_by", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_limit_settings")),
    )
    op.create_index(
        "ix_limit_settings_name_effective",
        "limit_settings",
        ["name", "effective_from"],
        unique=False,
    )
    op.create_table(
        "model_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column(
            "mode",
            sa.Enum(
                "live",
                "shadow",
                "retired",
                name="model_mode",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("params", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_model_versions")),
        sa.UniqueConstraint("name", "version", name=op.f("uq_model_versions_name")),
    )
    op.create_index(
        "uq_model_versions_one_live",
        "model_versions",
        ["mode"],
        unique=True,
        postgresql_where=sa.text("mode = 'live'"),
    )
    op.create_table(
        "owners",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=254), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("totp_secret_encrypted", sa.Text(), nullable=False),
        sa.Column("totp_last_step", sa.BigInteger(), nullable=True),
        sa.Column("failed_login_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "password_changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_owners")),
        sa.UniqueConstraint("username", name=op.f("uq_owners_username")),
    )
    op.create_table(
        "teams",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("country", sa.String(length=32), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_teams")),
        sa.UniqueConstraint("name", name=op.f("uq_teams_name")),
    )
    op.create_table(
        "worker_heartbeats",
        sa.Column("worker", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_beat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("details", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("worker", name=op.f("pk_worker_heartbeats")),
    )
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name=op.f("fk_auth_sessions_owner_id_owners"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_auth_sessions_token_hash")),
    )
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("competition_id", sa.Integer(), nullable=False),
        sa.Column("home_team_id", sa.Integer(), nullable=False),
        sa.Column("away_team_id", sa.Integer(), nullable=False),
        sa.Column("kickoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "scheduled",
                "live",
                "finished",
                "postponed",
                "cancelled",
                "abandoned",
                name="event_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("home_goals", sa.Integer(), nullable=True),
        sa.Column("away_goals", sa.Integer(), nullable=True),
        sa.Column("result_source", sa.String(length=32), nullable=True),
        sa.Column("result_recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("betfair_event_id", sa.String(length=32), nullable=True),
        sa.Column("odds_api_event_id", sa.String(length=64), nullable=True),
        sa.Column("api_football_fixture_id", sa.Integer(), nullable=True),
        sa.Column(
            "allow_extra_bets", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(home_goals IS NULL) = (away_goals IS NULL)", name=op.f("ck_events_score_complete")
        ),
        sa.CheckConstraint(
            "home_goals >= 0 AND away_goals >= 0", name=op.f("ck_events_score_not_negative")
        ),
        sa.CheckConstraint("home_team_id <> away_team_id", name=op.f("ck_events_different_teams")),
        sa.ForeignKeyConstraint(
            ["away_team_id"], ["teams.id"], name=op.f("fk_events_away_team_id_teams")
        ),
        sa.ForeignKeyConstraint(
            ["competition_id"],
            ["competitions.id"],
            name=op.f("fk_events_competition_id_competitions"),
        ),
        sa.ForeignKeyConstraint(
            ["home_team_id"], ["teams.id"], name=op.f("fk_events_home_team_id_teams")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_events")),
        sa.UniqueConstraint(
            "api_football_fixture_id", name=op.f("uq_events_api_football_fixture_id")
        ),
        sa.UniqueConstraint("betfair_event_id", name=op.f("uq_events_betfair_event_id")),
        sa.UniqueConstraint("odds_api_event_id", name=op.f("uq_events_odds_api_event_id")),
    )
    op.create_index(op.f("ix_events_kickoff_at"), "events", ["kickoff_at"], unique=False)
    op.create_index("ix_events_status_kickoff", "events", ["status", "kickoff_at"], unique=False)
    op.create_table(
        "team_aliases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("alias", sa.String(length=120), nullable=False),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["teams.id"],
            name=op.f("fk_team_aliases_team_id_teams"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_team_aliases")),
        sa.UniqueConstraint("source", "alias", name=op.f("uq_team_aliases_source")),
    )
    op.create_table(
        "markets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column(
            "type",
            sa.Enum(
                "match_result",
                "total_goals",
                "btts",
                "asian_handicap",
                "draw_no_bet",
                name="market_type",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("line", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("betfair_market_id", sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(
            ["event_id"], ["events.id"], name=op.f("fk_markets_event_id_events"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_markets")),
        sa.UniqueConstraint("betfair_market_id", name=op.f("uq_markets_betfair_market_id")),
        sa.UniqueConstraint(
            "event_id",
            "type",
            "line",
            name=op.f("uq_markets_event_id"),
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_table(
        "selections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("market_id", sa.Integer(), nullable=False),
        sa.Column(
            "code",
            sa.Enum(
                "home",
                "draw",
                "away",
                "over",
                "under",
                "yes",
                "no",
                name="selection_code",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("label", sa.String(length=80), nullable=True),
        sa.Column("betfair_selection_id", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(
            ["market_id"],
            ["markets.id"],
            name=op.f("fk_selections_market_id_markets"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_selections")),
        sa.UniqueConstraint("market_id", "code", name=op.f("uq_selections_market_id")),
    )
    op.create_table(
        "fair_prices",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("selection_id", sa.Integer(), nullable=False),
        sa.Column("fair_prob", sa.Double(), nullable=False),
        sa.Column("method", sa.String(length=32), nullable=False),
        sa.Column("mid_overround", sa.Double(), nullable=False),
        sa.Column("inputs", postgresql.JSONB(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "fair_prob > 0 AND fair_prob < 1", name=op.f("ck_fair_prices_probability_range")
        ),
        sa.ForeignKeyConstraint(
            ["selection_id"], ["selections.id"], name=op.f("fk_fair_prices_selection_id_selections")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fair_prices")),
    )
    op.create_index("ix_fair_prices_lookup", "fair_prices", ["selection_id", "as_of"], unique=False)
    op.create_table(
        "price_snapshots",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("selection_id", sa.Integer(), nullable=False),
        sa.Column(
            "source",
            sa.Enum(
                "odds_feed",
                "betfair",
                name="price_source",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("bookmaker_id", sa.Integer(), nullable=True),
        sa.Column(
            "side",
            sa.Enum(
                "back",
                "lay",
                name="price_side",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("odds", sa.Numeric(precision=8, scale=3), nullable=False),
        sa.Column("size", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(source = 'betfair') = (bookmaker_id IS NULL)",
            name=op.f("ck_price_snapshots_bookmaker_matches_source"),
        ),
        sa.CheckConstraint("odds > 1", name=op.f("ck_price_snapshots_odds_above_one")),
        sa.ForeignKeyConstraint(
            ["bookmaker_id"],
            ["bookmakers.id"],
            name=op.f("fk_price_snapshots_bookmaker_id_bookmakers"),
        ),
        sa.ForeignKeyConstraint(
            ["selection_id"],
            ["selections.id"],
            name=op.f("fk_price_snapshots_selection_id_selections"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_price_snapshots")),
    )
    op.create_index(
        "ix_price_snapshots_captured_at", "price_snapshots", ["captured_at"], unique=False
    )
    op.create_index(
        "ix_price_snapshots_lookup",
        "price_snapshots",
        ["selection_id", "source", "bookmaker_id", "captured_at"],
        unique=False,
    )
    op.create_table(
        "shadow_signals",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("model_version_id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("selection_id", sa.Integer(), nullable=False),
        sa.Column("bookmaker_id", sa.Integer(), nullable=True),
        sa.Column("offered_odds", sa.Numeric(precision=8, scale=3), nullable=True),
        sa.Column("model_prob", sa.Double(), nullable=False),
        sa.Column("fair_prob", sa.Double(), nullable=True),
        sa.Column("edge", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("would_stake", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "outcome",
            sa.Enum(
                "won",
                "half_won",
                "void",
                "half_lost",
                "lost",
                name="shadow_outcome",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column("profit", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("clv", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("graded_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["bookmaker_id"],
            ["bookmakers.id"],
            name=op.f("fk_shadow_signals_bookmaker_id_bookmakers"),
        ),
        sa.ForeignKeyConstraint(
            ["event_id"], ["events.id"], name=op.f("fk_shadow_signals_event_id_events")
        ),
        sa.ForeignKeyConstraint(
            ["model_version_id"],
            ["model_versions.id"],
            name=op.f("fk_shadow_signals_model_version_id_model_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["selection_id"],
            ["selections.id"],
            name=op.f("fk_shadow_signals_selection_id_selections"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shadow_signals")),
    )
    op.create_index(
        op.f("ix_shadow_signals_model_version_id"),
        "shadow_signals",
        ["model_version_id"],
        unique=False,
    )
    op.create_table(
        "signals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("selection_id", sa.Integer(), nullable=False),
        sa.Column("bookmaker_id", sa.Integer(), nullable=False),
        sa.Column("offered_odds", sa.Numeric(precision=8, scale=3), nullable=False),
        sa.Column("offered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fair_prob", sa.Double(), nullable=False),
        sa.Column("fair_price_id", sa.BigInteger(), nullable=True),
        sa.Column("model_prob", sa.Double(), nullable=True),
        sa.Column("edge", sa.Numeric(precision=9, scale=6), nullable=False),
        sa.Column("kelly_stake", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("suggested_stake", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column(
            "capped_by",
            sa.Enum(
                "max_stake",
                "bookmaker_limit",
                "daily_exposure",
                name="stake_cap",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column("min_odds", sa.Numeric(precision=8, scale=3), nullable=False),
        sa.Column("bankroll_at_signal", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("strategy_version", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "awaiting",
                "placed",
                "skipped",
                "expired",
                name="signal_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("skip_reason", sa.String(length=64), nullable=True),
        sa.Column(
            "expiry_reason",
            sa.Enum(
                "approval_window",
                "kicked_off",
                "odds_below_minimum",
                "value_gone",
                "alerts_paused",
                name="expiry_reason",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=True,
        ),
        sa.CheckConstraint(
            "offered_odds > 1 AND min_odds > 1", name=op.f("ck_signals_odds_above_one")
        ),
        sa.CheckConstraint("suggested_stake > 0", name=op.f("ck_signals_stake_positive")),
        sa.ForeignKeyConstraint(
            ["bookmaker_id"], ["bookmakers.id"], name=op.f("fk_signals_bookmaker_id_bookmakers")
        ),
        sa.ForeignKeyConstraint(
            ["event_id"], ["events.id"], name=op.f("fk_signals_event_id_events")
        ),
        sa.ForeignKeyConstraint(
            ["fair_price_id"], ["fair_prices.id"], name=op.f("fk_signals_fair_price_id_fair_prices")
        ),
        sa.ForeignKeyConstraint(
            ["selection_id"], ["selections.id"], name=op.f("fk_signals_selection_id_selections")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_signals")),
    )
    op.create_index(op.f("ix_signals_event_id"), "signals", ["event_id"], unique=False)
    op.create_index("ix_signals_status_expires", "signals", ["status", "expires_at"], unique=False)
    op.create_index(
        "uq_signals_one_awaiting_per_selection",
        "signals",
        ["selection_id"],
        unique=True,
        postgresql_where=sa.text("status = 'awaiting'"),
    )
    op.create_table(
        "bets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("signal_id", sa.Integer(), nullable=False),
        sa.Column("bookmaker_id", sa.Integer(), nullable=False),
        sa.Column("odds_taken", sa.Numeric(precision=8, scale=3), nullable=False),
        sa.Column("stake", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("placed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closing_fair_prob", sa.Double(), nullable=True),
        sa.Column("clv", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("warnings", postgresql.JSONB(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.CheckConstraint("odds_taken > 1", name=op.f("ck_bets_odds_above_one")),
        sa.CheckConstraint("stake > 0", name=op.f("ck_bets_stake_positive")),
        sa.ForeignKeyConstraint(
            ["bookmaker_id"], ["bookmakers.id"], name=op.f("fk_bets_bookmaker_id_bookmakers")
        ),
        sa.ForeignKeyConstraint(
            ["signal_id"], ["signals.id"], name=op.f("fk_bets_signal_id_signals")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bets")),
        sa.UniqueConstraint("signal_id", name=op.f("uq_bets_signal_id")),
    )
    op.create_table(
        "settlements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("signal_id", sa.Integer(), nullable=False),
        sa.Column("bet_id", sa.Integer(), nullable=True),
        sa.Column(
            "outcome",
            sa.Enum(
                "won",
                "half_won",
                "void",
                "half_lost",
                "lost",
                name="outcome",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("stake", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("odds", sa.Numeric(precision=8, scale=3), nullable=False),
        sa.Column("profit", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("is_what_if", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("is_override", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("override_reason", sa.Text(), nullable=True),
        sa.Column(
            "graded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("superseded_by_id", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "NOT is_override OR override_reason IS NOT NULL",
            name=op.f("ck_settlements_override_has_reason"),
        ),
        sa.CheckConstraint(
            "is_what_if = (bet_id IS NULL)", name=op.f("ck_settlements_what_if_has_no_bet")
        ),
        sa.ForeignKeyConstraint(["bet_id"], ["bets.id"], name=op.f("fk_settlements_bet_id_bets")),
        sa.ForeignKeyConstraint(
            ["signal_id"], ["signals.id"], name=op.f("fk_settlements_signal_id_signals")
        ),
        sa.ForeignKeyConstraint(
            ["superseded_by_id"],
            ["settlements.id"],
            name=op.f("fk_settlements_superseded_by_id_settlements"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_settlements")),
    )
    op.create_index(
        "uq_settlements_current_per_signal",
        "settlements",
        ["signal_id"],
        unique=True,
        postgresql_where=sa.text("superseded_by_id IS NULL"),
    )
    op.create_table(
        "bankroll_ledger",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "kind",
            sa.Enum(
                "deposit",
                "withdrawal",
                "settlement",
                "correction",
                name="ledger_kind",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("balance_after", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("settlement_id", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "(kind = 'settlement') = (settlement_id IS NOT NULL)",
            name=op.f("ck_bankroll_ledger_settlement_link"),
        ),
        sa.CheckConstraint(
            "kind <> 'deposit' OR amount > 0", name=op.f("ck_bankroll_ledger_deposit_positive")
        ),
        sa.CheckConstraint(
            "kind <> 'withdrawal' OR amount < 0",
            name=op.f("ck_bankroll_ledger_withdrawal_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["settlement_id"],
            ["settlements.id"],
            name=op.f("fk_bankroll_ledger_settlement_id_settlements"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bankroll_ledger")),
    )
    # Append-only tables: rows can be added but never changed, deleted or truncated.
    op.execute(
        """
        CREATE FUNCTION edgewise_forbid_change() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only: rows cannot be changed or deleted', TG_TABLE_NAME
                USING ERRCODE = 'restrict_violation';
        END;
        $$
        """
    )
    for table in APPEND_ONLY_TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION edgewise_forbid_change()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION edgewise_forbid_change()"
        )


def downgrade() -> None:
    for table in APPEND_ONLY_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_truncate ON {table}")
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}")
    op.execute("DROP FUNCTION IF EXISTS edgewise_forbid_change()")
    op.drop_table("bankroll_ledger")
    op.drop_index(
        "uq_settlements_current_per_signal",
        table_name="settlements",
        postgresql_where=sa.text("superseded_by_id IS NULL"),
    )
    op.drop_table("settlements")
    op.drop_table("bets")
    op.drop_index(
        "uq_signals_one_awaiting_per_selection",
        table_name="signals",
        postgresql_where=sa.text("status = 'awaiting'"),
    )
    op.drop_index("ix_signals_status_expires", table_name="signals")
    op.drop_index(op.f("ix_signals_event_id"), table_name="signals")
    op.drop_table("signals")
    op.drop_index(op.f("ix_shadow_signals_model_version_id"), table_name="shadow_signals")
    op.drop_table("shadow_signals")
    op.drop_index("ix_price_snapshots_lookup", table_name="price_snapshots")
    op.drop_index("ix_price_snapshots_captured_at", table_name="price_snapshots")
    op.drop_table("price_snapshots")
    op.drop_index("ix_fair_prices_lookup", table_name="fair_prices")
    op.drop_table("fair_prices")
    op.drop_table("selections")
    op.drop_table("markets")
    op.drop_table("team_aliases")
    op.drop_index("ix_events_status_kickoff", table_name="events")
    op.drop_index(op.f("ix_events_kickoff_at"), table_name="events")
    op.drop_table("events")
    op.drop_table("auth_sessions")
    op.drop_table("worker_heartbeats")
    op.drop_table("teams")
    op.drop_table("owners")
    op.drop_index(
        "uq_model_versions_one_live",
        table_name="model_versions",
        postgresql_where=sa.text("mode = 'live'"),
    )
    op.drop_table("model_versions")
    op.drop_index("ix_limit_settings_name_effective", table_name="limit_settings")
    op.drop_table("limit_settings")
    op.drop_table("feed_status")
    op.drop_table("competitions")
    op.drop_table("bookmakers")
    op.drop_index(op.f("ix_audit_log_occurred_at"), table_name="audit_log")
    op.drop_index("ix_audit_log_entity", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_index(
        "uq_alert_pauses_open_per_reason",
        table_name="alert_pauses",
        postgresql_where=sa.text("resumed_at IS NULL"),
    )
    op.drop_table("alert_pauses")
