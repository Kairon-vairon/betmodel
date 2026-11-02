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
