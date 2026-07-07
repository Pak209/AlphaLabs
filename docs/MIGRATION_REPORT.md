# AlphaLabs Migration Report — Old Mac → Mac Mini

**Generated:** 2026-06-23  
**Status:** AUDIT ONLY — no changes made  
**Scope:** Full migration from old dedicated MacBook server to new Apple Silicon Mac mini

---

## Executive Summary

AlphaLabs is a well-structured paper-trading/market-analysis system. The migration is
straightforward: the Mac mini needs a git clone, Python venv, `.env` file copied from the
old Mac, and three launchd agents registered. The existing tooling (`setup_old_mac.sh`,
`bootstrap_old_mac_from_github.sh`, `verify_old_mac_runtime.sh`) was designed exactly for
this scenario. No architectural changes are required.

**Critical rule:** The SQLite database must be migrated from the old Mac. It is the
operational history of record. Do NOT start fresh.

---

## Phase 1 — Repository Audit

### 1.1 Repository Layout

```
AlphaLab/              (clone target: ~/AlphaLab on Mac mini)
├── alpha_lab/         Core app: FastAPI, scheduler, market-data, scoring
│   ├── main.py        Entry point → uvicorn on 127.0.0.1:8787
│   ├── scheduler.py   APScheduler long-running process (18 jobs)
│   ├── api.py         REST API
│   ├── database.py    SQLite resolver
│   └── data/          ← RUNTIME: alpha_lab.sqlite3 (git-ignored, must migrate)
├── paper_trader/      Alpaca paper-trading broker client + decision engine
├── deploy/            launchd plist templates (3 agents)
├── scripts/           Startup wrappers, setup, verify, deploy
├── ops                zsh CLI for dev-Mac→server remote operations
├── requirements.txt   Python dependencies (root)
└── .env.example       Template for server .env (never committed)
```

### 1.2 Startup Commands

| Service | Entry Point | How Started |
|---------|-------------|-------------|
| Dashboard / API | `python -m alpha_lab.main --host 127.0.0.1 --port 8787` | `scripts/run_dashboard.sh` → launchd |
| Scheduler | `python -m alpha_lab.scheduler` | `scripts/run_scheduler.sh` → launchd |
| Options validator | `scripts/run_options_validation.sh` | launchd calendar trigger (weekdays 06:32 PT) |

### 1.3 LaunchAgents (always-on)

| Agent Label | Type | Trigger |
|-------------|------|---------|
| `com.alphalab.dashboard` | KeepAlive | RunAtLoad + KeepAlive |
| `com.alphalab.scheduler` | KeepAlive | RunAtLoad + KeepAlive |
| `com.alphalab.options-validation` | Calendar | Weekdays 06:32 PT (= ~09:32 ET market open) |

Templates live in `deploy/`. Rendered by `scripts/setup_old_mac.sh` into
`~/Library/LaunchAgents/`. All reference `__HOME__/AlphaLab/` — no hardcoded paths.

### 1.4 Database

- **Engine:** SQLite 3
- **Path resolution:** `ALPHA_LAB_DB_PATH` env var (falls back to relative `alpha_lab/data/alpha_lab.sqlite3`)
- **Location on server:** Absolute path, e.g. `/Users/<user>/AlphaLab/alpha_lab/data/alpha_lab.sqlite3`
- **Owner:** The server is the SOLE writer. Dev Mac and phone reach it only via the API.
- **WARNING:** Never mount over SMB/NFS/iCloud for live writes — SQLite will corrupt.
- **Migration required:** Copy the `.sqlite3` file from old Mac to Mac mini before first start.

### 1.5 Python Version Requirement

- **Minimum:** Python 3.11+ (required by `zoneinfo` stdlib usage in `scheduler.py`, `ops`)
- **Recommended:** Python 3.12 from python.org or Homebrew (NOT Xcode bundled python)
- `setup_old_mac.sh` warns if Xcode python is detected; use a standalone install

### 1.6 Python Dependencies

**Root `requirements.txt`** (core runtime):

```
fastapi>=0.110
uvicorn>=0.29
apscheduler>=3.10
pytest>=8.0
httpx>=0.27
pywebpush>=1.14        # Optional: PWA web push (lazy import; safe to omit initially)
```

**`paper_trader/requirements.txt`** (broker):

```
fastapi>=0.110
uvicorn>=0.29
apscheduler>=3.10
pytest>=8.0
httpx>=0.27
```

No compiled/native extensions that would require special ARM build steps. All packages are
pure-Python or have universal/ARM wheels on PyPI. `pywebpush` may need `cryptography` which
has ARM wheels — should install cleanly on Apple Silicon.

### 1.7 Environment Variables Required

**Hard required (system will not function without these):**

| Variable | Purpose |
|----------|---------|
| `ALPHA_LAB_DB_PATH` | Absolute path to SQLite DB on Mac mini |
| `ALPHALAB_SCHEDULER_MODE` | Must be `dry_run` (safe default) |
| `POLYGON_API_KEY` | Market data (futures, options, catalysts) |
| `SEC_USER_AGENT` | SEC EDGAR contact string (e.g. `AlphaLab/0.1 your@email.com`) |
| `ALPACA_API_KEY` | Alpaca paper account key |
| `ALPACA_SECRET_KEY` | Alpaca paper account secret |
| `ALPACA_PAPER_BASE_URL` | Must be `https://paper-api.alpaca.markets` |

