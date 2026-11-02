# Live / lab release process

## Two versions

| | Live (`main`) | Lab (`lab`) |
|---|---|---|
| Who it's for | The owner | Claude |
| Data | Real, read-write | Nightly read-only copy, credentials stripped |
| Can send alerts | Yes | Never |
| Can place bets (exchange mode) | Only with owner approval | Never |
| Changes | Only through approved releases | Freely, with tests |

Both run on the same server as separate Docker Compose projects with separate databases.

## Nightly data copy

At 03:00 AEDT the live database is dumped, sanitized (credentials, tokens, push keys and Telegram IDs removed) and restored into the lab database. The copy is one-way.

## How a change reaches live

1. **Experiment in the lab.** Claude makes the change on the `lab` branch and records it in `lab/NOTEBOOK.md`.
2. **Backtest.** Walk-forward on at least two seasons the model never trained on.
3. **Shadow run.** The lab version runs against live incoming prices and logs what it would have bet, compared with live over the same period.
4. **Release proposal.** Claude opens a pull request from `lab` to `main` with notes using the template below.
5. **Owner review.** In the app (Lab & releases) or on GitHub: Upgrade or Reject. Rejection reasons go into the notebook.
6. **Deploy.** Merge, tag `vX.Y.Z`, deploy the new image to the live stack. Pending bets are preserved.
7. **Rollback.** The previous image tag is kept; rollback redeploys it in one step.

## Risk levels

- **Low:** new features that don't change which bets are suggested or how much; bug fixes with tests.
- **Medium:** changes to which bets are suggested (thresholds, markets, model inputs).
- **High:** anything touching stake sizing, safety limits, settlement money calculations or placement. Always listed separately at the top of the release notes.

## Release notes template

```
## vX.Y.Z — <short title>

<Two or three plain-English sentences on what changes and why.>

### High-risk changes
None. / <list>

### Same period, side by side (<dates>)
| Measure | Live | Lab |
| Value bets found | | |
| Avg CLV | | |
| Beat the close | | |
| Simulated ROI | | |

### Changes
- New / Changed / Removed / Fixed: <what> — <why, with evidence> — <risk>

### Checks
- Walk-forward backtest: <seasons>
- Shadow run: <weeks, signals>
- Automated tests: <passed / failed>
- Settlement replay: <result>
```

## Promotion rules for models

A shadow model replaces the live one only when all of these hold:
- At least 300 shadow signals
- CLV at least 0.5 points above live
- Brier score no worse than live
- Holds up in walk-forward tests on two unseen seasons
- The owner approves
