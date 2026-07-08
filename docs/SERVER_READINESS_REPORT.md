# AlphaLabs Server Readiness Report — Mac Mini

**Generated:** 2026-06-23  
**Purpose:** Pre-cutover readiness checklist for the Mac mini becoming the primary AlphaLabs runner  
**Status:** TEMPLATE — fill in results after running on the Mac mini

---

## How to Use This Report

Run the verification steps on the Mac mini, then mark each item PASS / FAIL.  
The target state before cutover is: all **REQUIRED** items PASS.

To fill this report: run `./scripts/verify_old_mac_runtime.sh` on the Mac mini and cross-reference each section below.

---

## Phase 2 Checks — Apple Silicon / Server Prerequisites

Run these on the Mac mini before attempting deployment.

### Homebrew

```bash
brew --version
```

| Check | Result | Notes |
|-------|--------|-------|
| Homebrew installed | `[ ] PASS  [ ] FAIL` | `brew --version` returns a version |

Install if missing: `/bin/bash -c "$(curl -fsSL https://brew.sh/install.sh)"`

### Python 3.11+

```bash
python3 --version
which python3
```

| Check | Result | Notes |
|-------|--------|-------|
| Python 3.11+ present | `[ ] PASS  [ ] FAIL` | Must not be Xcode `/Library/Developer/...` path |
| Standalone (not Xcode) | `[ ] PASS  [ ] FAIL` | Prefer `brew install python@3.12` or python.org |

### Git

```bash
git --version
```

| Check | Result | Notes |
|-------|--------|-------|
| Git installed | `[ ] PASS  [ ] FAIL` | `xcode-select --install` if missing |

### Tailscale

```bash
tailscale --version
tailscale status
tailscale ip -4
```

| Check | Result | Notes |
|-------|--------|-------|
| Tailscale installed | `[ ] PASS  [ ] FAIL` | `brew install tailscale` if missing |
| Tailscale connected to tailnet | `[ ] PASS  [ ] FAIL` | `tailscale up` if not connected |
| Mac mini has a tailnet IPv4 | `[ ] PASS  [ ] FAIL` | Record IP: `_______________` |

### Cloudflared (Optional — do not start the tunnel yet)

```bash
cloudflared --version
```

| Check | Result | Notes |
|-------|--------|-------|
| cloudflared installed | `[ ] PASS  [ ] SKIP` | SKIP is acceptable — only needed for CodexPro tunnel |

Install if needed later: `brew install cloudflare/cloudflare/cloudflared`

### Mac mini Timezone

```bash
readlink /etc/localtime | sed 's|.*/zoneinfo/||'
```

| Check | Result | Notes |
|-------|--------|-------|
| Timezone is `America/Los_Angeles` | `[ ] PASS  [ ] FAIL` | Required for scheduler calendar alignment |

Fix: System Settings → General → Date & Time → set timezone to America/Los_Angeles.

### Power Settings (prevent sleep)

```bash
sudo pmset -c sleep 0 autorestart 1 womp 1
sudo pmset -a disablesleep 1
pmset -g | grep -E 'sleep|autorestart'
```

| Check | Result | Notes |
|-------|--------|-------|
| System sleep disabled on AC | `[ ] PASS  [ ] FAIL` | Mac mini must never sleep; stays plugged in |
| Auto-restart after power loss | `[ ] PASS  [ ] FAIL` | `autorestart 1` |

---

## Phase 3 Checks — Deployment

### Git Checkout

```bash
ls ~/AlphaLab/.git
git -C ~/AlphaLab branch --show-current
git -C ~/AlphaLab rev-parse --short HEAD
git -C ~/AlphaLab status --porcelain
```

| Check | Result | Notes |
|-------|--------|-------|
| `~/AlphaLab` exists and is a git repo | `[ ] PASS  [ ] FAIL` | |
| Branch is `main` | `[ ] PASS  [ ] FAIL` | |
| Working tree clean | `[ ] PASS  [ ] FAIL` | No uncommitted source changes |
| Commit hash | `_______________` | Should match current `origin/main` |

### Python Virtualenv + Dependencies

