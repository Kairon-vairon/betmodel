# Architecture

## Overview

```
Data feeds ──▶ Server (24/7)                                   ──▶ Web app (PWA) + notifications ──▶ Phone & computer
               ├─ ingestion workers (odds, Betfair, fixtures/results)
               ├─ pricing (fair prices, margin removal)
               ├─ value finder + staking + limits
               ├─ bet log + settlement
               ├─ health monitor
               └─ PostgreSQL
```

The phone and computer do no heavy work. They show screens and receive notifications.

## Stack (proposed, confirm in Phase 1)

| Layer | Choice | Why |
|---|---|---|
| Backend API | Python 3.12, FastAPI | Strong data/ML ecosystem, simple async API |
| Workers / scheduling | Separate worker process with APScheduler | Adaptive scan schedules, retries |
| Database | PostgreSQL 16 | Reliable, good for time-series price snapshots with proper indexes |
| ORM / migrations | SQLAlchemy 2 + Alembic | |
| Betfair | `betfairlightweight` | Mature Betfair Exchange API client |
| Models | pandas, scikit-learn, LightGBM | |
| Web app | React + TypeScript + Vite, installable PWA | One codebase for Android and desktop |
| Push | Web Push (VAPID) + Telegram bot as backup | Telegram alerts carry Placed / Skip buttons |
| Auth | Single-owner login + TOTP 2FA | |
| Infra | Docker Compose on one small VPS, Caddy for HTTPS | Live and lab as separate stacks on one server |
| Backups | Nightly `pg_dump` to off-server storage | |

## Data feeds (candidates, confirm pricing before committing)

| Need | Candidate | Notes |
|---|---|---|
| Bookmaker odds (AU) | The Odds API or similar aggregator | Must cover Sportsbet, TAB, Ladbrokes, Neds, bet365 for top-5 leagues and our markets |
| Fair prices and closing lines | Betfair Exchange API | Needs a Betfair account and application key; read-only in Phase 1 |
| Fixtures, lineups, results | API-Football or similar | Lineups ~1 h before kick-off; final scores for settlement |

## Scanning schedule (adaptive)

| Time to kick-off | Odds scan | Betfair poll |
|---|---|---|
| > 48 h | every 30 min | every 15 min |
| 6–48 h | every 10 min | every 5 min |
| 1–6 h | every 5 min | every 1 min |
| < 1 h | every 1–2 min | streaming or every 30 s |
| Lineups published | immediate re-check of every affected market | immediate |

Each feed has a freshness threshold. If prices are older than the threshold, signals from that feed are suppressed and the owner is notified.

## Core data model (first cut)

- `competitions`, `teams`, `events` (fixtures, kick-off UTC, status, final score)
- `markets` (event, type, line), `selections`
- `bookmakers` (name, account status, stake limit, notes)
- `price_snapshots` (selection, source, bookmaker or betfair, back/lay, odds, captured_at): append-only, our own odds history
- `fair_prices` (selection, fair probability, method, computed_at)
- `signals` (every generated bet: selection, bookmaker, offered odds, fair prob, model prob, edge, suggested stake, min odds, reason, expires_at, strategy version, status: awaiting / placed / skipped / expired)
- `bets` (signal, odds taken, stake, placed_at, closing price, CLV)
- `settlements` (bet or signal, result: won / lost / void / half-won / half-lost, profit, graded_at, source, override flag)
- `bankroll_ledger` (every change with reason)
- `limits` (current values + history)
- `model_versions`, `shadow_signals` (for shadow models)
- `audit_log` (every owner action and every automated change)

## Settlement

- Worker polls results every 15 min for events with open bets or signals.
- Grading rules per market, including Asian handicap quarter lines (half-win / half-loss) and draw no bet (void on draw).
- Skipped signals are graded into a separate "what-if" ledger.
- After settlement: recompute bankroll, stats, CLV; enqueue for training data; send summary notification.

## Security

- Owner login with TOTP 2FA; sessions expire.
- Secrets only from environment variables; `.env` never committed.
- No bookmaker passwords stored, ever.
- Lab stack gets a sanitized copy of data: credentials, tokens and notification keys stripped.

## Health monitoring

- Heartbeat per worker and per feed; stale-data detector; error-rate alarms.
- If a worker dies, it restarts; if a feed stays down, alerts pause and the owner gets one notification (not a flood).

## Implementation notes (built in Milestone 1)

How the code behaves today. Update this when the behaviour changes.

**Fair price** (`backend/edgewise/domain/pricing.py`)
- Per runner: midpoint of best back and best lay implied probabilities, then the multiplicative method scales them to 100%. Power and Shin methods are implemented for the lab to compare.
- A market is not used as a reference if any runner is missing a back or lay price, or if lay is more than 5% above back (too thin to trust).
- For two-way markets with pushes (whole and quarter Asian handicap or goal lines), the fair probability means "win, given no push". That is the right input for both edge and Kelly.

