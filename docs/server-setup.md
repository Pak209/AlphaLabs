# AlphaLabs Old Mac Deployment From GitHub

GitHub is the source of truth for code. The old Mac is the source of truth for
runtime state once deployed: its own `.env`, SQLite DB, logs, LaunchAgents, and
Tailscale/LAN exposure stay local on that machine.

Current known-good commit:

```text
291fdcb7a908afac5c3d8a35a6b62f6414fc69a6
Add DB status and heartbeat diagnostics
```

Repository:

```text
https://github.com/Pak209/AlphaLabs.git
```

## What Never Gets Overwritten

These are intentionally local to the old Mac and git-ignored:

```text
.env
.venv/
alpha_lab/data/
logs/
paper_trader/inbox/
paper_trader/logs/
paper_trader/generated/
paper_trader/reports/
reports/
scripts/server.conf
```

Do not copy a SQLite DB from the dev Mac onto the old Mac as part of deployment.
After cutover, the old Mac's `alpha_lab/data/alpha_lab.sqlite3` is the operational
history of record.

## Clean Setup Flow

Run these steps on the old Mac unless a step says otherwise.

### 1. Install Git And Python

Check whether Git exists:

```bash
git --version
```

If missing:

```bash
xcode-select --install
```

Install standalone Python 3.11+ from python.org or Homebrew:

```bash
python3 --version
```

Avoid relying on Xcode's bundled Python for a long-running server.

### 2. Clone AlphaLabs

```bash
cd ~
git clone https://github.com/Pak209/AlphaLabs.git AlphaLab
cd ~/AlphaLab
git checkout main
git rev-parse HEAD
```

The hash should match the commit you intend to deploy, for example:

```text
291fdcb7a908afac5c3d8a35a6b62f6414fc69a6
```

For an existing checkout:

```bash
cd ~/AlphaLab
git status --short
git fetch origin main
git pull --ff-only origin main
```

Do not pull over uncommitted source changes. Runtime files should be ignored and
do not need to be committed.

### 3. Create The Virtualenv

```bash
cd ~/AlphaLab
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
```

### 4. Create `.env` Manually

Create the old Mac's `.env` on the old Mac:

```bash
cd ~/AlphaLab
cp .env.example .env
chmod 600 .env
```

Edit `.env` locally and fill real values there. Do not commit `.env`, paste
secrets into chat, or assume the dev Mac and old Mac share environment values.

At minimum, set a local DB path for this machine:

```text
ALPHA_LAB_DB_PATH=alpha_lab/data/alpha_lab.sqlite3
ALPHALAB_SCHEDULER_MODE=dry_run
```

Use absolute paths if you prefer, but keep them old-Mac-local.

### 5. Create Runtime Folders

```bash
cd ~/AlphaLab
mkdir -p logs alpha_lab/data paper_trader/logs paper_trader/inbox paper_trader/processed paper_trader/rejected paper_trader/generated
```

This preserves existing DB/log data if those folders already exist.

### 6. Run DB Diagnostics

```bash
cd ~/AlphaLab
.venv/bin/python -m alpha_lab.db_status
.venv/bin/python -m alpha_lab.db_status --json
```

Before first startup, the DB may not exist. After startup, this should show the
old Mac's active DB path, idea/trade counts, latest scanner run, and scheduler
heartbeat when the scheduler has started.

### 7. Start The Server Manually

For a foreground smoke test:

```bash
cd ~/AlphaLab
./scripts/run_dashboard.sh
```

Then, from another terminal on the same Mac:

```bash
curl -s http://127.0.0.1:8787/api/health
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8787/api/catalysts/intelligence
curl -s http://127.0.0.1:8787/api/db-status
```

Expected:

```text
/api/health returns JSON with status ok and db_path
/api/catalysts/intelligence returns HTTP 200
/api/db-status returns the same active DB path
```

Stop the foreground server with `Ctrl-C` before installing launchd.

### 8. Install And Verify LaunchAgents

Run the setup script on the old Mac:

```bash
cd ~/AlphaLab
./scripts/setup_old_mac.sh
```

It rebuilds or verifies the virtualenv, installs dependencies, ensures runtime
folders, locks `.env` permissions, renders LaunchAgent plists, loads dashboard,
scheduler, and options-validation jobs, and prints a verification summary.

Verify:

```bash
cd ~/AlphaLab
./scripts/verify_old_mac_runtime.sh
```

This checks:

```text
git commit hash
active DB path
DB exists
API responds
/api/catalysts/intelligence returns 200
scheduler heartbeat exists
LaunchAgent status
Tailscale/LAN URL hints when detectable
```

