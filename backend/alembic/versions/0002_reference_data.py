"""Reference data: the five leagues, the bookmakers in scope, the live strategy.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-04

Feed identifiers are checked against the live feeds in Milestone 2 (data ingestion).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

competitions = sa.table(
    "competitions",
    sa.column("code", sa.String),
    sa.column("name", sa.String),
    sa.column("country", sa.String),
    sa.column("betfair_competition_id", sa.String),
    sa.column("odds_api_sport_key", sa.String),
    sa.column("api_football_league_id", sa.Integer),
)

bookmakers = sa.table(
    "bookmakers",
    sa.column("key", sa.String),
    sa.column("name", sa.String),
    sa.column("account_status", sa.String),
    sa.column("notes", sa.Text),
)

model_versions = sa.table(
    "model_versions",
    sa.column("name", sa.String),
    sa.column("version", sa.String),
    sa.column("mode", sa.String),
    sa.column("description", sa.Text),
    sa.column("params", postgresql.JSONB),
    sa.column("promoted_at", sa.DateTime(timezone=True)),
)

COMPETITIONS = [
    ("EPL", "Premier League", "England", "10932509", "soccer_epl", 39),
    ("LALIGA", "La Liga", "Spain", "117", "soccer_spain_la_liga", 140),
    ("SERIEA", "Serie A", "Italy", "81", "soccer_italy_serie_a", 135),
    ("BUNDESLIGA", "Bundesliga", "Germany", "59", "soccer_germany_bundesliga", 78),
    ("LIGUE1", "Ligue 1", "France", "55", "soccer_france_ligue_one", 61),
]

BOOKMAKERS = [
    ("sportsbet", "Sportsbet", None),
    ("tab", "TAB", None),
    ("ladbrokes_au", "Ladbrokes", "Same owner as Neds (Entain): limits may be shared."),
    ("neds", "Neds", "Same owner as Ladbrokes (Entain): limits may be shared."),
    (
        "bet365_au",
        "bet365",
        "The Odds API lists bet365 AU for AFL/NRL only (Nov 2026): no soccer prices "
        "expected from that feed.",
    ),
]


def upgrade() -> None:
    op.bulk_insert(
        competitions,
        [
            {
                "code": code,
                "name": name,
                "country": country,
                "betfair_competition_id": betfair,
                "odds_api_sport_key": odds_api,
                "api_football_league_id": api_football,
            }
            for code, name, country, betfair, odds_api, api_football in COMPETITIONS
        ],
    )
    op.bulk_insert(
        bookmakers,
        [
            {"key": key, "name": name, "account_status": "active", "notes": notes}
            for key, name, notes in BOOKMAKERS
        ],
    )
    op.execute(
        sa.insert(model_versions).values(
            name="reference-price",
            version="v1",
            mode="live",
            description=(
                "Betfair Exchange fair price (back/lay midpoint, multiplicative margin "
                "removal) compared with Australian bookmaker prices."
            ),
            params={"margin_method": "multiplicative", "max_spread": "0.05"},
            promoted_at=sa.func.now(),
        )
    )


def downgrade() -> None:
    op.execute("DELETE FROM model_versions WHERE name = 'reference-price' AND version = 'v1'")
    keys = ", ".join(f"'{key}'" for key, _, _ in BOOKMAKERS)
    op.execute(f"DELETE FROM bookmakers WHERE key IN ({keys})")  # noqa: S608
    codes = ", ".join(f"'{code}'" for code, *_ in COMPETITIONS)
    op.execute(f"DELETE FROM competitions WHERE code IN ({codes})")  # noqa: S608
