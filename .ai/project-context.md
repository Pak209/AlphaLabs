# Project Context — AlphaLabs

Context for AI coding assistants (e.g. ChatGPT via CodexPro) connecting to this repo.
This file is informational; the binding safety controls live in `agent-rules.md`,
`safe-commands.md`, and `blocked-paths.md`.

## What this project is
AlphaLabs is an automated **paper-trading / market-analysis** system. It ingests
market data and live signals, scans for catalysts, makes trading decisions, and runs
on a schedule via macOS `launchd`. It integrates with a broker (paper trading) and
external market-data sources.

## High-level layout
- `alpha_lab/` — core application: API, market-data, live sources, scanner service.
- `paper_trader/` — broker client, decision engine, paper-trade workflow (inbox /
  processed / rejected / generated / reports).
- `deploy/` — deployment assets.
- `scripts/` — operational scripts and server config.
- `ops` — operational tooling/CLI.
- `docs/` — handoff and operations documentation.
- Runtime/ignored: `logs/`, `reports/`, `alpha_lab/data/` (sqlite db), `.env`.

## Operating reality (important)
- This system places **paper trades** and runs **scheduled jobs**. Do not trigger
  either. Inspection only.
- Secrets live in `.env`; the database is `alpha_lab/data/alpha_lab.sqlite3`; logs and
  reports contain operational data. All are off-limits (see `blocked-paths.md`).

## What the assistant is here to do
- Read and explain code, review git status/diffs, help plan changes.
- It is **not** authorized to modify runtime code, trading logic, deploy scripts,
  launchd files, the database schema, or broker/API behavior in the approved mode.
- Current approved CodexPro mode is **read-only, local-only, no tunnel** — see
  `../TOOLING_HANDOFF.md`.
