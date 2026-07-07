# AlphaLabs Cutover Checklist — Old Mac → Mac Mini

**Generated:** 2026-06-23  
**Purpose:** Step-by-step cutover from old MacBook server to new Apple Silicon Mac mini  
**Safety rules:**
- Do NOT enable live trading
- Do NOT modify broker settings
- Do NOT delete anything (only stop services and copy data)
- Keep `ALPHALAB_SCHEDULER_MODE=dry_run` throughout

---

## Pre-Conditions (must all be true before starting)

- [ ] `SERVER_READINESS_REPORT.md` is complete with all REQUIRED items PASS
- [ ] Mac mini is on, plugged in, connected to Tailscale
- [ ] Dev Mac can reach Mac mini over Tailscale (`ping <tailnet-ip>`)
- [ ] Old Mac is still running and reachable (`./ops remote-status` from dev Mac shows green)
- [ ] You have SSH access to both machines
- [ ] You have at least 1 hour of uninterrupted time (markets can be open or closed)

---

## Step 1 — Record Old Mac Baseline

On dev Mac:

```bash
./ops production-audit
./ops db-info
./ops scheduler-status
```

Record the following before any change:

| Item | Old Mac Value |
|------|--------------|
| Commit hash | `_______________` |
| DB path | `_______________` |
| Idea count | `_______________` |
| Trade count | `_______________` |
| Catalyst events count | `_______________` |
| Scheduler heartbeat (last) | `_______________` |
| Dashboard state | `_______________` |
| Scheduler state | `_______________` |

- [ ] Baseline recorded

---

## Step 2 — Stop Old Mac Services

This prevents any further writes to the old Mac's DB before migration.

From dev Mac:

```bash
./ops stop
```

Confirm both agents are stopped:

```bash
./ops status
```

Expected output: `NOT_LOADED` for `com.alphalab.dashboard` and `com.alphalab.scheduler`.

- [ ] Dashboard LaunchAgent stopped (`NOT_LOADED`)
- [ ] Scheduler LaunchAgent stopped (`NOT_LOADED`)

> If `./ops stop` is unavailable (old Mac unreachable), SSH directly:
> ```bash
> ssh <user>@<old-mac-tailnet-ip>
> launchctl bootout gui/$(id -u)/com.alphalab.dashboard
> launchctl bootout gui/$(id -u)/com.alphalab.scheduler
> launchctl bootout gui/$(id -u)/com.alphalab.options-validation
> ```

---

## Step 3 — Back Up Old Mac Database

SSH to old Mac and create a timestamped backup:

```bash
ssh <user>@<old-mac-tailnet-ip>
cd ~/AlphaLab
mkdir -p alpha_lab/data/backups
cp alpha_lab/data/alpha_lab.sqlite3 \
   alpha_lab/data/backups/alpha_lab.sqlite3.before-macmini-cutover-$(date +%Y%m%d%H%M%S).bak
ls -lh alpha_lab/data/backups/
```

- [ ] Backup file created on old Mac
- [ ] Backup filename recorded: `_______________`
- [ ] Backup file size matches original (verify with `ls -lh`)

---

## Step 4 — Copy Database to Mac Mini

From old Mac (or dev Mac using SSH hop), copy the DB to Mac mini.

**Option A — From old Mac (push):**

```bash
# On old Mac:
scp ~/AlphaLab/alpha_lab/data/alpha_lab.sqlite3 \
    <user>@<mac-mini-tailnet-ip>:~/AlphaLab/alpha_lab/data/alpha_lab.sqlite3
```

**Option B — From dev Mac (pull from old Mac, push to Mac mini):**

```bash
# On dev Mac:
scp <old-mac-user>@<old-mac-tailnet-ip>:~/AlphaLab/alpha_lab/data/alpha_lab.sqlite3 /tmp/alpha_lab.sqlite3
scp /tmp/alpha_lab.sqlite3 <mac-mini-user>@<mac-mini-tailnet-ip>:~/AlphaLab/alpha_lab/data/alpha_lab.sqlite3
rm /tmp/alpha_lab.sqlite3  # clean up dev Mac temp copy
```

Verify the copy on the Mac mini:

```bash
ssh <user>@<mac-mini-tailnet-ip>
ls -lh ~/AlphaLab/alpha_lab/data/alpha_lab.sqlite3
```