**Suggestions** (`domain/finder.py`, `domain/staking.py`, `domain/limits.py`: high-risk code)
- Edge and the stake formula are as in the brief. "Don't take below" odds are rounded **up** to the cent. Stakes are rounded to the nearest dollar, then capped. Caps are rounded **down** to the dollar, so a limit can never be exceeded.
- Daily exposure means stake placed since midnight Sydney time, plus stake awaiting approval.
- The drawdown stop compares the bankroll with its peak since alerts were last resumed. Only betting results count: deposits and withdrawals move the peak with them, so taking money out never triggers the stop. Once triggered, alerts stay paused until the owner resumes them, even if the bankroll recovers. Resuming restarts the peak from the current bankroll.
- In one scan, candidates are ranked by expected profit in dollars (edge x stake), so a slightly lower price with no account limit can beat a higher price at a limited account. At most one bet per match, unless the owner allows more for that match.
- Limits have hard bounds to catch typos (e.g. max stake per bet 0.1%–10%). If stored limits don't form a valid set, nothing is suggested.
- Price freshness by time to kick-off (bookmaker / Betfair): over 48 h 75 / 45 min; 6–48 h 30 / 15 min; 1–6 h 15 / 5 min; under 1 h 10 / 2 min. A stale price never produces a suggestion and never keeps one alive.

**Signals** (`domain/lifecycle.py`, `services/signals.py`)
- A signal expires at the end of the 60-minute window, at kick-off, when a fresh bookmaker price falls below the minimum odds, when a fresh Betfair price shows the edge is now under 2%, or when alerts are paused.
- "Placed" records the odds and stake the owner actually got, with warnings if the odds were below the minimum or the stake above the suggestion. A Placed or Skip tap can be undone for 10 minutes, before kick-off.
- The database allows only one awaiting signal per selection.

**Settlement** (`domain/settlement.py`: high-risk code)
- Graded on the score after 90 minutes plus stoppage time. Quarter lines split the stake across the two neighbouring lines. Postponed, cancelled and abandoned matches are void, with a manual override.
- CLV = odds taken x fair probability at kick-off - 1.

**Running it**
- `docker compose up` in the repository root runs everything on one computer: no settings file needed, app at `http://localhost:8080` (bound to this computer only), plain-http cookie. Laptop settings live in `compose.override.yaml`.
- Servers use `infra/stack live|lab`, which names its compose files explicitly (so the laptop settings never load), checks `POSTGRES_PASSWORD` and `DOMAIN`, and adds Caddy (live) or the lab port.

**Data feeds (Milestone 2)** (`backend/edgewise/feeds/`, `services/ingest.py`, `worker/feeds.py`)
- API-Football fixtures are the reference list of matches. Odds API and Betfair matches are linked to a fixture only when kick-off times are within an hour, both teams look alike, and no other fixture comes close (`feeds/matching.py`). Linked names are saved as team aliases, so later matches link exactly. Unlinked matches are listed in the feed's details.
- Bookmaker prices come only from The Odds API (h2h, totals, spreads; region `au`). Bookmakers not in the `bookmakers` table are ignored.
- Betfair is read-only: catalogue (one call per market type) and best back/lay prices. Certificate login is used if `BETFAIR_CERT_PATH` is set, otherwise username/password login. The client logs in again once when a session expires. Asian handicap lines are paired on the home team's handicap.
- `latest_prices` / `latest_fair_prices` hold the newest value and when it was last confirmed; `price_snapshots` / `fair_prices` get a row only when a value changes. With a delayed Betfair key, prices count as 3 minutes older than when they were read.
- Polling follows the schedule above, capped for the odds feed at every 2 minutes (it refreshes about every 5). Fixtures every 6 hours; results every 15 minutes once a match should be over and until its result arrives; Betfair catalogue every 30 minutes; value finder every minute and after new prices.
- A feed pauses after 3 failures in a row once it has been failing for at least 5 minutes, or at once on a refused key or login, with one notice; it resumes with one notice on the next success. During an outage only one request per feed is tried per tick. While the odds feed or Betfair is paused, no bets are suggested (and stale prices are refused anyway).
- Not yet run against the live services (no keys yet). The tests use sample replies in each provider's documented format.

**Data integrity**
- `price_snapshots`, `bankroll_ledger` and `audit_log` are append-only: database triggers refuse updates, deletes and truncation.
- All times are stored in UTC. The code refuses times without a time zone.

**Sign-in**
- Argon2id password hashing and authenticator-app codes (TOTP). Codes from the neighbouring 30 seconds are accepted, and a code can't be reused. The 2FA secret is encrypted with `APP_SECRET_KEY`. If that isn't set, a random key is created on first start in the `app-secrets` Docker volume (`APP_SECRET_KEY_FILE`, owner-only file) and reused after that.
- Five failed attempts lock sign-in for 15 minutes.
- Sessions live in the database, which stores only a SHA-256 hash of each token. They end after 7 days, or after 3 days unused. The cookie is `__Host-`, HttpOnly, Secure and SameSite=Strict, and cross-site requests are refused.
