# AlphaLab Remote Operations

Manage the dedicated **Old Mac** AlphaLab runtime server from your **Dev Mac**,
from anywhere, over Tailscale + SSH — through one command: `./ops`.

This layer is **purely additive**. It changes no trading logic, scheduler logic,
database schema, or runtime behavior. Every action `./ops` performs is an
*existing* on-server capability (the `scripts/*.sh` helpers, the
`alpha_lab.*` diagnostics, `launchctl`, and the loopback API) invoked over SSH.

---

## Architecture

```
        ┌──────────────────────────┐         Tailscale tailnet          ┌───────────────────────────────────────┐
        │        DEV MAC           │   (WireGuard, encrypted, private)  │            OLD MAC (server)            │
        │   development / control  │                                   │      dedicated always-on runtime       │
        │                          │                                   │                                        │
        │   ./ops <command>  ──────┼──── SSH over Tailscale/LAN ───────▶│  ~/AlphaLab  (git checkout = code)      │
        │     reads server.conf    │                                   │   ├── .env            (server-owned)    │
        │     (TAILSCALE_HOST)     │                                   │   ├── alpha_lab/data/*.sqlite3 (DB)     │
        │                          │                                   │   ├── logs/           (server-owned)    │
        │   git push  ─────────────┼──┐                                │   └── LaunchAgents:                     │
        └──────────────────────────┘  │                                │        com.alphalab.dashboard (API)    │
                                       │                                │        com.alphalab.scheduler         │
                                       │   ┌──────────────┐             │        com.alphalab.options-validation │
                                       └──▶│   GitHub     │◀── git ─────┤  (dashboard binds 127.0.0.1:8787 only) │
                                           │ Pak209/      │   ff-only    │                                        │
                                           │ AlphaLabs    │   pull       └───────────────────────────────────────┘
                                           └──────────────┘
```

**Source-of-truth split**
- **GitHub** owns code.
- **Old Mac** owns runtime state: its own `.env`, the SQLite DB
  (`alpha_lab/data/alpha_lab.sqlite3`, the operational history of record), logs,
  and LaunchAgents. These are git-ignored and **never** overwritten by deploys.
- **Dev Mac / phone** are clients: they reach the data through the API over
  Tailscale/SSH — never by copying the SQLite file around.

The dashboard binds **loopback only** (`127.0.0.1:8787`). It is never bound to
`0.0.0.0`. Remote access is via SSH tunnel or Tailscale Serve.

---

## Deployment flow

```
  Dev Mac                         GitHub                  Old Mac
  ───────                         ──────                  ───────
  edit code
  git commit / git push  ───────▶ main
                                                 ./ops deploy  (from Dev Mac)
                                                   │  ssh ──────────────▶ bootstrap_old_mac_from_github.sh
                                                   │                       • refuse if checkout dirty
                                                   │                       • git fetch + pull --ff-only
                                                   │                       • pip install -r requirements
                                                   │                       • ensure runtime dirs
                                                   │                       • .env / DB / logs untouched
                                                   │  ssh ──────────────▶ launchctl kickstart dashboard + scheduler
                                                   └─ ssh ──────────────▶ verify_old_mac_runtime.sh (health gate)
                                                                          summary: <old commit> -> <new commit>
```

`./ops deploy` is a thin orchestrator over the existing, proven server scripts —
it does not invent a new deploy path. A dirty server checkout aborts the deploy
before anything is reloaded.

---

## Command reference

Run all of these from the Dev Mac, in the repo root:

| Command | What it does |
|---|---|
| `./ops doctor` | Verify Tailscale + SSH + server checkout/venv readiness |
| `./ops remote-status` | One-glance status: host, uptime, commit, agents, heartbeat |
| `./ops deploy` | Pull code (git ff-only) + reload services + verify *(confirm)* |
| `./ops health` | Run the full server-side runtime verifier |
| `./ops logs scheduler` \| `api` \| `errors` `[N]` | Tail recent logs (default 60 lines) |
| `./ops tail scheduler` \| `api` | Stream a log live (Ctrl-C to stop) |
| `./ops scheduler-status` | Scheduler agent state + heartbeat + recent log |
| `./ops api-status` | Loopback API health (`/api/health`, `db-status`, `catalysts`) |
| `./ops db-info` | Resolved DB path + idea/trade/catalyst counts |
| `./ops check polygon` \| `sec` \| `alpaca` | Key presence + endpoint reachability *(secrets hidden)* |
| `./ops status` | Show all LaunchAgent states |
| `./ops start` | Bootstrap all agents *(confirm)* |
| `./ops stop` | Bootout all agents *(confirm)* |
| `./ops restart` | Kickstart dashboard + scheduler *(confirm)* |
| `./ops reload` | Re-render + reload agents via `setup_old_mac.sh` *(confirm)* |
| `--yes` / `-y` | Skip confirmation prompts |

Connection is read from `scripts/server.conf`. `./ops` prefers `TAILSCALE_HOST`
when set, falling back to `SERVER_HOST` (LAN/Bonjour).

---

## First-time setup

### 1. On the Old Mac — Tailscale + Remote Login

```bash
# Install Tailscale (https://tailscale.com/download) and sign into your tailnet:
tailscale up
tailscale status          # note this machine's MagicDNS name / 100.x.y.z IP
```

Enable SSH: **System Settings → General → Sharing → Remote Login → On**
(limit to your user). Confirm the AlphaLab runtime is installed and healthy:

```bash
cd ~/AlphaLab && ./scripts/verify_old_mac_runtime.sh
```

(If AlphaLab is not yet installed, follow `docs/server-setup.md` first.)

### 2. On the Dev Mac — Tailscale + connection config

```bash
# Install + join the SAME tailnet:
tailscale up

cd ~/AlphaLab
cp scripts/server.conf.example scripts/server.conf
```