## One-Command Bootstrap

For a new old Mac, you can run:

```bash
/bin/zsh -c "$(curl -fsSL https://raw.githubusercontent.com/Pak209/AlphaLabs/main/scripts/bootstrap_old_mac_from_github.sh)"
```

The bootstrap script clones or fast-forwards `~/AlphaLab`, creates `.venv`,
installs requirements, creates runtime directories, and prints the remaining
manual `.env` and launchd steps. It refuses to pull over a dirty source checkout.

## Updating The Old Mac Later

On the old Mac:

```bash
cd ~/AlphaLab
git status --short
git fetch origin main
git pull --ff-only origin main
.venv/bin/python -m pip install -r requirements.txt
launchctl kickstart -k gui/$(id -u)/com.alphalab.dashboard
launchctl kickstart -k gui/$(id -u)/com.alphalab.scheduler
./scripts/verify_old_mac_runtime.sh
```

Never use `git reset --hard` as a routine deploy command. It can discard local
source edits. It does not remove ignored DB files, but it is still too blunt for
normal operations.

## Rollback

Before rolling back code, preserve the old Mac DB:

```bash
cd ~/AlphaLab
mkdir -p alpha_lab/data/backups
cp alpha_lab/data/alpha_lab.sqlite3 alpha_lab/data/backups/alpha_lab.sqlite3.$(date +%Y%m%d%H%M%S).bak
```

Then return to a previous commit:

```bash
git log --oneline -10
git checkout <previous_commit>
.venv/bin/python -m pip install -r requirements.txt
launchctl kickstart -k gui/$(id -u)/com.alphalab.dashboard
launchctl kickstart -k gui/$(id -u)/com.alphalab.scheduler
./scripts/verify_old_mac_runtime.sh
```

To return to latest main later:

```bash
git checkout main
git pull --ff-only origin main
launchctl kickstart -k gui/$(id -u)/com.alphalab.dashboard
launchctl kickstart -k gui/$(id -u)/com.alphalab.scheduler
```

## Access URLs

The old Mac is the **single source of truth for data**: it runs the backend and
scheduler and owns the SQLite DB. The dev Mac and phone are clients that reach
that data through the API — **never by copying `alpha_lab.sqlite3` around, and
never by pointing `ALPHA_LAB_DB_PATH` at a network/iCloud/SMB mount** (live
SQLite writes over a share corrupt the file).

The dashboard binds to loopback only:

```text
http://127.0.0.1:8787/
```

Reach it from the dev Mac or phone one of two ways. Both keep the bind on
loopback — do **not** bind the app to `0.0.0.0` unless you have deliberately
reviewed the network exposure.

### Option A — SSH tunnel (dev Mac, most secure)

Forward the old Mac's loopback port to your laptop over LAN or Tailscale:

```bash
# On the dev Mac; then open http://127.0.0.1:8787 locally. Leave it running.
ssh -N -L 8787:127.0.0.1:8787 <user>@old-macbook.local   # LAN (Bonjour)
ssh -N -L 8787:127.0.0.1:8787 <user>@100.x.y.z           # Tailscale IP
```

Only someone who can SSH in can reach it, so no API token is required.

### Option B — Tailscale Serve (phone, no SSH needed)

`tailscale serve` proxies the loopback dashboard onto your private tailnet over
HTTPS without rebinding the app or exposing it to the public internet:

```bash
# On the old Mac (one-time; persists across reboots):
tailscale serve --bg 127.0.0.1:8787
tailscale serve status        # prints the https://<magic-dns-name> to use
```

Then browse to that `https://<old-mac>.<tailnet>.ts.net` URL from the phone or
dev Mac (both must be signed into the same tailnet). Because any tailnet device
can now reach write endpoints, set an API token on the old Mac so mutating
requests need a bearer token. In `~/AlphaLab/.env`:

```bash
ALPHALAB_API_TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
# then: launchctl kickstart -k gui/$(id -u)/com.alphalab.dashboard
```

Reads (the dashboard) stay open; approve / paper-trade / import / chat then
require `Authorization: Bearer <token>`. To undo: `tailscale serve --https=443 off`.

The runtime verifier prints these URL hints when it can detect Tailscale or
Bonjour names, so you don't have to look them up by hand.

## Safety Rules

- GitHub contains source code only.
- The old Mac owns live `.env`, DB, logs, and LaunchAgents.
- Pull code with `git pull --ff-only`.
- Never commit `.env`, DB files, logs, reports, broker/API secrets, or runtime data.
- Keep scheduler mode `dry_run` unless you intentionally enable paper mode.
