# CodexPro Mac Mini — Cloudflare Tunnel Setup

**Date:** 2026-06-23  
**Machine:** Mac mini (arm64, macOS 26.4, user `pak`)  
**Scope:** New Cloudflare named tunnel for Mac Mini CodexPro endpoint.  
**Constraint:** Dev Mac, `mcp.pak-labs.com`, and `codexpro-alphalab` tunnel untouched.

---

## Install Path

| Component | Path |
|---|---|
| cloudflared binary | `~/.codexpro/bin/cloudflared` |
| cloudflared version | **2026.6.1** |
| Cloudflare cert | `~/.cloudflared/cert.pem` (perms 600) |
| Tunnel credential | `~/.cloudflared/0af4408b-b409-4922-9084-538f8072d956.json` (perms 600) |
| Tunnel config | `~/.cloudflared/config.yml` |
| MCP auth token | `~/.codexpro/mini-mcp.token` (perms 600, 64-byte hex, value not recorded) |
| Launch script | `scripts/codexpro-mini-launch.sh` |
| CodexPro LaunchAgent | `~/Library/LaunchAgents/com.alphalab.codexpro-mini.plist` |
| Tunnel LaunchAgent | `~/Library/LaunchAgents/com.alphalab.cloudflared-mini.plist` |
| CodexPro log | `~/Library/Logs/codexpro-mini.log` |
| Tunnel log | `~/Library/Logs/cloudflared-mini.log` |

---

## Tunnel Details

| Item | Value |
|---|---|
| **Tunnel name** | `codexpro-mini` |
| **Tunnel ID** | `0af4408b-b409-4922-9084-538f8072d956` |
| **Hostname** | `mcp-mini.pak-labs.com` |
| **DNS record** | CNAME → `0af4408b-b409-4922-9084-538f8072d956.cfargotunnel.com` |
| **Cloudflare zone** | `pak-labs.com` |
| **Local service** | `http://127.0.0.1:8788` |
| **Catch-all rule** | `http_status:404` (all other hostnames rejected) |

---

## Server URL & Port

| Item | Value |
|---|---|
| **Public MCP URL** | `https://mcp-mini.pak-labs.com/mcp` |
| **Local MCP URL** | `http://127.0.0.1:8788/mcp` |
| **Port** | **8788** (8787 reserved for AlphaLab dashboard) |
| **Host binding** | `127.0.0.1` only — tunnel is the only external path |

---

## Auth Status

| Layer | Mechanism | Status |
|---|---|---|
| **Cloudflare tunnel** | Named tunnel (no public IP, no open port) | Active |
| **MCP bearer token** | `Authorization: Bearer <token>` or `?token=<token>` | **Enabled** (`authEnabled: true`) |
| **MCP session-ID** | UUID per connection, issued on initialize | Required |
| **Write mode** | `CODEXPRO_WRITE_MODE=off` | Off |
| **Bash mode** | `CODEXPRO_BASH_MODE=off` | Off |

Unauthenticated requests return **HTTP 401**. Wrong token returns **401**. No session-ID returns **401** (auth is checked before session validation).

The token value lives only in `~/.codexpro/mini-mcp.token` (chmod 600). To share it with a ChatGPT connector: `cat ~/.codexpro/mini-mcp.token` — paste the value into the connector's "Bearer token" field and do not record it elsewhere.

---

## Exposed Repo Root

```
/Users/pak/AlphaLab
```

### Safety exclusions (CODEXPRO_BLOCKED_GLOBS — set in launch script)

```
*.sqlite3, *.db, **/*.sqlite3, **/*.db,
logs/**, **/logs/**,
reports/**, **/reports/**,
data/**, **/data/**,
credentials/**, secrets/**
```

Built-in CodexPro blocklist also covers: `.env`, `.env.*`, `*.pem`, `*.key`, `.ssh/`, `.git/`, `node_modules/`.

---

## Commands Run

```bash
# 1. Install cloudflared
curl -L https://github.com/cloudflare/cloudflared/releases/download/2026.6.1/cloudflared-darwin-arm64.tgz \
  -o /tmp/cloudflared-darwin-arm64.tgz
mkdir -p ~/.codexpro/bin
tar -xzf /tmp/cloudflared-darwin-arm64.tgz -C /tmp
mv /tmp/cloudflared ~/.codexpro/bin/cloudflared
chmod 755 ~/.codexpro/bin/cloudflared

# 2. Cloudflare login (browser auth — pak-labs.com zone authorized)
~/.codexpro/bin/cloudflared tunnel login
# → wrote ~/.cloudflared/cert.pem

# 3. Create named tunnel
~/.codexpro/bin/cloudflared tunnel create codexpro-mini
# → created tunnel ID 0af4408b-b409-4922-9084-538f8072d956
# → wrote ~/.cloudflared/0af4408b-b409-4922-9084-538f8072d956.json

# 4. DNS route
~/.codexpro/bin/cloudflared tunnel route dns codexpro-mini mcp-mini.pak-labs.com
# → added CNAME mcp-mini.pak-labs.com → 0af4408b...cfargotunnel.com

# 5. Tunnel config
# → wrote ~/.cloudflared/config.yml (tunnel + credentials-file + ingress rules)

# 6. MCP token
openssl rand -hex 32 > ~/.codexpro/mini-mcp.token
chmod 600 ~/.codexpro/mini-mcp.token

# 7. Launch script
# → wrote scripts/codexpro-mini-launch.sh (reads token file, sets CODEXPRO_HTTP_TOKEN)

# 8. LaunchAgents
# → wrote ~/Library/LaunchAgents/com.alphalab.codexpro-mini.plist
# → wrote ~/Library/LaunchAgents/com.alphalab.cloudflared-mini.plist

# 9. Load services
launchctl load ~/Library/LaunchAgents/com.alphalab.codexpro-mini.plist
launchctl load ~/Library/LaunchAgents/com.alphalab.cloudflared-mini.plist
```