Edit `scripts/server.conf`:

```bash
SERVER_USER="<old-mac-login-user>"
SERVER_HOST="old-macbook.local"                       # LAN fallback
TAILSCALE_HOST="old-macbook.<tailnet-name>.ts.net"    # from step 1
REMOTE_PATH="AlphaLab"
```

Recommended — set up key-based SSH so commands don't prompt for a password:

```bash
ssh-keygen -t ed25519                                 # if you don't have a key
ssh-copy-id "$SERVER_USER@old-macbook.<tailnet>.ts.net"
```

### 3. Verify and go

```bash
./ops doctor          # all green = ready
./ops remote-status
./ops health
```

From then on, the everyday loop is: `git push` → `./ops deploy`.

---

## SSH / dashboard access

The dashboard stays on loopback. Reach the UI two ways (both keep the bind on
`127.0.0.1`):

**SSH tunnel (Dev Mac, most secure):**
```bash
ssh -N -L 8787:127.0.0.1:8787 "$SERVER_USER@old-macbook.<tailnet>.ts.net"
# then open http://127.0.0.1:8787 locally
```

**Tailscale Serve (phone, no SSH):** run once on the Old Mac —
```bash
tailscale serve --bg 127.0.0.1:8787
tailscale serve status        # prints the https://<magic-dns>.ts.net URL
```
Because any tailnet device can then hit write endpoints, set
`ALPHALAB_API_TOKEN` in the Old Mac's `.env` (see `docs/server-setup.md`).

---

## Safety model

`./ops` is built so the dangerous things are impossible-by-construction:

- **Never overwrites** `.env`, the database, logs, reports, or LaunchAgent
  config. Deploys only run `git pull --ff-only` (which leaves git-ignored runtime
  files alone) plus `pip install` and `launchctl kickstart`.
- **Dirty-checkout guard:** the underlying `bootstrap_old_mac_from_github.sh`
  refuses to pull when the server has uncommitted source changes — so a deploy
  can't silently clobber local edits, and it aborts before any service reload.
- **Confirmation required** for every state-changing action (`deploy`, `start`,
  `stop`, `restart`, `reload`). `--yes` opts out only for trusted automation.
- **No secrets printed.** `./ops check *` reports key *presence* and endpoint
  *reachability* only — never the values. The server-side verifier follows the
  same rule.
- **Read-mostly.** `status`, `*-status`, `db-info`, `logs`, `tail`, `health`,
  `remote-status`, `doctor`, and `check` make no changes at all.
- **One writer.** Only the Old Mac writes the live DB. `./ops` never copies the
  SQLite file or points anything at a network mount.

---

## Recovery procedures

**Roll back to a previous commit** (on the Old Mac — back up the DB first):
```bash
cd ~/AlphaLab
mkdir -p alpha_lab/data/backups
cp alpha_lab/data/alpha_lab.sqlite3 \
   alpha_lab/data/backups/alpha_lab.sqlite3.$(date +%Y%m%d%H%M%S).bak
git log --oneline -10
git checkout <previous_commit>
.venv/bin/python -m pip install -r requirements.txt
launchctl kickstart -k gui/$(id -u)/com.alphalab.dashboard
launchctl kickstart -k gui/$(id -u)/com.alphalab.scheduler
./scripts/verify_old_mac_runtime.sh
```
Then from the Dev Mac: `./ops health`.

**Return to latest main:**
```bash
git checkout main && git pull --ff-only origin main
```
…or just `./ops deploy` from the Dev Mac.

**Services stuck / crash-looping:** `./ops stop` then `./ops start`
(or `./ops reload` to re-render the plists via `setup_old_mac.sh`).

**Split-brain DB warning** from the verifier (API/scheduler/resolver disagree on
the DB path): stop the agents, confirm `ALPHA_LAB_DB_PATH` in `.env` is a single
old-Mac-local path (never a network/iCloud mount), then restart. See
`docs/server-setup.md` → "Access URLs".

---

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `cannot reach <target> over SSH` | Old Mac asleep/offline, Remote Login off, or wrong host/user. Run `./ops doctor`; test `ssh <user>@<host> 'echo ok'`. |
| `doctor`: no tailnet IP | `tailscale up` on the machine that's missing it; confirm both Macs are on the same tailnet. |
| `doctor`: no AlphaLab checkout | Bootstrap it: `ssh <target> '/bin/zsh -c "$(curl -fsSL https://raw.githubusercontent.com/Pak209/AlphaLabs/main/scripts/bootstrap_old_mac_from_github.sh)"'`. |
| `deploy` aborts: dirty checkout | The server has uncommitted source edits. SSH in, `git status --short`, resolve, retry. Runtime files (`.env`, DB, logs) are ignored and safe to leave. |
| SSH prompts for a password every command | Set up key auth: `ssh-copy-id <user>@<host>`. |
| `api-status`: HTTP 000 | Dashboard agent down. `./ops status`, then `./ops restart`; inspect `./ops logs api`. |
| `scheduler-status`: no heartbeat | Scheduler not running or just (re)started. `./ops restart`; watch `./ops tail scheduler`. |
| `check polygon` HTTP 401/403 | Endpoint reachable but key invalid/missing — fix `POLYGON_API_KEY` in the Old Mac's `.env`. (401/403 still proves network reachability.) |
| Timezone warning in `health` | Old Mac must be `America/Los_Angeles` for the 06:32 schedule to align with the market open. |

---

## Related docs

- `docs/server-setup.md` — full Old Mac install/setup, `.env`, access URLs.
- `docs/ALPHALABS_HANDOFF.md` — operational handoff notes.
- `scripts/verify_old_mac_runtime.sh` — the server-side health gate `./ops health` runs.
