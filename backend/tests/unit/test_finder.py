"""The value finder. HIGH-RISK: every safety limit has a test here (CLAUDE.md rule 3)."""

import random
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

from edgewise.domain.finder import (
    BookmakerState,
    Candidate,
    PortfolioState,
    Reject,
    find_value,
)
from edgewise.domain.limits import DEFAULT_LIMITS
from edgewise.domain.staking import StakeCap, edge

NOW = datetime(2026, 11, 7, 10, 0, tzinfo=UTC)
KICKOFF = NOW + timedelta(hours=12)
SPORTSBET, TAB, LADBROKES = 1, 2, 3


def cand(**overrides: object) -> Candidate:
    base = Candidate(
        event_id=100,
        selection_id=1000,
        bookmaker_id=SPORTSBET,
        offered_odds=D("1.95"),
        offered_at=NOW - timedelta(minutes=2),
        fair_prob=0.542,
        fair_as_of=NOW - timedelta(minutes=1),
        kickoff=KICKOFF,
        bookmaker_name="Sportsbet",
        selection_label="Brighton",
        market_label="Match result",
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


def state(**overrides: object) -> PortfolioState:
    base = PortfolioState(
        bankroll=D("2186.90"),
        peak_bankroll=D("2233.40"),
        alerts_paused=False,
        exposure_today=D("0"),
        bookmakers={
            SPORTSBET: BookmakerState(),
            TAB: BookmakerState(),
            LADBROKES: BookmakerState(stake_limit=D("15")),
        },
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


def test_brief_example_becomes_a_suggestion() -> None:
    result = find_value([cand()], state(), now=NOW)
    assert result.rejections == ()
    (s,) = result.suggestions
    assert s.edge == D("0.0569")
    assert s.stake == D("33")
    assert s.min_odds == D("1.89")
    assert s.expires_at == NOW + timedelta(minutes=60)
    assert s.capped_by is None
    assert s.strategy_version == "reference-price-v1"
    assert s.reason == (
        "Sportsbet pays 1.95 on Brighton (Match result). Betfair's fair price is 1.85 "
        "(54.2% chance), so the edge is +5.7%."
    )


def test_expires_at_kickoff_when_sooner_than_window() -> None:
    kickoff = NOW + timedelta(minutes=25)
    (s,) = find_value([cand(kickoff=kickoff)], state(), now=NOW).suggestions
    assert s.expires_at == kickoff


def reasons_for(c: Candidate, st: PortfolioState | None = None) -> tuple[Reject, ...]:
    result = find_value([c], st or state(), now=NOW)
    assert result.suggestions == ()
    (rejection,) = result.rejections
    return rejection.reasons


def test_minimum_edge() -> None:
    assert edge(D("1.90"), 0.542) < D("0.03")
    assert reasons_for(cand(offered_odds=D("1.90"))) == (Reject.EDGE_TOO_SMALL,)
    # exactly 3% is enough: 2.06 x 0.5 - 1 = 0.03
    assert find_value([cand(offered_odds=D("2.06"), fair_prob=0.5)], state(), now=NOW).suggestions


def test_odds_range_is_inclusive() -> None:
    assert find_value([cand(offered_odds=D("1.50"), fair_prob=0.7)], state(), now=NOW).suggestions
    assert find_value([cand(offered_odds=D("6.00"), fair_prob=0.2)], state(), now=NOW).suggestions
    assert reasons_for(cand(offered_odds=D("1.49"), fair_prob=0.7)) == (Reject.ODDS_OUT_OF_RANGE,)
    assert reasons_for(cand(offered_odds=D("6.20"), fair_prob=0.2)) == (Reject.ODDS_OUT_OF_RANGE,)


def test_stale_prices_never_produce_a_suggestion() -> None:
    old_book = cand(offered_at=NOW - timedelta(minutes=31))  # 12h out: 30 min allowed
    assert reasons_for(old_book) == (Reject.STALE_BOOKMAKER_PRICE,)
    old_fair = cand(fair_as_of=NOW - timedelta(minutes=16))  # 12h out: 15 min allowed
    assert reasons_for(old_fair) == (Reject.STALE_FAIR_PRICE,)
    future = cand(offered_at=NOW + timedelta(minutes=5))  # clock problem: not trusted
    assert reasons_for(future) == (Reject.STALE_BOOKMAKER_PRICE,)


def test_no_suggestions_after_kickoff() -> None:
    c = cand(kickoff=NOW - timedelta(minutes=1), offered_at=NOW, fair_as_of=NOW)
    assert reasons_for(c) == (Reject.KICKED_OFF,)


def test_bookmaker_must_be_available() -> None:
    closed = state(bookmakers={SPORTSBET: BookmakerState(available=False)})
    assert reasons_for(cand(), closed) == (Reject.BOOKMAKER_UNAVAILABLE,)
    assert reasons_for(cand(bookmaker_id=99)) == (Reject.BOOKMAKER_UNAVAILABLE,)


def test_paused_alerts_block_everything() -> None:
    assert reasons_for(cand(), state(alerts_paused=True)) == (Reject.ALERTS_PAUSED,)


def test_drawdown_stop_blocks_everything_and_is_reported() -> None:
    st = state(bankroll=D("850"), peak_bankroll=D("1000"))  # -15%
    result = find_value([cand()], st, now=NOW)
    assert result.suggestions == ()
    assert result.rejections[0].reasons == (Reject.DRAWDOWN_STOP,)
    assert result.drawdown_breached is True
    assert find_value([cand()], state(), now=NOW).drawdown_breached is False


def test_no_bankroll() -> None:
    assert reasons_for(cand(), state(bankroll=D("0"), peak_bankroll=D("0"))) == (
        Reject.NO_BANKROLL,
    )


def test_one_bet_per_match_against_existing_bets() -> None:
    assert reasons_for(cand(), state(bets_per_event={100: 1})) == (Reject.ONE_BET_PER_MATCH,)
    assert reasons_for(cand(), state(selections_with_bets=frozenset({1000}))) == (
        Reject.ALREADY_SUGGESTED,
    )


def test_one_bet_per_match_within_a_scan_keeps_the_best() -> None:
    weaker = cand(selection_id=1001, offered_odds=D("1.92"), bookmaker_id=TAB)
    stronger = cand()
    result = find_value([weaker, stronger], state(), now=NOW)
    (s,) = result.suggestions
    assert s.candidate is stronger
    assert result.rejections[0].candidate is weaker
    assert result.rejections[0].reasons == (Reject.ONE_BET_PER_MATCH,)


def test_owner_can_allow_more_bets_on_a_match() -> None:
    other = cand(selection_id=2000, offered_odds=D("2.10"), fair_prob=0.5)
    st = state(extra_bets_allowed=frozenset({100}))
    assert len(find_value([cand(), other], st, now=NOW).suggestions) == 2
    # ...but never the same selection twice
    same = cand(bookmaker_id=TAB, offered_odds=D("1.94"))
    result = find_value([cand(), same], st, now=NOW)
    assert len(result.suggestions) == 1
    assert result.rejections[0].reasons == (Reject.ALREADY_SUGGESTED,)


def test_bookmaker_limit_caps_and_can_change_the_choice() -> None:
    capped = cand(bookmaker_id=LADBROKES, offered_odds=D("2.00"), bookmaker_name="Ladbrokes")
    (s,) = find_value([capped], state(), now=NOW).suggestions
    assert s.stake == D("15")
    assert s.capped_by is StakeCap.BOOKMAKER_LIMIT
    assert s.reason.endswith("Stake capped by your account limit at this bookmaker.")
    # A slightly lower price with no limit is worth more in dollars.
    open_book = cand(bookmaker_id=TAB, offered_odds=D("1.97"))
    (best,) = find_value([capped, open_book], state(), now=NOW).suggestions
    assert best.candidate is open_book


def test_daily_exposure_is_shared_across_the_scan() -> None:
    st = state(bankroll=D("1000"), peak_bankroll=D("1000"), exposure_today=D("30"))  # cap $80
    big = [
        cand(event_id=e, selection_id=e, offered_odds=D("3.00"), fair_prob=0.5)
        for e in (1, 2, 3, 4)
    ]
    result = find_value(big, st, now=NOW)
    stakes = [s.stake for s in result.suggestions]
    assert stakes == [D("20"), D("20"), D("10")]  # 2% cap, 2% cap, then the last $10 of room
    assert result.suggestions[2].capped_by is StakeCap.DAILY_EXPOSURE
    assert result.rejections[0].reasons == (Reject.STAKE_TOO_SMALL,)


def test_all_reasons_are_reported_together() -> None:
    c = cand(offered_odds=D("1.40"), offered_at=NOW - timedelta(hours=2))
    assert set(reasons_for(c)) == {
        Reject.ODDS_OUT_OF_RANGE,
        Reject.EDGE_TOO_SMALL,
        Reject.STALE_BOOKMAKER_PRICE,
    }


def test_random_scans_never_break_a_limit() -> None:
    """Safety net: whatever comes in, no suggestion breaks a limit."""
    rng = random.Random(20261107)
    for _ in range(300):
        bankroll = D(rng.randint(100, 20000))
        st = state(
            bankroll=bankroll,
            peak_bankroll=bankroll + D(rng.randint(0, 500)),
            exposure_today=D(rng.randint(0, int(bankroll * D("0.1")))),
            bets_per_event={e: 1 for e in range(5) if rng.random() < 0.3},
        )
        cands = [
            cand(
                event_id=rng.randint(0, 9),
                selection_id=rng.randint(0, 40),
                bookmaker_id=rng.choice([SPORTSBET, TAB, LADBROKES]),
                offered_odds=D(str(round(rng.uniform(1.2, 8.0), 2))),
                fair_prob=rng.uniform(0.1, 0.85),
                offered_at=NOW - timedelta(minutes=rng.randint(0, 40)),
            )
            for _ in range(rng.randint(1, 25))
        ]
        result = find_value(cands, st, now=NOW)
        assert len(result.suggestions) + len(result.rejections) == len(cands)
        total = st.exposure_today
        events: dict[int, int] = dict(st.bets_per_event)
        for s in result.suggestions:
            c = s.candidate
            assert s.edge >= DEFAULT_LIMITS.min_edge
            assert DEFAULT_LIMITS.min_odds <= c.offered_odds <= DEFAULT_LIMITS.max_odds
            assert D(1) <= s.stake <= bankroll * DEFAULT_LIMITS.max_stake_fraction
            limit = st.bookmakers[c.bookmaker_id].stake_limit
            assert limit is None or s.stake <= limit
            assert s.stake == s.stake.to_integral_value()
            assert s.min_odds <= c.offered_odds
            assert s.expires_at <= c.kickoff
            total += s.stake
            events[c.event_id] = events.get(c.event_id, 0) + 1
        assert total <= max(
            st.exposure_today, bankroll * DEFAULT_LIMITS.max_daily_exposure_fraction
        )
        assert all(n <= 1 for e, n in events.items() if e not in st.bets_per_event)
