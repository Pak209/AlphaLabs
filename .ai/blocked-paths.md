# Blocked Paths — AlphaLabs

Paths that AI tooling must never read or expose. CodexPro enforces blocking in code
(it throws on a blocked path); this file is the source of truth for what to block and
the exact config to apply.

## Why this file exists
CodexPro's **built-in** blocklist covers: `.env`, `.env.*`, `*.pem`, `*.key`,
`id_rsa`, `id_ed25519`, `.ssh/`, `.git/`, `node_modules/`, build/cache dirs.

It does **NOT** cover (verified 2026-06-17): `*.sqlite3` / `*.sqlite` / `*.db`,
`logs/`, `reports/`, `data/`, `credentials/`, `secrets/`. Without the extension below,
a small log/report/sqlite file is readable. The extension closes the gap (verified).

## REQUIRED CodexPro config
Export this before launching CodexPro on this repo (and as the baseline for every project):

```bash
export CODEXPRO_BLOCKED_GLOBS='*.sqlite3,*.sqlite,*.db,**/*.sqlite3,**/*.sqlite,**/*.db,logs,logs/**,**/logs/**,reports,reports/**,**/reports/**,data,data/**,**/data/**,credentials,credentials/**,**/credentials/**,secrets,secrets/**,**/secrets/**'
```

## Protected paths (must remain unreadable)
- Secrets / env: `.env`, `.env.*` (built-in) — keep `*.example` templates out of scope too.
- Databases: `*.sqlite3`, `*.sqlite`, `*.db` (incl. `alpha_lab/data/alpha_lab.sqlite3`).
- Logs: `logs/`, `paper_trader/logs/`, any `**/logs/**`.
- Reports: `reports/`, `paper_trader/reports/`, any `**/reports/**`.
- Data: `data/`, `alpha_lab/data/`, any `**/data/**`.
- Credentials / secrets dirs: `credentials/`, `secrets/` (none present today; blocked pre-emptively).
- Keys: `*.pem`, `*.key`, `id_rsa*`, `id_ed25519*`, `.ssh/` (built-in).

## Verification (how to re-check)
With the env var set, attempt to read a representative file in each category through
CodexPro's `read` tool; each must return
`CodexProError: Path is blocked by safety rules: <path>`.

Examples confirmed blocked: `logs/scheduler.log`,
`reports/daily_activity/2026-06-16-alpha-activity.md`,
`alpha_lab/data/alpha_lab.sqlite3`, `.env`.