```bash
ls ~/AlphaLab/.venv/bin/python
~/AlphaLab/.venv/bin/python --version
~/AlphaLab/.venv/bin/python -c "import fastapi, uvicorn, apscheduler; print('OK')"
```

| Check | Result | Notes |
|-------|--------|-------|
| `.venv` exists | `[ ] PASS  [ ] FAIL` | Created by `setup_old_mac.sh` |
| Core deps importable | `[ ] PASS  [ ] FAIL` | fastapi, uvicorn, apscheduler |

### `.env` File

```bash
ls -la ~/AlphaLab/.env
stat -f '%Lp' ~/AlphaLab/.env   # should be 600
```

| Check | Result | Notes |
|-------|--------|-------|
| `.env` exists | `[ ] PASS  [ ] FAIL` | Copied from old Mac; never committed |
| Permissions are 600 | `[ ] PASS  [ ] FAIL` | `chmod 600 .env` if wrong |
| `ALPHA_LAB_DB_PATH` is absolute Mac mini path | `[ ] PASS  [ ] FAIL` | e.g. `/Users/<user>/AlphaLab/alpha_lab/data/alpha_lab.sqlite3` |
| `ALPHALAB_SCHEDULER_MODE=dry_run` | `[ ] PASS  [ ] FAIL` | Must be `dry_run` before cutover |

### Runtime Directories

```bash
ls ~/AlphaLab/logs ~/AlphaLab/alpha_lab/data ~/AlphaLab/paper_trader/logs
```

| Check | Result | Notes |
|-------|--------|-------|
| `logs/` exists | `[ ] PASS  [ ] FAIL` | Created by setup script |
| `alpha_lab/data/` exists | `[ ] PASS  [ ] FAIL` | DB lives here |
| `paper_trader/logs/` exists | `[ ] PASS  [ ] FAIL` | |

---

## Phase 4 Checks — Safety and Readiness

Run these after `setup_old_mac.sh` completes on the Mac mini.

### Database

```bash
cd ~/AlphaLab
.venv/bin/python -m alpha_lab.db_status
```

| Check | Result | Notes |
|-------|--------|-------|
| DB file exists at resolved path | `[ ] PASS  [ ] FAIL` | Must be the migrated file from old Mac |
| DB is writable | `[ ] PASS  [ ] FAIL` | Not on a network mount |
| Idea / trade counts match old Mac | `[ ] PASS  [ ] FAIL` | Verify migration was complete |
| DB path is NOT on iCloud/SMB/NFS | `[ ] PASS  [ ] FAIL` | Local disk only |

### Scheduler

```bash
launchctl print gui/$(id -u)/com.alphalab.scheduler
```

| Check | Result | Notes |
|-------|--------|-------|
| Scheduler LaunchAgent loaded | `[ ] PASS  [ ] FAIL` | State should be `running` |
| Scheduler heartbeat written after start | `[ ] PASS  [ ] FAIL` | Allow ~2 min; check with `db_status` |
| `ALPHALAB_SCHEDULER_MODE=dry_run` confirmed | `[ ] PASS  [ ] FAIL` | |
| `ALPHALAB_ALLOW_AUTOMATION_PAPER_TRADES=false` | `[ ] PASS  [ ] FAIL` | |
| Safe stabilization mode = true | `[ ] PASS  [ ] FAIL` | Both above must be true |

### Alpaca Connectivity (paper only)

```bash
cd ~/AlphaLab && ./ops check alpaca   # from dev Mac after server.conf updated
# OR on the Mac mini:
curl -s -o /dev/null -w "%{http_code}\n" \
  -H "APCA-API-KEY-ID: $(grep ALPACA_API_KEY .env | cut -d= -f2)" \
  -H "APCA-API-SECRET-KEY: $(grep ALPACA_SECRET_KEY .env | cut -d= -f2)" \
  https://paper-api.alpaca.markets/v2/account
```

