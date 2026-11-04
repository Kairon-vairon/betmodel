"""Matching teams and matches between feeds that spell names differently.

API-Football's fixtures are the reference list of matches. A match from another feed is
linked to a fixture only when the kick-off times agree, both teams look alike, and no
other fixture comes close. Getting this wrong would compare prices for different
matches and invent value, so when in doubt there is no match.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from difflib import SequenceMatcher

# Words that don't tell clubs apart.
_STOP_WORDS = frozenset(
    {
        "fc",
        "cf",
        "afc",
        "sc",
        "ssc",
        "ss",
        "cd",
        "ud",
        "sd",
        "rcd",
        "club",
        "calcio",
        "de",
        "the",
        "and",
        "of",
    }
)

# Common short forms used by bookmakers and Betfair.
_TOKEN_SYNONYMS: dict[str, tuple[str, ...]] = {
    "man": ("manchester",),
    "utd": ("united",),
    "nottm": ("nottingham",),
    "sheff": ("sheffield",),
    "wolves": ("wolverhampton",),
    "spurs": ("tottenham",),
    "st": ("saint",),
    "ste": ("sainte",),
    "munchen": ("munich",),
    "cologne": ("koln",),
    "mgladbach": ("monchengladbach",),
    "gladbach": ("monchengladbach",),
    "internazionale": ("inter",),
    "atl": ("atletico",),
    "lyonnais": ("lyon",),
    "rennais": ("rennes",),
    "brestois": ("brest",),
    "psg": ("paris", "saint", "germain"),
}

# Whole names that the word rules can't fix.
_NAME_SYNONYMS = {
    "paris st g": "paris saint germain",
    "paris sg": "paris saint germain",
    "athletic club": "athletic bilbao",
}


def normalise_team(name: str) -> str:
    text = name.replace("ß", "ss")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return " ".join(text.split())


def team_tokens(name: str) -> frozenset[str]:
    norm = normalise_team(name)
    norm = _NAME_SYNONYMS.get(norm, norm)
    words: list[str] = []
    for token in norm.split():
        if not token.isdigit():
            words.extend(_TOKEN_SYNONYMS.get(token, (token,)))
    meaningful = [w for w in words if w not in _STOP_WORDS]
    # Keep words like "FC" when only one other word is left: "Paris FC" must not
    # shrink to "Paris" and look like Paris Saint-Germain.
    if len(meaningful) >= 2:
        return frozenset(meaningful)
    return frozenset(w for w in words if w not in {"the", "and", "of"})


def name_similarity(a: str, b: str) -> float:
    """1.0 for the same club name, lower as names differ. Symmetric."""
    ta, tb = team_tokens(a), team_tokens(b)
    if not ta or not tb:
        return 0.0
    if ta == tb:
        return 1.0
    if ta <= tb or tb <= ta:
        return 0.9  # e.g. "Brighton" and "Brighton and Hove Albion"
    jaccard = len(ta & tb) / len(ta | tb)
    sa, sb = " ".join(sorted(ta)), " ".join(sorted(tb))
    # SequenceMatcher can score a/b and b/a differently: take the higher, so the
    # result doesn't depend on which feed is asking.
    sequence = max(SequenceMatcher(None, sa, sb).ratio(), SequenceMatcher(None, sb, sa).ratio())
    return max(jaccard, 0.9 * sequence)


def best_similarity(name: str, known_names: Iterable[str]) -> float:
    return max((name_similarity(name, known) for known in known_names), default=0.0)


@dataclass(frozen=True)
class FixtureCandidate:
    event_id: int
    kickoff: datetime
    home_names: tuple[str, ...]  # the team's name and every alias seen so far
    away_names: tuple[str, ...]


@dataclass(frozen=True)
class EventMatch:
    event_id: int
    score: float


def match_event(
    home: str,
    away: str,
    kickoff: datetime,
    candidates: Sequence[FixtureCandidate],
    *,
    window: timedelta = timedelta(minutes=60),
    min_score: float = 0.75,
    min_team_score: float = 0.5,
    margin: float = 0.15,
) -> EventMatch | None:
    """The fixture this match is, or None if it isn't clearly one of them."""
    scored: list[tuple[float, int]] = []
    for candidate in candidates:
        if abs(candidate.kickoff - kickoff) > window:
            continue
        home_score = best_similarity(home, candidate.home_names)
        away_score = best_similarity(away, candidate.away_names)
        if min(home_score, away_score) < min_team_score:
            continue
        scored.append((round((home_score + away_score) / 2, 6), candidate.event_id))
    if not scored:
        return None
    scored.sort(reverse=True)
    best_score, best_id = scored[0]
    if best_score < min_score:
        return None
    if len(scored) > 1 and best_score - scored[1][0] < margin:
        return None  # two fixtures look alike: don't guess
    return EventMatch(event_id=best_id, score=best_score)


def split_event_name(name: str) -> tuple[str, str] | None:
    """Betfair names matches "Home v Away"."""
    parts = re.split(r"\s+v(?:s)?\.?\s+", name.strip(), maxsplit=1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None
    return parts[0].strip(), parts[1].strip()
