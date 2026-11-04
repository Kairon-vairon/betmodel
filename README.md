# Edgewise (betmodel)

Value-betting software for soccer in the top 5 European leagues. It finds bookmaker prices that beat the Betfair fair price, sends them to you for approval, logs every bet, settles results automatically, and improves over time with Claude working in a separate lab version.

**Nothing is ever placed without your approval.**

## Status

Phase 1 (bookmaker value finder) in progress.

- **Built:** Milestone 1 foundations: server, database, sign-in with two-factor codes, the installable web app, Docker setup and CI. Milestone 2, data ingestion: fixtures and results, bookmaker odds, Betfair prices, feed health, and the value finder running on them. The core of settlement (grading every market, profit, closing line value), with tests.
- **Waiting for:** the data feed keys ([Connecting the data feeds](docs/FEEDS.md)). The feed connections have only been tested against sample replies so far.
- **Next:** Milestone 4, alerts and approval: phone notifications with Placed / Skip.

To run it on your own computer, follow [Running Edgewise on your own computer](docs/LAPTOP.md). To run it on a server, follow [Setting up the server](docs/SETUP.md).

## Documents

- [Project brief](docs/PROJECT_BRIEF.md): goals, strategy, decisions
- [Architecture](docs/ARCHITECTURE.md): how it works, data feeds, data model
- [Phase 1 plan](docs/PHASE_1_PLAN.md): milestones and what you'll need to do
- [Release process](docs/RELEASE_PROCESS.md): live vs lab, upgrades, rollback
- [Lab notebook](lab/NOTEBOOK.md): Claude's running record of experiments
- [Design](design/README.md): UI preview
- [Running on your own computer](docs/LAPTOP.md): step-by-step, Mac and Windows
- [Connecting the data feeds](docs/FEEDS.md): the three keys and where they go
- [Setting up the server](docs/SETUP.md): step-by-step install on a server

## Branches

- `main`: live, your version
- `lab`: Claude's version

## Code layout

| Folder | What's in it |
|---|---|
| `backend/` | Python: API (FastAPI), worker, database models and migrations, and `edgewise/domain/`, the betting logic (no database or network, fully unit-tested) |
| `web/` | The app you use on phone and computer (React + TypeScript, installable PWA) |
| `compose.yaml` | The Docker services. `docker compose up` here runs everything on this computer (laptop settings in `compose.override.yaml`) |
| `infra/` | Server extras: Caddy (HTTPS), the lab settings, and `infra/stack`, which runs the live or lab version on a server |
| `.github/workflows/` | CI: lint, type checks and tests on every push |

Run the tests locally:

```bash
cd backend && python3 -m venv .venv && .venv/bin/pip install -e '.[dev]' && .venv/bin/pytest
```

```bash
cd web && npm ci && npm test
```

The PostgreSQL integration tests run when `TEST_DATABASE_URL` points at an empty test database (CI does this).

## Working with Claude Code

Open this repository in Claude Code (desktop app Code tab, or `claude` in a terminal inside the folder). Claude reads `CLAUDE.md` automatically, so every session starts with the full context. For big build steps you can turn on `/effort ultracode`.