---

## Test Results (2026-06-23)

### Service isolation

| Test | Expected | Result |
|---|---|---|
| AlphaLab dashboard on `127.0.0.1:8787` | HTTP 200 | **PASS** |
| CodexPro on `127.0.0.1:8788` | listening | **PASS** |
| No port collision | both coexist | **PASS** |
| LaunchAgent `com.alphalab.codexpro-mini` | exit code 0 | **PASS** |
| LaunchAgent `com.alphalab.cloudflared-mini` | exit code 0 | **PASS** |
| Tunnel — 4 connections to CF edge | sjc05/sjc08/lax07 | **PASS** |

### Auth checks (public endpoint `https://mcp-mini.pak-labs.com/mcp`)

| Test | Expected | Result |
|---|---|---|
| No token | 401 | **PASS** |
| Wrong token | 401 | **PASS** |
| Correct token — initialize | 200 + session-ID | **PASS** |
| `authEnabled` in server_config | `true` | **PASS** |

### Safety checks (authenticated session via public tunnel)

| Test | Expected | Result |
|---|---|---|
| `CLAUDE.md` readable | content returned | **PASS** |
| `.env` blocked | `CodexProError: Path is blocked` | **PASS** |
| `alpha_lab/data/alpha_lab.sqlite3` blocked | `CodexProError: Path is blocked` | **PASS** |
| `write` tool disabled | `CODEXPRO_WRITE_MODE=off` error | **PASS** |
| `bash` tool disabled | `CODEXPRO_BASH_MODE=off` error | **PASS** |
| `writeMode` in server_config | `off` | **PASS** |
| `bashMode` in server_config | `off` | **PASS** |

### Untouched systems confirmed

| Item | Status |
|---|---|
| `mcp.pak-labs.com` | Unchanged (530 = Dev Mac cloudflared offline, pre-existing) |
| `codexpro-alphalab` tunnel | Not modified |
| AlphaLab scheduler / launchd | Not touched |
| `.env` | Not read, not modified |
| SQLite database | Not read, not modified |

---

## Service management

```bash
# Status
launchctl list | grep -E "codexpro-mini|cloudflared-mini"
tail -f ~/Library/Logs/codexpro-mini.log
tail -f ~/Library/Logs/cloudflared-mini.log

# Stop
launchctl unload ~/Library/LaunchAgents/com.alphalab.codexpro-mini.plist
launchctl unload ~/Library/LaunchAgents/com.alphalab.cloudflared-mini.plist

# Start
launchctl load ~/Library/LaunchAgents/com.alphalab.codexpro-mini.plist
launchctl load ~/Library/LaunchAgents/com.alphalab.cloudflared-mini.plist

# Restart CodexPro only
launchctl kickstart -k gui/$(id -u)/com.alphalab.codexpro-mini

# Restart tunnel only
launchctl kickstart -k gui/$(id -u)/com.alphalab.cloudflared-mini
```

---

## Rollback steps

### Stop and disable services
```bash
launchctl unload ~/Library/LaunchAgents/com.alphalab.codexpro-mini.plist
launchctl unload ~/Library/LaunchAgents/com.alphalab.cloudflared-mini.plist
rm ~/Library/LaunchAgents/com.alphalab.codexpro-mini.plist
rm ~/Library/LaunchAgents/com.alphalab.cloudflared-mini.plist
```

### Delete the Cloudflare tunnel and DNS record
```bash
# This also removes the CNAME from Cloudflare DNS
~/.codexpro/bin/cloudflared tunnel delete codexpro-mini
# → removes mcp-mini.pak-labs.com CNAME automatically
```

### Clean up local files
```bash
rm ~/.cloudflared/0af4408b-b409-4922-9084-538f8072d956.json
rm ~/.cloudflared/config.yml
rm ~/.codexpro/mini-mcp.token
rm ~/.codexpro/bin/cloudflared
# optionally:
rm ~/.cloudflared/cert.pem  # revokes ability to create new tunnels on this machine
rm ~/AlphaLab/scripts/codexpro-mini-launch.sh
```

### Verify clean
```bash
lsof -nP -iTCP -sTCP:LISTEN | grep 8788   # should be empty
launchctl list | grep codexpro-mini         # should be empty
curl -s -o /dev/null -w "%{http_code}" https://mcp-mini.pak-labs.com/mcp
# → 530 (tunnel gone) or DNS NXDOMAIN within ~60s of tunnel deletion
```

---

## Auth token — connector setup (ChatGPT / MCP client)

1. Server URL: `https://mcp-mini.pak-labs.com/mcp`
2. Authentication: **Bearer token**
3. Token value: `cat ~/.codexpro/mini-mcp.token` (paste directly; do not screenshot or log)

To rotate the token:
```bash
openssl rand -hex 32 > ~/.codexpro/mini-mcp.token
chmod 600 ~/.codexpro/mini-mcp.token
launchctl kickstart -k gui/$(id -u)/com.alphalab.codexpro-mini
# Update the token in your MCP client connector
```