**Safety flags (must be set correctly):**

| Variable | Safe Value |
|----------|-----------|
| `ALPHALAB_SCHEDULER_MODE` | `dry_run` |
| `ALPHALAB_ALLOW_AUTOMATION_PAPER_TRADES` | `false` |
| `ALPHALAB_ALLOW_MANUAL_PAPER_TRADES` | `true` |
| `ALPHALAB_REQUIRE_PAPER_APPROVAL` | `true` |
| `ALPHALAB_ALLOW_LIVE_EXECUTION` | `false` |
| `ALERT_DELIVERY_DRY_RUN` | `true` |

**Optional (system degrades gracefully if absent):**

| Variable | Purpose |
|----------|---------|
| `BENZINGA_API_KEY` | News catalyst source |
| `TIINGO_API_KEY` | News catalyst source |
| `NEWSFILTER_API_KEY` | News catalyst source |
| `ANTHROPIC_API_KEY` | LLM analyst layer (disabled if absent) |
| `OPENAI_API_KEY` | LLM fallback (disabled if absent) |
| `ALPHALAB_API_TOKEN` | API bearer token (required if using Tailscale Serve) |
| `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` | PWA web push notifications |
| `TWILIO_*` | SMS alerts |

**The old Mac's `.env` is the source of truth for all real values.**  
Copy it to the Mac mini manually, never via git.

### 1.8 Expected Ports

| Port | Bind Address | Service |
|------|-------------|---------|
| 8787 | 127.0.0.1 only | Dashboard / API (uvicorn) |

The app refuses any non-loopback bind unless `ALPHALAB_ALLOW_PUBLIC_BIND=true` is set.
Remote access is via Tailscale Serve (proxied HTTPS on tailnet) or SSH tunnel.

### 1.9 Remote Access Architecture

- **Tailscale:** Mac mini must join the same tailnet as the dev Mac
- **Cloudflare tunnel / CodexPro:** `scripts/codexpro-cloudflare-stable.sh` — opt-in; do not start until explicitly needed
- **`ops` CLI:** `scripts/server.conf` (git-ignored) configures dev Mac → Mac mini SSH target; update `TAILSCALE_HOST` to Mac mini's tailnet IP after setup

### 1.10 Scheduled Jobs (18 total)

The APScheduler process runs approximately 18 jobs covering:
- Catalyst radar (market hours)
- SEC EDGAR polling
- Polygon futures + options pulse (overnight)
- Daily brief generation
- Scheduler heartbeat (every 5 minutes, proves aliveness)
- Options validation (also has a dedicated launchd calendar agent)

Timezone: scheduler expects the server to be set to `America/Los_Angeles` for the 06:32
calendar trigger to align with ET market open. **Verify Mac mini timezone before setup.**

---

## Missing Dependencies / Risks

| # | Item | Severity | Notes |
|---|------|----------|-------|
| 1 | `.env` must be manually copied from old Mac | **HIGH** | Never committed; must transfer securely (ssh copy, not paste in chat) |
| 2 | SQLite DB must be migrated | **HIGH** | Operational history; do not start fresh |
| 3 | Mac mini timezone must be `America/Los_Angeles` | **HIGH** | Scheduler calendar trigger depends on it |
| 4 | Python 3.11+ must be standalone (not Xcode) | MEDIUM | `setup_old_mac.sh` warns but does not block |
| 5 | Tailscale must be installed + joined to tailnet | MEDIUM | Required for `./ops` remote management from dev Mac |
| 6 | Cloudflare tunnel / CodexPro optional | LOW | Do not start until explicitly approved |
| 7 | `scripts/server.conf` needs updating | LOW | Update `TAILSCALE_HOST` to Mac mini's IP after Tailscale setup |
| 8 | `pmset` power settings need sudo | LOW | `setup_old_mac.sh` applies them; Mac mini must not sleep |
| 9 | Old Mac services must be stopped before cutover | MEDIUM | Prevent two machines writing the same DB (they won't share the file, but eliminates confusion) |

---

## Recommended Deployment Order

1. **Stop old Mac** services (`./ops stop` from dev Mac)
2. **Back up** old Mac DB to a timestamped file
3. **Copy DB** to Mac mini (`scp` from old Mac → Mac mini)
4. **Copy `.env`** to Mac mini (secure transfer)
5. **Bootstrap Mac mini** from GitHub (one-command or manual)
6. **Update `ALPHA_LAB_DB_PATH`** in Mac mini `.env` to absolute Mac mini path
7. **Run `setup_old_mac.sh`** on Mac mini (installs launchd agents)
8. **Verify** with `verify_old_mac_runtime.sh`
9. **Update `scripts/server.conf`** on dev Mac to point `TAILSCALE_HOST` at Mac mini
10. **Run `./ops doctor`** from dev Mac to confirm connectivity

---

*Report generated by Claude — audit only, no files changed.*
