# CLAUDE.md — read this first

This repository is **Edgewise** (placeholder name; repo `betmodel`): software that finds value bets on soccer in the top 5 European leagues (EPL, La Liga, Serie A, Bundesliga, Ligue 1), logs every bet it generates, settles results automatically, and improves over time.

Full context lives in `docs/`. Start with `docs/PROJECT_BRIEF.md`, then `docs/PHASE_1_PLAN.md`.

## Hard rules (never break these)

1. **No bet is ever placed without the owner's explicit approval.** Not in bookmaker mode, not in exchange mode, not in tests against real accounts. The app suggests; the owner taps.
2. **No automation of bookmaker websites.** No scraping bookmaker sites, no bots placing bets there. Bookmaker prices come from a licensed odds feed; bookmaker bets are placed manually by the owner.
3. **Safety limits live in code and are enforced server-side**: max stake per bet (default 2% of bankroll), max daily exposure (default 8%), drawdown stop (default −15% from peak pauses alerts), minimum edge (default 3%), odds range (default 1.50–6.00). A bet that breaks a limit is never suggested.
4. **Stake sizing and safety limits are high-risk code.** Any change to them must be called out on its own in the release notes and never bundled silently with other changes.
5. **Never store bookmaker passwords.** API keys and secrets come from environment variables, never from the repo. Never commit `.env` files or credentials.
6. **The statistical model sets probabilities, not an LLM.** Claude (via the API) may produce structured signals (team news), explanations and reviews, but probabilities come from the model and market prices.
7. **Never present stale data as current.** If a feed is down or prices are older than their freshness threshold, pause alerts for that feed and say so.

## Branches and versions

- `main` = **live**: the owner's version. Deployed to the live stack. Changes reach it only through an approved release.
- `lab` = **Claude's version**: where Claude experiments. Deployed to the lab stack, which receives a nightly **read-only** copy of live data with credentials stripped. The lab can never send alerts or place bets.
- Releases are tagged `vMAJOR.MINOR.PATCH`. Every release has notes written for a non-technical owner (see `docs/RELEASE_PROCESS.md`).

## Working in the lab (for Claude sessions)

1. Read `lab/NOTEBOOK.md` first. It records what was tested, what worked, what failed and what to try next.
2. Work only on the `lab` branch.
3. Every change: walk-forward backtest on unseen seasons → shadow run on live prices → write a release proposal.
4. Judge changes by closing line value (CLV), calibration and Brier score. Short-term profit is noise.
5. Update `lab/NOTEBOOK.md` at the end of every session, including failed experiments.

## Owner profile

- Based in Sydney (AEDT). Many kick-offs are 11pm–7am local time.
- Comfortable with light technical steps (copy-paste commands). Explain anything they need to do in plain steps.
- Uses an Android phone and a computer; the app must work well on both.

## Where things are

- `docs/PROJECT_BRIEF.md`: goals, strategy, decisions
- `docs/ARCHITECTURE.md`: system design, data model, feeds
- `docs/PHASE_1_PLAN.md`: what to build first, milestones, acceptance criteria
- `docs/RELEASE_PROCESS.md`: live/lab workflow, release proposals, rollback
- `lab/NOTEBOOK.md`: Claude's lab notebook
- `design/`: UI design preview sources and tokens