- [ ] DB file exists on Mac mini at correct path
- [ ] DB file size matches old Mac original (within a few bytes)
- [ ] DB path in Mac mini `.env` matches this location

---

## Step 5 — Copy `.env` to Mac Mini (if not already done)

If the Mac mini `.env` was not pre-populated, copy it now.

**From old Mac:**

```bash
scp ~/AlphaLab/.env <mac-mini-user>@<mac-mini-tailnet-ip>:~/AlphaLab/.env
```

Then on Mac mini, update `ALPHA_LAB_DB_PATH` to the Mac mini's absolute path:

```bash
ssh <user>@<mac-mini-tailnet-ip>
nano ~/AlphaLab/.env
# Change: ALPHA_LAB_DB_PATH=/Users/<OLD-MAC-USER>/AlphaLab/...
# To:     ALPHA_LAB_DB_PATH=/Users/<MAC-MINI-USER>/AlphaLab/alpha_lab/data/alpha_lab.sqlite3
chmod 600 ~/AlphaLab/.env
```

Verify on Mac mini:

```bash
grep ALPHA_LAB_DB_PATH ~/AlphaLab/.env
grep ALPHALAB_SCHEDULER_MODE ~/AlphaLab/.env   # must be dry_run
grep ALPHALAB_ALLOW_AUTOMATION_PAPER_TRADES ~/AlphaLab/.env  # must be false
```

- [ ] `.env` exists on Mac mini with correct permissions (600)
- [ ] `ALPHA_LAB_DB_PATH` points to Mac mini's local absolute path
- [ ] `ALPHALAB_SCHEDULER_MODE=dry_run` confirmed
- [ ] `ALPHALAB_ALLOW_AUTOMATION_PAPER_TRADES=false` confirmed

---

## Step 6 — Start Mac Mini Services

On the Mac mini, run the setup script (idempotent — safe to re-run):

```bash
ssh <user>@<mac-mini-tailnet-ip>
cd ~/AlphaLab
./scripts/setup_old_mac.sh
```

This will:
- Rebuild/verify the virtualenv
- Install dependencies
- Render and load the three launchd agents
- Apply power settings (may prompt for sudo password)
- Print a verification summary

- [ ] `setup_old_mac.sh` completed without errors
- [ ] All three LaunchAgents loaded (dashboard, scheduler, options-validation)
- [ ] No `[FAIL]` lines in setup output

---

## Step 7 — Verify Scheduler Heartbeat

Wait ~2 minutes for the scheduler to start and write its first heartbeat.

On Mac mini:

```bash
cd ~/AlphaLab
.venv/bin/python -m alpha_lab.db_status
```

Look for `scheduler_heartbeat_at` — it should be a recent timestamp.

