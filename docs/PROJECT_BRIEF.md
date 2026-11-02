# Project brief

Last updated: 3 Nov 2026.

## Goal

Find value bets on soccer in the top 5 European leagues, log everything, learn over time, and **never place a bet without the owner's approval**.

## What "good" means

- The aim is **value**: odds that are higher than the true chance of the outcome justifies. Not "bets that hit". Good bets lose often; the edge shows over hundreds of bets.
- Success is measured by:
  - **Closing line value (CLV)**: do we consistently get better odds than the final price before kick-off? The best early sign of a real edge.
  - **Calibration**: do bets rated 60% win about 60% of the time?
  - **Profit over a large sample** (several hundred bets), not weeks.
- Realistic outcome: a small edge of a few percent per bet. Losing streaks happen even when everything is right.

## Strategy

**Phase 1 edge: reference price.** Use Betfair Exchange prices (margin removed) as the estimate of true probability. Flag any Australian bookmaker price that beats it by at least 3% after margin.

- Edge = bookmaker odds × fair probability − 1
- Minimum odds = the price at which edge drops to 2%
- Stake = ¼ Kelly: 0.25 × edge ÷ (odds − 1) × bankroll, rounded to $1, capped by limits and bookmaker account limits

Bookmakers in scope: Sportsbet, TAB, Ladbrokes, Neds, bet365 (Australian-licensed only).

Markets in scope: match result (1X2), total goals 2.5, both teams to score, Asian handicap, draw no bet. Not in scope initially: correct score, player props.

Other sources of edge to add over time:
- Team news and lineups (re-check prices within minutes of official lineups)
- Steam detection (fast, heavy Betfair moves that bookmakers haven't followed yet)
- Bookmaker promotions with positive value
- Own statistical model in niche markets (Poisson / xG goals model, LightGBM)

## Safety limits (defaults)

| Limit | Default |
|---|---|
| Max stake per bet | 2% of current bankroll |
| Max daily exposure (placed + queued) | 8% of bankroll |
| Drawdown stop | −15% from peak pauses all alerts until owner resumes |
| Minimum edge | 3% after margin |
| Odds range | 1.50 – 6.00 |
| Approval window | 60 min, or until odds fall below minimum |
| Correlation guard | Max 1 bet per match unless explicitly allowed |

## Roadmap

1. **Bookmakers, manual placement.** Odds feed → value finder → alert → owner places in the bookmaker app → confirms in our app with the odds they got.
2. **Own model in shadow mode.** Runs alongside; logs what it would bet; promoted only when it beats the live strategy.
3. **Paper trading on Betfair** via API at real available prices (accounts for commission and liquidity).
4. **Betfair placement with approval.** The owner taps Approve; the app re-checks the price and places only at or above the minimum. Unlock criteria: 300 settled bets with CLV above +1%.

## The bet log (key feature)

- Every generated bet is logged: awaiting approval, placed, skipped, expired.
- Results feed checked every 15 minutes; when a match ends, bets are graded won / lost / void by market rules. Skipped bets are graded too (tracked only, bankroll unaffected), so we can see whether skipping helps.
- After grading: bankroll, P/L, ROI, CLV, calibration and stake limits recalculate; the graded bet joins the training data for the weekly retrain; the owner gets a summary notification.
- Manual "Correct result" override, clearly marked in the log.

## Claude's role

Claude is the analyst, not the decision-maker:
- Reads team news into structured signals the value finder can use
- Explains each flagged bet in plain English
- Writes a weekly review of results
- Answers the owner's questions using their own data
- Flags data problems
- Proposes and tests improvements in the lab

Claude never changes the live model, stake sizing, limits or code on its own. See `RELEASE_PROCESS.md`.

## Live / lab

- **Live** = the owner's version. **Lab** = Claude's version.
- Lab gets a nightly read-only copy of live data, never credentials, and can't send alerts or place bets.
- Every lab change: backtest → shadow run → release proposal → owner taps Upgrade. One-tap rollback.
- Start with a weekly scheduled Claude session; add an in-app agent via the Claude API later.

## Practical notes

- **Kick-off times:** most top-5 matches kick off 11pm–7am Sydney time, and late team-news value often lands overnight. Lean on earlier-week prices; quiet hours setting.
- **Bookmaker limits** will come. Track them per account and cap stakes automatically.
- **Data feeds** are the main running cost. Faster scanning needs more expensive plans; confirm pricing when choosing providers.
- **Tax:** recreational gambling winnings in Australia are generally not taxed; the owner should check with an accountant if amounts become significant.
- **Responsible gambling:** deposit limits per bookmaker; BetStop (national self-exclusion register); Gambling Help Online 1800 858 858. Shown in Settings.
