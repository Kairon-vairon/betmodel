"""Grading bets from final scores, and the money that follows.

HIGH-RISK CODE (docs/RELEASE_PROCESS.md: settlement money calculations). Changes must be
listed on their own under "High-risk changes" in the release notes.

Rules:
- Markets are graded on the score at the end of normal time (90 minutes plus stoppage).
- Quarter lines (e.g. -0.25, 2.75) split the stake in half across the two neighbouring
  lines: -0.25 is half on 0 and half on -0.5. That gives half-won / half-lost results.
- Whole lines (e.g. 0, -1, 3) refund the stake on a tie with the line (void).
- Draw no bet refunds on a draw.
- Matches that are postponed, cancelled or abandoned are void. Bookmaker rules on
  abandoned matches vary, so the owner can correct any result by hand.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from edgewise.domain.markets import (
    MarketType,
    Selection,
    validate_line,
    validate_selection,
)

CENT = Decimal("0.01")
HALF = Decimal("0.5")
QUARTER = Decimal("0.25")


class Outcome(StrEnum):
    WON = "won"
    HALF_WON = "half_won"
    VOID = "void"
    HALF_LOST = "half_lost"
    LOST = "lost"


class EventOutcome(StrEnum):
    FINISHED = "finished"
    POSTPONED = "postponed"
    CANCELLED = "cancelled"
    ABANDONED = "abandoned"


def grade(
    market_type: MarketType,
    selection: Selection,
    line: Decimal | None,
    home_goals: int,
    away_goals: int,
) -> Outcome:
    """Result of one selection given the full-time score."""
    validate_selection(market_type, selection)
    line = validate_line(market_type, line)
    if home_goals < 0 or away_goals < 0:
        raise ValueError("goals cannot be negative")

    if market_type is MarketType.MATCH_RESULT:
        if home_goals > away_goals:
            winner = Selection.HOME
        elif home_goals < away_goals:
            winner = Selection.AWAY
        else:
            winner = Selection.DRAW
        return Outcome.WON if selection is winner else Outcome.LOST

    if market_type is MarketType.BOTH_TEAMS_TO_SCORE:
        both = home_goals > 0 and away_goals > 0
        return Outcome.WON if both == (selection is Selection.YES) else Outcome.LOST

    if market_type is MarketType.DRAW_NO_BET:
        return _grade_lines(_margin_for(selection, home_goals - away_goals), Decimal(0))

    if market_type is MarketType.ASIAN_HANDICAP:
        assert line is not None
        # The line is the home team's handicap; the away team gets the opposite.
        diff = home_goals - away_goals
        if selection is Selection.HOME:
            return _grade_lines(Decimal(diff), line)
        return _grade_lines(Decimal(-diff), -line)

    # Total goals
    assert line is not None
    total = Decimal(home_goals + away_goals)
    if selection is Selection.OVER:
        return _grade_lines(total, -line)
    return _grade_lines(-total, line)


def _margin_for(selection: Selection, diff: int) -> Decimal:
    return Decimal(diff if selection is Selection.HOME else -diff)


def _split(line: Decimal) -> tuple[Decimal, ...]:
    if (line / QUARTER) % 1 != 0:
        raise ValueError(f"lines must be multiples of 0.25, got {line}")
    if (line / HALF) % 1 == 0:
        return (line,)
    return (line - QUARTER, line + QUARTER)


def _grade_lines(value: Decimal, line: Decimal) -> Outcome:
    """Grade "value + line > 0" for a whole, half or quarter line."""
    parts = [value + part for part in _split(line)]
    results = ["win" if p > 0 else "push" if p == 0 else "loss" for p in parts]
    if len(results) == 1:
        return {"win": Outcome.WON, "push": Outcome.VOID, "loss": Outcome.LOST}[results[0]]
    combined = set(results)
    if combined == {"win"}:
        return Outcome.WON
    if combined == {"loss"}:
        return Outcome.LOST
    if combined == {"win", "push"}:
        return Outcome.HALF_WON
    if combined == {"loss", "push"}:
        return Outcome.HALF_LOST
    raise AssertionError(f"impossible quarter-line result: {results}")  # pragma: no cover


def grade_event(
    event_outcome: EventOutcome,
    market_type: MarketType,
    selection: Selection,
    line: Decimal | None,
    home_goals: int | None,
    away_goals: int | None,
) -> Outcome:
    if event_outcome is not EventOutcome.FINISHED:
        return Outcome.VOID
    if home_goals is None or away_goals is None:
        raise ValueError("a finished match needs a score")
    return grade(market_type, selection, line, home_goals, away_goals)


def profit(outcome: Outcome, stake: Decimal, odds: Decimal) -> Decimal:
    """Profit (negative for a loss) in dollars and cents."""
    if stake < 0:
        raise ValueError("stake cannot be negative")
    if odds <= 1:
        raise ValueError("decimal odds must be above 1")
    win = stake * (odds - 1)
    amounts = {
        Outcome.WON: win,
        Outcome.HALF_WON: win / 2,
        Outcome.VOID: Decimal(0),
        Outcome.HALF_LOST: -stake / 2,
        Outcome.LOST: -stake,
    }
    return amounts[outcome].quantize(CENT, ROUND_HALF_UP)


def closing_line_value(odds_taken: Decimal, closing_fair_prob: float) -> Decimal:
    """CLV: how much better the price taken was than the fair price at kick-off.

    odds_taken x closing fair probability - 1. Positive means we beat the closing line.
    """
    if odds_taken <= 1:
        raise ValueError("decimal odds must be above 1")
    if not 0.0 < closing_fair_prob < 1.0:
        raise ValueError("probability must be between 0 and 1")
    value = odds_taken * Decimal(repr(closing_fair_prob)) - 1
    return value.quantize(Decimal("0.000001"), ROUND_HALF_UP)
