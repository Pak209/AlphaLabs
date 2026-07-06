# MCP Topology Report — AlphaLabs

**Generated:** 2026-06-23  
**Last updated:** 2026-06-23 (port fix + verification pass)  
**Scope:** Topology audit + Mac Mini port fix (8787→8788). Dev Mac / tunnel untouched.

---

## 1. Machines in the topology

| Role | Machine | Hostname | Tailscale IP | User |
|---|---|---|---|---|
| **Dev Mac** | MacBook Pro | `daniels-macbook-pro` | `100.114.195.7` | danielpak |
| **Runner / Old Mac** | MacBook Pro (old) | `daniels-MacBook-Pro-3.local` (Tailscale: `daniels-macbook-pro-2`) | `100.91.41.60` | danielpak |
| **Mac Mini** ← this machine | Mac mini (arm64) | `dans-Mac-mini.local` | — (not on Tailscale yet) | pak |

---

## 2. Dev Mac — MCP / CodexPro

| Item | Value |
|---|---|
| **CodexPro version** | 0.28.5 (installed; Node via nvm) |
| **Local port** | **8799** |
| **Local MCP endpoint** | `http://127.0.0.1:8799/mcp` |
| **Public MCP endpoint** | `https://mcp.pak-labs.com/mcp` |
| **Auth** | MCP token (`~/.codexpro/alphalab-mcp.token`, perms 600) + session-ID |
| **Tunnel type** | Cloudflare **named tunnel** (`codexpro-alphalab`) |
| **Tunnel binary** | `~/.codexpro/bin/cloudflared` |
| **Tunnel credentials** | `~/.cloudflared/` (exists; not read) |
| **Launch script** | `scripts/codexpro-cloudflare-stable.sh` |
| **Write mode** | off |
| **Bash mode** | off |
| **Repo root exposed** | `/Users/danielpak/AlphaLab` |

### Dev Mac — current status (as of last handoff entry)
- After a 502/530 outage (cloudflared dead while CodexPro was up), service was
  restored: `codexpro-cloudflare-stable.sh` relaunched, tunnel confirmed active.
- Pre-fix state: port 8799 listening (4d uptime), cloudflared NOT running → `mcp.pak-labs.com` = 530.
- Post-fix state: port 8799 + cloudflared both running → `mcp.pak-labs.com` = 401 (token-protected).

---

## 3. Old Mac / Runner — ports & services

| Item | Value |
|---|---|
| **Role** | AlphaLabs paper-trading scheduler (launchd) |
| **AlphaLab dashboard** | `http://127.0.0.1:8787` |
| **Tailscale Serve** | `https://daniels-macbook-pro-2.<tailnet>.ts.net/` → `http://127.0.0.1:8787` |
| **CodexPro** | **Never installed / never ran here** |
| **cloudflared** | Not present |
| **~/.codexpro** | Does not exist |

The old Mac exposes the **AlphaLab health dashboard** over Tailscale HTTPS — not
an MCP endpoint. This is a separate service from CodexPro.

---

## 4. Mac Mini — MCP / CodexPro (just installed)

| Item | Value |
|---|---|
| **CodexPro version** | 0.28.5 (installed 2026-06-23 via nvm Node 22.23.1) |
| **Saved profile port** | **8788** (fixed 2026-06-23; was 8787, collided with dashboard) |
| **Local MCP endpoint** | `http://127.0.0.1:8788/mcp` |
| **Public MCP endpoint** | None (tunnel=none) |
| **Auth** | Session-ID only (no token file configured yet) |
| **Tunnel** | None |
| **Write mode** | off |
| **Bash mode** | off |
| **Repo root exposed** | `/Users/pak/AlphaLab` |

### Verification — 2026-06-23 (all PASS)

| Test | Result |
|---|---|
| AlphaLab dashboard on `127.0.0.1:8787` | **PASS** — Python PID 22568, HTTP 200 `/api/health` |
| CodexPro on `127.0.0.1:8788` | **PASS** — node PID 25298, session-ID auth active |
| No collision between ports | **PASS** — confirmed via `lsof` |
| `CLAUDE.md` readable | **PASS** |
| `.env` blocked | **PASS** — `CodexProError: Path is blocked by safety rules: .env` |
| `alpha_lab/data/alpha_lab.sqlite3` blocked | **PASS** — `CodexProError: Path is blocked by safety rules: …sqlite3` |
| `write` tool disabled | **PASS** — `CODEXPRO_WRITE_MODE=off` |
| `bash` tool disabled | **PASS** — `CODEXPRO_BASH_MODE=off` |
| No Cloudflare changes | **CONFIRMED** — Dev Mac / `codexpro-alphalab` / `mcp.pak-labs.com` untouched |

---

## 5. Current hostname mappings

