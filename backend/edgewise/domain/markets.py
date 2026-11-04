"""Markets and selections in scope for Phase 1 (docs/PROJECT_BRIEF.md)."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum


class MarketType(StrEnum):
    MATCH_RESULT = "match_result"  # 1X2
    TOTAL_GOALS = "total_goals"  # over/under a goal line, e.g. 2.5
    BOTH_TEAMS_TO_SCORE = "btts"
    ASIAN_HANDICAP = "asian_handicap"  # line = handicap given to the HOME team
    DRAW_NO_BET = "draw_no_bet"


class Selection(StrEnum):
    HOME = "home"
    DRAW = "draw"
    AWAY = "away"
    OVER = "over"
    UNDER = "under"
    YES = "yes"
    NO = "no"


SELECTIONS: dict[MarketType, tuple[Selection, ...]] = {
    MarketType.MATCH_RESULT: (Selection.HOME, Selection.DRAW, Selection.AWAY),
    MarketType.TOTAL_GOALS: (Selection.OVER, Selection.UNDER),
    MarketType.BOTH_TEAMS_TO_SCORE: (Selection.YES, Selection.NO),
    MarketType.ASIAN_HANDICAP: (Selection.HOME, Selection.AWAY),
    MarketType.DRAW_NO_BET: (Selection.HOME, Selection.AWAY),
}

LINE_MARKETS = frozenset({MarketType.TOTAL_GOALS, MarketType.ASIAN_HANDICAP})
QUARTER = Decimal("0.25")


def validate_line(market_type: MarketType, line: Decimal | None) -> Decimal | None:
    """Return the line if it is valid for the market type, otherwise raise ValueError."""
    if market_type not in LINE_MARKETS:
        if line is not None:
            raise ValueError(f"{market_type.value} markets have no line")
        return None
    if line is None:
        raise ValueError(f"{market_type.value} markets need a line")
    if (line / QUARTER) % 1 != 0:
        raise ValueError(f"lines must be multiples of 0.25, got {line}")
    if market_type is MarketType.TOTAL_GOALS and line <= 0:
        raise ValueError(f"goal lines must be positive, got {line}")
    return line


def validate_selection(market_type: MarketType, selection: Selection) -> None:
    if selection not in SELECTIONS[market_type]:
        allowed = ", ".join(s.value for s in SELECTIONS[market_type])
        raise ValueError(f"{selection.value} is not a {market_type.value} selection ({allowed})")
