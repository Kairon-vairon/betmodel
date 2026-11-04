"""Golden grading set. HIGH-RISK: settlement money calculations."""

from decimal import Decimal as D

import pytest

from edgewise.domain.markets import MarketType as M
from edgewise.domain.markets import Selection as S
from edgewise.domain.settlement import (
    EventOutcome,
    Outcome,
    closing_line_value,
    grade,
    grade_event,
    profit,
)

W, HW, V, HL, L = Outcome.WON, Outcome.HALF_WON, Outcome.VOID, Outcome.HALF_LOST, Outcome.LOST

GOLDEN: list[tuple[M, S, str | None, str, Outcome]] = [
    # Match result
    (M.MATCH_RESULT, S.HOME, None, "2-1", W),
    (M.MATCH_RESULT, S.DRAW, None, "2-1", L),
    (M.MATCH_RESULT, S.AWAY, None, "0-1", W),
    (M.MATCH_RESULT, S.DRAW, None, "1-1", W),
    (M.MATCH_RESULT, S.HOME, None, "0-0", L),
    # Total goals: half lines
    (M.TOTAL_GOALS, S.OVER, "2.5", "2-1", W),
    (M.TOTAL_GOALS, S.OVER, "2.5", "1-1", L),
    (M.TOTAL_GOALS, S.UNDER, "2.5", "1-1", W),
    (M.TOTAL_GOALS, S.UNDER, "2.5", "3-0", L),
    # Total goals: whole lines push
    (M.TOTAL_GOALS, S.OVER, "2", "1-1", V),
    (M.TOTAL_GOALS, S.OVER, "2", "2-1", W),
    (M.TOTAL_GOALS, S.OVER, "2", "1-0", L),
    (M.TOTAL_GOALS, S.UNDER, "3", "2-1", V),
    # Total goals: quarter lines split
    (M.TOTAL_GOALS, S.OVER, "2.25", "1-1", HL),
    (M.TOTAL_GOALS, S.OVER, "2.25", "2-1", W),
    (M.TOTAL_GOALS, S.OVER, "2.25", "1-0", L),
    (M.TOTAL_GOALS, S.OVER, "2.75", "2-1", HW),
    (M.TOTAL_GOALS, S.OVER, "2.75", "1-1", L),
    (M.TOTAL_GOALS, S.OVER, "2.75", "2-2", W),
    (M.TOTAL_GOALS, S.UNDER, "2.25", "1-1", HW),
    (M.TOTAL_GOALS, S.UNDER, "2.25", "2-1", L),
    (M.TOTAL_GOALS, S.UNDER, "2.75", "2-1", HL),
    (M.TOTAL_GOALS, S.UNDER, "2.75", "1-1", W),
    # Both teams to score
    (M.BOTH_TEAMS_TO_SCORE, S.YES, None, "1-1", W),
    (M.BOTH_TEAMS_TO_SCORE, S.YES, None, "1-0", L),
    (M.BOTH_TEAMS_TO_SCORE, S.NO, None, "0-0", W),
    (M.BOTH_TEAMS_TO_SCORE, S.NO, None, "3-0", W),
    (M.BOTH_TEAMS_TO_SCORE, S.NO, None, "2-1", L),
    # Asian handicap (line is the home team's handicap)
    (M.ASIAN_HANDICAP, S.HOME, "-0.5", "1-0", W),
    (M.ASIAN_HANDICAP, S.HOME, "-0.5", "1-1", L),
    (M.ASIAN_HANDICAP, S.AWAY, "-0.5", "1-1", W),
    (M.ASIAN_HANDICAP, S.AWAY, "-0.5", "1-0", L),
    (M.ASIAN_HANDICAP, S.HOME, "-0.25", "1-1", HL),
    (M.ASIAN_HANDICAP, S.HOME, "-0.25", "2-1", W),
    (M.ASIAN_HANDICAP, S.HOME, "-0.25", "0-1", L),
    (M.ASIAN_HANDICAP, S.AWAY, "-0.25", "1-1", HW),
    (M.ASIAN_HANDICAP, S.AWAY, "-0.25", "2-1", L),
    (M.ASIAN_HANDICAP, S.HOME, "-0.75", "1-0", HW),
    (M.ASIAN_HANDICAP, S.HOME, "-0.75", "2-0", W),
    (M.ASIAN_HANDICAP, S.HOME, "-0.75", "1-1", L),
    (M.ASIAN_HANDICAP, S.AWAY, "-0.75", "1-0", HL),
    (M.ASIAN_HANDICAP, S.AWAY, "-0.75", "0-0", W),
    (M.ASIAN_HANDICAP, S.HOME, "-1", "1-0", V),
    (M.ASIAN_HANDICAP, S.HOME, "-1", "2-0", W),
    (M.ASIAN_HANDICAP, S.HOME, "-1", "1-1", L),
    (M.ASIAN_HANDICAP, S.HOME, "0", "1-1", V),
    (M.ASIAN_HANDICAP, S.HOME, "0", "1-0", W),
    (M.ASIAN_HANDICAP, S.HOME, "0.25", "1-1", HW),
    (M.ASIAN_HANDICAP, S.HOME, "0.25", "0-1", L),
    (M.ASIAN_HANDICAP, S.AWAY, "0.25", "1-1", HL),
    (M.ASIAN_HANDICAP, S.HOME, "1.5", "0-1", W),
    (M.ASIAN_HANDICAP, S.HOME, "1.5", "0-2", L),
    (M.ASIAN_HANDICAP, S.HOME, "-1.25", "2-1", HL),
    (M.ASIAN_HANDICAP, S.HOME, "-1.25", "3-1", W),
    (M.ASIAN_HANDICAP, S.HOME, "-1.75", "2-0", HW),
    (M.ASIAN_HANDICAP, S.AWAY, "-1.75", "2-0", HL),
    # Draw no bet
    (M.DRAW_NO_BET, S.HOME, None, "1-1", V),
    (M.DRAW_NO_BET, S.HOME, None, "2-1", W),
    (M.DRAW_NO_BET, S.HOME, None, "0-1", L),
    (M.DRAW_NO_BET, S.AWAY, None, "0-1", W),
    (M.DRAW_NO_BET, S.AWAY, None, "0-0", V),
]