| Check | Result | Notes |
|-------|--------|-------|
| `ALPACA_PAPER_BASE_URL` = `https://paper-api.alpaca.markets` | `[ ] PASS  [ ] FAIL` | Exact match required |
| `/v2/account` returns HTTP 200 | `[ ] PASS  [ ] FAIL` | 200 = authenticated paper account |
| No live Alpaca base URL in `.env` | `[ ] PASS  [ ] FAIL` | `api.alpaca.markets` must NOT appear |

### Dashboard

```bash
launchctl print gui/$(id -u)/com.alphalab.dashboard
curl -s http://127.0.0.1:8787/api/health
lsof -nP -iTCP:8787 -sTCP:LISTEN
```

| Check | Result | Notes |
|-------|--------|-------|
| Dashboard LaunchAgent loaded | `[ ] PASS  [ ] FAIL` | State should be `running` |
| Bound to 127.0.0.1:8787 only | `[ ] PASS  [ ] FAIL` | Not `*:8787` (all interfaces) |
| `/api/health` returns HTTP 200 | `[ ] PASS  [ ] FAIL` | |
| `/api/health` `db_path` matches resolved path | `[ ] PASS  [ ] FAIL` | Same-DB proof |

### API Endpoints

```bash
curl -s http://127.0.0.1:8787/api/health
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8787/api/catalysts/intelligence
curl -s http://127.0.0.1:8787/api/db-status
```

| Check | Result | Notes |
|-------|--------|-------|
| `/api/health` → 200 | `[ ] PASS  [ ] FAIL` | |
| `/api/catalysts/intelligence` → 200 | `[ ] PASS  [ ] FAIL` | |
| `/api/db-status` → 200 | `[ ] PASS  [ ] FAIL` | |
| `/api/db-status` `db_path` = resolver path | `[ ] PASS  [ ] FAIL` | Split-brain check |

### Notifications

```bash
grep ALERT_DELIVERY_DRY_RUN ~/AlphaLab/.env
```

| Check | Result | Notes |
|-------|--------|-------|
| `ALERT_DELIVERY_DRY_RUN=true` | `[ ] PASS  [ ] FAIL` | Must remain true until channels confirmed |
| `ALPHALAB_ALLOW_REAL_NOTIFICATION_TESTS=false` | `[ ] PASS  [ ] FAIL` | |

### Tailscale (on Mac mini)

```bash
tailscale status
tailscale ip -4
tailscale ping <dev-mac-tailnet-name>
```

| Check | Result | Notes |
|-------|--------|-------|
| Tailscale connected | `[ ] PASS  [ ] FAIL` | |
| Mac mini visible on tailnet | `[ ] PASS  [ ] FAIL` | Dev Mac can ping Mac mini |
| Dev Mac can SSH to Mac mini over tailnet | `[ ] PASS  [ ] FAIL` | Required for `./ops` |

### Cloudflare Tunnel

| Check | Result | Notes |
|-------|--------|-------|
| Tunnel NOT running (pre-cutover) | `[ ] PASS  [ ] FAIL` | Do not start until explicitly approved post-cutover |

### MCP Access / CodexPro

| Check | Result | Notes |
|-------|--------|-------|
| CodexPro NOT started (pre-cutover) | `[ ] PASS  [ ] FAIL` | Start only after explicit approval |

---

## Overall Readiness Summary

Fill in after running all checks:

| Component | Status | Notes |
|-----------|--------|-------|
| Database | `[ ] PASS  [ ] FAIL` | |
| Scheduler | `[ ] PASS  [ ] FAIL` | |
| Alpaca paper connectivity | `[ ] PASS  [ ] FAIL` | |
| Dashboard | `[ ] PASS  [ ] FAIL` | |
| API | `[ ] PASS  [ ] FAIL` | |
| Notifications | `[ ] PASS  [ ] FAIL` | |
| Tailscale | `[ ] PASS  [ ] FAIL` | |
| Cloudflare tunnel | `[ ] SKIP (pre-cutover)` | |
| MCP access | `[ ] SKIP (pre-cutover)` | |

**Ready for cutover?** `[ ] YES  [ ] NO`

All REQUIRED items must be PASS. SKIP items (Cloudflare, MCP) are intentionally deferred.

---

*Template generated by Claude — audit only, no files changed.*
