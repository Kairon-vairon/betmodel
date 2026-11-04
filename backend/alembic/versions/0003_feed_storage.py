"""Feed storage (Milestone 2): latest prices, latest fair prices, Betfair market links,
notifications, feed details.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
    )
    op.create_index(
        op.f("ix_notifications_created_at"), "notifications", ["created_at"], unique=False
    )
    op.create_table(
        "exchange_markets",
        sa.Column("betfair_market_id", sa.String(length=32), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("market_type", sa.String(length=32), nullable=False),
        sa.Column("event_name", sa.String(length=200), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("runners", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=True),
        sa.Column("total_matched", sa.Numeric(precision=16, scale=2), nullable=True),
        sa.Column("is_delayed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("last_catalogue_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_book_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["events.id"],
            name=op.f("fk_exchange_markets_event_id_events"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("betfair_market_id", name=op.f("pk_exchange_markets")),
    )
    op.create_index("ix_exchange_markets_event", "exchange_markets", ["event_id"], unique=False)
    op.create_table(
        "latest_prices",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("selection_id", sa.Integer(), nullable=False),
        sa.Column(
            "source",
            sa.Enum(
                "odds_feed",
                "betfair",
                name="latest_price_source",
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
                name="latest_price_side",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("odds", sa.Numeric(precision=8, scale=3), nullable=False),
        sa.Column("size", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("price_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(source = 'betfair') = (bookmaker_id IS NULL)",
            name=op.f("ck_latest_prices_bookmaker_matches_source"),
        ),
        sa.CheckConstraint("odds > 1", name=op.f("ck_latest_prices_odds_above_one")),
        sa.ForeignKeyConstraint(
            ["bookmaker_id"],
            ["bookmakers.id"],
            name=op.f("fk_latest_prices_bookmaker_id_bookmakers"),
        ),
        sa.ForeignKeyConstraint(
            ["selection_id"],
            ["selections.id"],
            name=op.f("fk_latest_prices_selection_id_selections"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_latest_prices")),
        sa.UniqueConstraint(
            "selection_id",
            "source",
            "bookmaker_id",
            "side",
            name=op.f("uq_latest_prices_selection_id"),
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_table(
        "latest_fair_prices",
        sa.Column("selection_id", sa.Integer(), nullable=False),
        sa.Column("fair_prob", sa.Double(), nullable=False),
        sa.Column("method", sa.String(length=32), nullable=False),
        sa.Column("mid_overround", sa.Double(), nullable=False),
        sa.Column("fair_price_id", sa.BigInteger(), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "fair_prob > 0 AND fair_prob < 1", name=op.f("ck_latest_fair_prices_probability_range")
        ),
        sa.ForeignKeyConstraint(
            ["fair_price_id"],
            ["fair_prices.id"],
            name=op.f("fk_latest_fair_prices_fair_price_id_fair_prices"),
        ),
        sa.ForeignKeyConstraint(
            ["selection_id"],
            ["selections.id"],
            name=op.f("fk_latest_fair_prices_selection_id_selections"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("selection_id", name=op.f("pk_latest_fair_prices")),
    )
    op.create_index(
        "ix_events_competition_kickoff", "events", ["competition_id", "kickoff_at"], unique=False
    )
    op.add_column(
        "feed_status",
        sa.Column("details", postgresql.JSONB(), server_default=sa.text("'{}'"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("feed_status", "details")
    op.drop_index("ix_events_competition_kickoff", table_name="events")
    op.drop_table("latest_fair_prices")
    op.drop_table("latest_prices")
    op.drop_index("ix_exchange_markets_event", table_name="exchange_markets")
    op.drop_table("exchange_markets")
    op.drop_index(op.f("ix_notifications_created_at"), table_name="notifications")
    op.drop_table("notifications")