@pytest.mark.parametrize(("market", "selection", "line", "score", "expected"), GOLDEN)
def test_golden_grading(
    market: M, selection: S, line: str | None, score: str, expected: Outcome
) -> None:
    home, away = (int(x) for x in score.split("-"))
    assert grade(market, selection, D(line) if line else None, home, away) is expected


def test_both_sides_of_a_two_way_line_are_mirror_images() -> None:
    mirror = {W: L, HW: HL, V: V, HL: HW, L: W}
    for line in ["-2", "-1.75", "-1.25", "-0.75", "-0.5", "-0.25", "0", "0.25", "0.5", "1"]:
        for home in range(5):
            for away in range(5):
                h = grade(M.ASIAN_HANDICAP, S.HOME, D(line), home, away)
                a = grade(M.ASIAN_HANDICAP, S.AWAY, D(line), home, away)
                assert a is mirror[h], (line, home, away)


@pytest.mark.parametrize(
    "status", [EventOutcome.POSTPONED, EventOutcome.CANCELLED, EventOutcome.ABANDONED]
)
def test_matches_not_completed_are_void(status: EventOutcome) -> None:
    assert grade_event(status, M.MATCH_RESULT, S.HOME, None, None, None) is V


def test_finished_match_needs_a_score() -> None:
    assert grade_event(EventOutcome.FINISHED, M.MATCH_RESULT, S.HOME, None, 2, 0) is W
    with pytest.raises(ValueError):
        grade_event(EventOutcome.FINISHED, M.MATCH_RESULT, S.HOME, None, None, 0)


@pytest.mark.parametrize(
    ("market", "selection", "line"),
    [
        (M.MATCH_RESULT, S.HOME, "0.5"),  # no line on 1X2
        (M.TOTAL_GOALS, S.OVER, None),  # totals need a line
        (M.TOTAL_GOALS, S.OVER, "2.3"),  # not a quarter line
        (M.TOTAL_GOALS, S.OVER, "-1"),
        (M.MATCH_RESULT, S.OVER, None),  # wrong selection for market
        (M.DRAW_NO_BET, S.DRAW, None),
    ],
)
def test_invalid_markets_are_refused(market: M, selection: S, line: str | None) -> None:
    with pytest.raises(ValueError):
        grade(market, selection, D(line) if line else None, 1, 0)


@pytest.mark.parametrize(
    ("outcome", "stake", "odds", "expected"),
    [
        (W, "33", "1.95", "31.35"),
        (HW, "20", "1.90", "9.00"),
        (V, "20", "1.90", "0.00"),
        (HL, "20", "1.90", "-10.00"),
        (L, "33", "1.95", "-33.00"),
        (W, "15", "3.70", "40.50"),
        (HW, "15", "1.87", "6.53"),  # 6.525 rounds half up
    ],
)
def test_profit(outcome: Outcome, stake: str, odds: str, expected: str) -> None:
    assert profit(outcome, D(stake), D(odds)) == D(expected)


def test_closing_line_value() -> None:
    # Took 1.95; Betfair closed at a fair 1.80 -> beat the close by 8.3%
    assert closing_line_value(D("1.95"), 1 / 1.80) == D("0.083333")
    assert closing_line_value(D("1.95"), 0.542) == D("0.0569")
    assert closing_line_value(D("1.80"), 0.6) == D("0.08")
    assert closing_line_value(D("1.50"), 0.6) < 0
