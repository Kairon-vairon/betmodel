"""Matching matches across feeds. A wrong match would invent value, so these are strict."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from edgewise.feeds.matching import (
    FixtureCandidate,
    match_event,
    name_similarity,
    split_event_name,
)

# (API-Football, The Odds API, Betfair) spellings of the same clubs.
SAME_CLUB = [
    ("Manchester United", "Manchester United", "Man Utd"),
    ("Manchester City", "Manchester City", "Man City"),
    ("Nottingham Forest", "Nottingham Forest", "Nottm Forest"),
    ("Wolves", "Wolverhampton Wanderers", "Wolves"),
    ("Tottenham", "Tottenham Hotspur", "Tottenham"),
    ("Brighton", "Brighton and Hove Albion", "Brighton"),
    ("Atletico Madrid", "Atlético Madrid", "Atletico Madrid"),
    ("Athletic Club", "Athletic Bilbao", "Athletic Bilbao"),
    ("Real Betis", "Real Betis", "Betis"),
    ("Inter", "Inter Milan", "Inter"),
    ("AS Roma", "AS Roma", "Roma"),
    ("Bayern München", "Bayern Munich", "Bayern Munich"),
    ("Borussia Mönchengladbach", "Borussia Monchengladbach", "Mgladbach"),
    ("1. FC Köln", "FC Koln", "FC Koln"),
    ("1899 Hoffenheim", "TSG Hoffenheim", "Hoffenheim"),
    ("FC St. Pauli", "FC St. Pauli", "St Pauli"),
    ("Paris Saint Germain", "Paris Saint Germain", "Paris St-G"),
    ("Stade Brestois 29", "Brest", "Brest"),
    ("Olympique Lyonnais", "Lyon", "Lyon"),
    ("Saint Etienne", "Saint Etienne", "St Etienne"),
    ("Paris FC", "Paris FC", "Paris FC"),
]

DIFFERENT_CLUBS = [
    ("Manchester United", "Manchester City"),
    ("AC Milan", "Inter Milan"),
    ("Paris FC", "Paris Saint Germain"),
    ("Real Madrid", "Atletico Madrid"),
    ("Real Madrid", "Real Sociedad"),
    ("Borussia Dortmund", "Borussia Mönchengladbach"),
    ("Brighton", "Brentford"),
    ("Bayern München", "Bayer Leverkusen"),
]


@pytest.mark.parametrize(("reference", "odds_api", "betfair"), SAME_CLUB)
def test_spellings_of_the_same_club_match(reference: str, odds_api: str, betfair: str) -> None:
    assert name_similarity(reference, odds_api) >= 0.9
    assert name_similarity(reference, betfair) >= 0.9


@pytest.mark.parametrize(("a", "b"), DIFFERENT_CLUBS)
def test_different_clubs_do_not(a: str, b: str) -> None:
    assert name_similarity(a, b) < 0.6
    assert name_similarity(a, b) == name_similarity(b, a)


SATURDAY = datetime(2026, 11, 7, 15, 0, tzinfo=UTC)
FIXTURES = [
    ("Manchester United", "Manchester City"),
    ("Brighton", "Everton"),
    ("Wolves", "Tottenham"),
    ("Nottingham Forest", "West Ham"),
    ("Brentford", "Newcastle"),
    ("Fulham", "Crystal Palace"),
    ("Bournemouth", "Aston Villa"),
]


def candidates(kickoff: datetime = SATURDAY) -> list[FixtureCandidate]:
    return [
        FixtureCandidate(event_id=i, kickoff=kickoff, home_names=(h,), away_names=(a,))
        for i, (h, a) in enumerate(FIXTURES, start=1)
    ]


@pytest.mark.parametrize(
    ("home", "away", "expected"),
    [
        ("Man Utd", "Man City", 1),
        ("Brighton and Hove Albion", "Everton", 2),
        ("Wolverhampton Wanderers", "Tottenham Hotspur", 3),
        ("Nottm Forest", "West Ham United", 4),
        ("Brentford", "Newcastle United", 5),
        ("Fulham", "Crystal Palace", 6),
        ("AFC Bournemouth", "Aston Villa", 7),
    ],
)
def test_busy_saturday_every_match_finds_its_fixture(home: str, away: str, expected: int) -> None:
    match = match_event(home, away, SATURDAY + timedelta(minutes=5), candidates())
    assert match is not None and match.event_id == expected


def test_kickoff_times_must_agree() -> None:
    assert match_event("Brighton", "Everton", SATURDAY + timedelta(hours=3), candidates()) is None


def test_home_and_away_swapped_is_not_the_same_match() -> None:
    assert match_event("Everton", "Brighton", SATURDAY, candidates()) is None


def test_one_team_alone_is_not_enough() -> None:
    assert match_event("Brighton", "Liverpool", SATURDAY, candidates()) is None


def test_two_lookalike_fixtures_means_no_guess() -> None:
    twin = [
        FixtureCandidate(1, SATURDAY, ("Brighton",), ("Everton",)),
        FixtureCandidate(2, SATURDAY + timedelta(minutes=30), ("Brighton",), ("Everton",)),
    ]
    assert match_event("Brighton", "Everton", SATURDAY, twin) is None


def test_known_aliases_are_used() -> None:
    fixture = [
        FixtureCandidate(
            9, SATURDAY, ("Wolves", "Wolverhampton Wanderers"), ("Tottenham", "Tottenham Hotspur")
        )
    ]
    match = match_event("Wolverhampton Wanderers", "Tottenham Hotspur", SATURDAY, fixture)
    assert match is not None and match.score == 1.0


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Brighton v Everton", ("Brighton", "Everton")),
        ("Man Utd v Man City", ("Man Utd", "Man City")),
        ("Inter vs AC Milan", ("Inter", "AC Milan")),
        ("Stevenage v Luton", ("Stevenage", "Luton")),
        ("Brighton Everton", None),
    ],
)
def test_split_betfair_event_names(name: str, expected: tuple[str, str] | None) -> None:
    assert split_event_name(name) == expected