| Hostname | Service | Machine | Mechanism | Status |
|---|---|---|---|---|
| `mcp.pak-labs.com` | CodexPro MCP | Dev Mac | Cloudflare named tunnel `codexpro-alphalab` | Active (401 when token required) |
| `codex.pak-labs.com` | CodexPro MCP (fallback) | Dev Mac | Same tunnel, alternate DNS route | Script references as `$CF_HOSTNAME` fallback — not confirmed active |
| `daniels-macbook-pro-2.<tailnet>.ts.net` | AlphaLab dashboard | Old Mac (runner) | Tailscale Serve HTTPS | Active (200 /api/health) |
| *(none)* | CodexPro MCP | Mac Mini | Local only, no tunnel | Local only |

### Cloudflare tunnel `codexpro-alphalab` — architecture

```
ChatGPT → https://mcp.pak-labs.com → Cloudflare edge
                                    → cloudflared (Dev Mac, ~/.codexpro/bin/cloudflared)
                                    → http://127.0.0.1:8799/mcp  (CodexPro, Dev Mac)
```

### pak-labs.com — multiple hostnames

**Yes, multiple hostnames are supported.** Cloudflare allows:

1. **Multiple DNS routes on the same named tunnel** — one tunnel can serve
   `mcp.pak-labs.com` AND `mcp-mini.pak-labs.com` from the same cloudflared process,
   routing each to a different local port or service.
2. **Multiple named tunnels** — a second tunnel (e.g. `codexpro-mini`) can be created
   and a new DNS route bound to `mcp-mini.pak-labs.com`, running its own cloudflared
   on the Mac Mini.
3. **Both approaches** coexist under the same Cloudflare zone (`pak-labs.com`).

---

## 6. Recommended dual-hostname architecture

### Goal
Expose both the Dev Mac MCP and the Mac Mini MCP publicly under `pak-labs.com`,
each at a distinct stable hostname, with independent auth.

### Proposed layout

```
                         pak-labs.com (Cloudflare zone)
                         ┌─────────────────────────────────────────┐
                         │                                         │
              mcp.pak-labs.com              mcp-mini.pak-labs.com
                    │                               │
         Tunnel: codexpro-alphalab         Tunnel: codexpro-mini  (new)
                    │                               │
         cloudflared (Dev Mac)            cloudflared (Mac Mini)
                    │                               │
         127.0.0.1:8799/mcp              127.0.0.1:8788/mcp
         (CodexPro, Dev Mac)             (CodexPro, Mac Mini)
```

### Step-by-step (human actions required — do not run without approval)

**On the Mac Mini:**

1. Fix port collision — update CodexPro saved profile:
   ```bash
   export NVM_DIR="$HOME/.nvm"; . "$NVM_DIR/nvm.sh"
   codexpro settings set --port 8788
   ```

2. Install cloudflared into `~/.codexpro/bin/`:
   ```bash
   codexpro install-cloudflared
   ```

3. Log in to Cloudflare (reuses the same account as Dev Mac):
   ```bash
   ~/.codexpro/bin/cloudflared tunnel login
   ```

4. Create a new named tunnel:
   ```bash
   ~/.codexpro/bin/cloudflared tunnel create codexpro-mini
   ```

5. Bind the DNS route:
   ```bash
   ~/.codexpro/bin/cloudflared tunnel route dns codexpro-mini mcp-mini.pak-labs.com
   ```

6. Copy `scripts/codexpro-cloudflare-stable.sh` to a Mac Mini variant with:
   - `CF_HOSTNAME=mcp-mini.pak-labs.com`
   - `CF_TUNNEL_NAME=codexpro-mini`
   - `PORT=8788`
   - `ROOT=/Users/pak/AlphaLab`

7. Configure an MCP token for the Mac Mini endpoint (separate from the Dev Mac token).

**Safety gates before enabling the tunnel:**
- [ ] Confirm `write=off`, `bash=off` are saved in Mac Mini profile
- [ ] Confirm `CODEXPRO_BLOCKED_GLOBS` is set in launch script
- [ ] Confirm token file is `chmod 600`
- [ ] Confirm no AlphaLab scheduler is running in live mode on the Mac Mini

---

## 7. Gaps and risks

| Gap | Severity | Notes |
|---|---|---|
| ~~Mac Mini CodexPro port 8787 collides with AlphaLab dashboard~~ | ~~HIGH~~ | **RESOLVED** — port changed to 8788 (2026-06-23) |
| Mac Mini has no MCP auth token (session-ID only) | Medium | Acceptable for local-only; required before any tunnel |
| ~~Mac Mini has no `~/.zshrc`~~ | ~~Medium~~ | **RESOLVED** — `~/.zshrc` created with nvm + `CODEXPRO_BLOCKED_GLOBS` exports (2026-06-23) |
| `codex.pak-labs.com` DNS route existence unconfirmed | Low | Referenced in launch script as fallback; not verified live |
| Dev Mac: tunnel watchdog is `none` (per status script) | Low | Manual restart required after crash; was the root cause of the 530 incident |
| Mac Mini not on Tailscale | Low | Cannot be reached by `./ops` from Dev Mac; no remote management |
