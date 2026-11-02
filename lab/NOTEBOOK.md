# Lab notebook

Claude reads this at the start of every lab session and updates it at the end. Newest entries first. Record failed experiments too: knowing what didn't work is as valuable as what did.

## Entry format

```
### YYYY-MM-DD — <session focus>
- Data: <what the lab copy contained>
- Tested: <experiment, method>
- Result: <numbers: CLV, Brier, sample size>
- Decision: <propose / keep testing / drop>
- Next: <what to try next session>
```

## Backlog of ideas

- Lineup tracker: re-check affected prices within 2 min of official lineups
- Steam detection: speed and volume of Betfair moves vs bookmaker lag
- Earlier-week price capture (Tue–Thu), which also avoids overnight alerts
- Minimum edge per market type (draws may need a higher threshold)
- Bookmaker-specific margin patterns by market
- Poisson / xG goals model for totals and both-teams-to-score (shadow)
- Promotions tracker (bonus bets, odds boosts)

## Entries

### 2026-11-03 — Project set up
- Repository created with brief, architecture, Phase 1 plan and release process.
- No data yet. First lab session starts once Phase 1 is collecting prices and results.
