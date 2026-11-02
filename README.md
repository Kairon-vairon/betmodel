# Edgewise (betmodel)

Value-betting software for soccer in the top 5 European leagues. It finds bookmaker prices that beat the Betfair fair price, sends them to you for approval, logs every bet, settles results automatically, and improves over time with Claude working in a separate lab version.

**Nothing is ever placed without your approval.**

## Status

Planning complete. Phase 1 (bookmaker value finder) not started yet.

## Documents

- [Project brief](docs/PROJECT_BRIEF.md): goals, strategy, decisions
- [Architecture](docs/ARCHITECTURE.md): how it works, data feeds, data model
- [Phase 1 plan](docs/PHASE_1_PLAN.md): milestones and what you'll need to do
- [Release process](docs/RELEASE_PROCESS.md): live vs lab, upgrades, rollback
- [Lab notebook](lab/NOTEBOOK.md): Claude's running record of experiments
- [Design](design/README.md): UI preview

## Branches

- `main`: live, your version
- `lab`: Claude's version

## Working with Claude Code

Open this repository in Claude Code (desktop app Code tab, or `claude` in a terminal inside the folder). Claude reads `CLAUDE.md` automatically, so every session starts with the full context. For big build steps you can turn on `/effort ultracode`.