Also from dev Mac (after updating `scripts/server.conf` to Mac mini's tailnet IP):

```bash
./ops scheduler-status
```

- [ ] Scheduler heartbeat written (timestamp present and recent)
- [ ] Heartbeat `db_path` matches the Mac mini's resolved DB path (same-DB proof)
- [ ] Scheduler mode shows `dry_run` in heartbeat

---

## Step 8 — Verify Dashboard Updates

On Mac mini:

```bash
curl -s http://127.0.0.1:8787/api/health | python3 -m json.tool
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8787/api/catalysts/intelligence
curl -s http://127.0.0.1:8787/api/db-status | python3 -m json.tool
```

Verify:
- `/api/health` returns `status: ok` and the correct Mac mini DB path
- `/api/db-status` returns the same DB path
- `/api/catalysts/intelligence` returns 200

- [ ] Dashboard API responding on 127.0.0.1:8787
- [ ] Bound to loopback only (not `*:8787`)
- [ ] `db_path` in API responses matches Mac mini resolved path
- [ ] Idea and trade counts match the migrated DB baseline (Step 1)

---

## Step 9 — Run Full Verification

On Mac mini:

```bash
cd ~/AlphaLab
./scripts/verify_old_mac_runtime.sh
```

Target: `All hard checks passed.`

- [ ] `verify_old_mac_runtime.sh` exits 0 (all hard checks pass)
- [ ] No `[FAIL]` lines in output
- [ ] Same-DB proof passes (resolver = API = heartbeat)

---

## Step 10 — Verify Alpaca Paper Connectivity

From dev Mac (or on Mac mini directly):

```bash
./ops check alpaca
```

Or on Mac mini:

```bash
cd ~/AlphaLab
set -a; source .env; set +a
curl -s -o /dev/null -w "%{http_code}\n" \
  -H "APCA-API-KEY-ID: $ALPACA_API_KEY" \
  -H "APCA-API-SECRET-KEY: $ALPACA_SECRET_KEY" \
  https://paper-api.alpaca.markets/v2/account
```

Expected: HTTP 200 (authenticated paper account)

- [ ] Alpaca paper account reachable (HTTP 200)
- [ ] Base URL is `https://paper-api.alpaca.markets` (not the live endpoint)

---

## Step 11 — Update Dev Mac `ops` Configuration

Update `scripts/server.conf` on dev Mac to point at the Mac mini:

```bash
# On dev Mac — edit scripts/server.conf:
SERVER_USER=<mac-mini-username>
SERVER_HOST=<mac-mini-local-hostname>.local     # LAN fallback
TAILSCALE_HOST=<mac-mini-tailnet-ip>            # preferred
REMOTE_PATH=AlphaLab
```

Verify:

```bash
./ops doctor
./ops remote-status
./ops safety-status
```

Expected: all green, `safe_stabilization_mode=true`

- [ ] `scripts/server.conf` updated to Mac mini
- [ ] `./ops doctor` passes
- [ ] `./ops remote-status` shows Mac mini host, running agents, fresh heartbeat
- [ ] `./ops safety-status` shows `safe_stabilization_mode=true`

---

## Step 12 — Verify Notifications

Notifications stay in dry-run mode throughout:

```bash
grep ALERT_DELIVERY_DRY_RUN ~/AlphaLab/.env   # on Mac mini
```

Must be `true`. Do not flip to false at this stage.

- [ ] `ALERT_DELIVERY_DRY_RUN=true` confirmed on Mac mini

---

## Post-Cutover: Optional Steps (do NOT enable during cutover)

These are intentionally excluded from cutover:

| Step | When to Do It |
|------|--------------|
| Start Cloudflare tunnel / CodexPro | Only after explicit approval and stabilization verified |
| Enable Tailscale Serve for phone access | After services confirmed stable; requires `ALPHALAB_API_TOKEN` |
| Enable notification delivery (`ALERT_DELIVERY_DRY_RUN=false`) | After channels configured and tested |
| Switch scheduler to paper mode | Only after manual paper validation passes |

---

## Rollback Plan

If anything goes wrong after cutover, restore old Mac services:

1. Stop Mac mini services: `ssh <mac-mini> 'launchctl bootout gui/$(id -u)/com.alphalab.dashboard; launchctl bootout gui/$(id -u)/com.alphalab.scheduler'`
2. Restore old Mac `.env` (it was never changed)
3. Restart old Mac services: `ssh <old-mac> 'cd ~/AlphaLab && ./scripts/setup_old_mac.sh'`
4. Update `scripts/server.conf` back to old Mac target
5. Verify with `./ops doctor` + `./ops remote-status`

**The old Mac DB backup (Step 3) is the recovery point.** The old Mac's DB was not modified during cutover.

---

## Cutover Completion Sign-Off

| Item | Status | Signed Off By |
|------|--------|--------------|
| Old Mac services stopped | `[ ] DONE` | |
| Old Mac DB backed up | `[ ] DONE` | |
| DB copied to Mac mini | `[ ] DONE` | |
| `.env` on Mac mini correct | `[ ] DONE` | |
| Mac mini services started | `[ ] DONE` | |
| Scheduler heartbeat verified | `[ ] DONE` | |
| Dashboard API verified | `[ ] DONE` | |
| Alpaca paper connectivity verified | `[ ] DONE` | |
| `./ops` updated to Mac mini | `[ ] DONE` | |
| `verify_old_mac_runtime.sh` passes | `[ ] DONE` | |
| Paper mode: dry_run confirmed | `[ ] DONE` | |
| No live trading | `[ ] CONFIRMED` | |

**Cutover complete:** `[ ] YES`  
**Date/Time:** `_______________`

---

*Generated by Claude — audit only, no files changed.*
