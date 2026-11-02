# Phase 1 plan: bookmaker value finder

Goal: a usable app that scans odds, finds value against the Betfair fair price, alerts the owner, logs everything, and settles results automatically. Placement is manual at the bookmaker.

## Milestones

### M1 — Foundations
- Repo layout: `backend/`, `web/`, `infra/`, `lab/`, `docs/`
- Docker Compose: `api`, `worker`, `db`, `web`, `caddy`; separate `live` and `lab` compose projects
- Database schema + migrations (see `ARCHITECTURE.md`)
- Owner login with TOTP 2FA
- CI: lint, type check, tests on every push

**Done when:** `docker compose up` gives a working login on the owner's server, and tests pass in CI.

### M2 — Data ingestion
- Fixtures for the 5 leagues; odds feed client; Betfair read-only client; results client
- Adaptive scan scheduler; append-only `price_snapshots`
- Feed health monitor with freshness thresholds

**Done when:** a week of fixtures and prices is stored, and killing a feed pauses its signals and sends one notification.

### M3 — Value finder
- Margin removal for Betfair fair prices (multiplicative baseline; document the method)
- Edge, minimum odds, ¼ Kelly stake, all limits, bookmaker stake caps, correlation guard
- Signal lifecycle: awaiting → placed / skipped / expired; expiry on time or when odds fall below minimum
- Human-readable reason per signal

**Done when:** unit tests cover every limit, the stake formula and expiry; signals appear for real fixtures.

### M4 — Alerts and approval
- Web Push and Telegram bot; Telegram messages with Placed / Skip buttons
- "I placed it" flow records the odds actually taken
- Quiet hours setting

**Done when:** the owner can approve or skip from their Android phone in under 10 seconds.

### M5 — Bet log and auto-settlement
- Settlement worker and grading rules (incl. Asian handicap quarter lines, draw no bet)
- Skipped-bet what-if ledger
- Closing line capture and CLV per bet
- Bankroll ledger; limits rescale after each settlement
- Manual "Correct result" override with audit trail
- CSV export

**Done when:** a replay of historical fixtures grades correctly against known results (golden test set).

### M6 — Web app (PWA)
Screens from the design preview (`design/`):
- Dashboard, Value bets (approval queue), Bet log, Settings & limits
- Phone: approval queue, bet detail, bet log
- Installable on Android (Add to Home screen), push enabled

**Done when:** the owner installs it on their phone and desktop and uses it for a full weekend of fixtures.

## After Phase 1

- Model & performance screen (CLV chart, calibration, league table)
- Lab stack + nightly sanitized data copy + release/upgrade/rollback flow
- Claude analyst (news signals, bet explanations, weekly review, chat)
- Lineup tracker, steam detection, promotions tracker, backtesting lab
- Shadow models (Poisson goals model, LightGBM)
- Betfair paper trading, then exchange placement with approval

## Owner tasks (with step-by-step guidance)

1. Choose and sign up for an odds feed and a football data feed (check pricing together first)
2. Open a Betfair account and request an application key
3. Rent a small VPS
4. Put API keys into the server's `.env` (never in the repo)
5. Create a Telegram bot via BotFather (for backup alerts)
