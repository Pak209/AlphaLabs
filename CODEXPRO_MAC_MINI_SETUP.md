# CodexPro Mac Mini Setup — AlphaLab

**Date:** 2026-06-23  
**Machine:** Mac mini (arm64, macOS 26.4)  
**Operator:** Claude

---

## Install Path

| Item | Path |
|---|---|
| Node.js | `~/.nvm/versions/node/v22.23.1/bin/node` (installed via nvm 0.40.3) |
| npm | `~/.nvm/versions/node/v22.23.1/bin/npm` (10.9.8) |
| CodexPro binary | `~/.nvm/versions/node/v22.23.1/bin/codexpro` |
| CodexPro package | `~/.nvm/versions/node/v22.23.1/lib/node_modules/codexpro` |
| CodexPro version | **0.28.5** |
| Saved profile | `~/.codexpro/profiles/3bf86ad5a350f9d395807826.json` |

---

## Server Configuration

| Setting | Value |
|---|---|
| **Server URL** | `http://127.0.0.1:8787/mcp` |
| **Port** | **8787** |
| **Host binding** | **127.0.0.1 only** (loopback — not externally reachable) |
| **Tunnel** | **none** (disabled) |
| **Repo root** | `/Users/pak/AlphaLab` |
| **Write mode** | **off** |
| **Bash mode** | **off** |
| **Mode** | agent (read-only inspection) |

---

## Auth / Token Status

CodexPro uses **MCP session-ID tokens** for auth. Every connection requires:

1. A valid `POST /mcp` initialize handshake → server issues a `mcp-session-id` header (UUID).
2. All subsequent requests must include `mcp-session-id` — requests without it are rejected with `400 Bad Request`.

No external tunnel is configured, so the server is only reachable from localhost. There is no API key option in this version; session-ID requirement is the auth layer.

**Auth status: ENABLED (session-ID required)**

---

## Exposed Repo Root

```
/Users/pak/AlphaLab
```

---

## Safety Exclusions

### Built-in CodexPro blocklist (always active)
`.env`, `.env.*`, `*.pem`, `*.key`, `id_rsa`, `id_ed25519`, `.ssh/`, `.git/`, `node_modules/`, build/cache dirs.

### Additional blocklist (must be set via env var before launch)
```bash
export CODEXPRO_BLOCKED_GLOBS='*.sqlite3,*.sqlite,*.db,**/*.sqlite3,**/*.sqlite,**/*.db,logs,logs/**,**/logs/**,reports,reports/**,**/reports/**,data,data/**,**/data/**,credentials,credentials/**,**/credentials/**,secrets,secrets/**,**/secrets/**'
```

This closes the gap for: database files, log dirs, report dirs, data dirs, credentials dirs, secrets dirs.  
Source of truth: [`.ai/blocked-paths.md`](.ai/blocked-paths.md)

---

## How to Launch

```bash
# Load Node (required every session)
export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"

# Apply extended blocklist
export CODEXPRO_BLOCKED_GLOBS='*.sqlite3,*.sqlite,*.db,**/*.sqlite3,**/*.sqlite,**/*.db,logs,logs/**,**/logs/**,reports,reports/**,**/reports/**,data,data/**,**/data/**,credentials,credentials/**,**/credentials/**,secrets,secrets/**,**/secrets/**'

# Start server (saved profile applies write=off, bash=off, tunnel=none automatically)
codexpro start --root /Users/pak/AlphaLab --host 127.0.0.1
```

The saved profile (`~/.codexpro/profiles/3bf86ad5a350f9d395807826.json`) persists:
`tunnel=none`, `write=off`, `bash=off`, `port=8787`.

---

## Test Results (2026-06-23)

All tests performed against a live `codexpro start` instance with `CODEXPRO_BLOCKED_GLOBS` set.

| Test | Expected | Result |
|---|---|---|
| Server binds to 127.0.0.1:8787 only | loopback only | **PASS** — `lsof` confirms `127.0.0.1.8787` |
| No tunnel | no external URL | **PASS** — `--tunnel none` |
| Session-ID auth | 400 without session-ID | **PASS** — "missing or invalid MCP session id" |
| Read safe file (`CLAUDE.md`) | content returned | **PASS** — 5 179 chars returned |
| Read `.env` | blocked | **PASS** — `CodexProError: Path is blocked by safety rules: .env` |
| Read `alpha_lab/data/alpha_lab.sqlite3` | blocked | **PASS** — `CodexProError: Path is blocked by safety rules: alpha_lab/data/alpha_lab.sqlite3` |
| Write attempt (`write` tool) | blocked | **PASS** — `write/edit tools are disabled because CODEXPRO_WRITE_MODE=off` |
| Bash attempt (`bash` tool) | blocked | **PASS** — `bash tool is disabled` |

---

## Safety Guarantees

- **No live trading:** AlphaLabs scheduler was not started. This setup never touches the scheduler, launchd, or broker/order paths.
- **No write access:** `write=off` prevents any file modification via CodexPro.
- **No bash execution:** `bash=off` prevents any shell command execution.
- **No external exposure:** `tunnel=none` + `host=127.0.0.1` means only processes on this Mac can connect.
- **Secrets protected:** `.env`, databases, logs, reports, credentials, and keys are blocked at the path level.

---

## Known Limitations

- Node.js must be loaded via nvm before each launch (`export NVM_DIR=...`). Consider adding nvm init to `~/.zshrc` if not already present.
- No `cloudflared` installed — required only if a stable tunnel is ever needed (not approved for this repo).
- Auth is session-ID only (no persistent API key). If a persistent key is needed, configure `CODEXPRO_TOKEN` per CodexPro docs.
