#!/usr/bin/env bash
# Safe stable-URL launcher for CodexPro on AlphaLabs via a Cloudflare NAMED tunnel.
# Stable hostname (no rotation, no ngrok free-tier interstitial that breaks the
# ChatGPT connector probe).
#
# Posture (non-negotiable, baked in): read-only (--write off), no shell
# (--bash off), local bind 127.0.0.1, extended secret/data blocklist. The
# hostname is STABLE, so the MCP token is the only gate -> keep it private.
#
# PREREQUISITES (one-time, done by a human BEFORE this script works):
#   - pak-labs.com active in Cloudflare (nameservers propagated).
#   - cloudflared logged in:        ~/.codexpro/bin/cloudflared tunnel login
#   - named tunnel created:         ~/.codexpro/bin/cloudflared tunnel create codexpro-alphalab
#   - DNS route bound to hostname:  ~/.codexpro/bin/cloudflared tunnel route dns codexpro-alphalab mcp.pak-labs.com
#   - private MCP token exists at ~/.codexpro/alphalab-mcp.token (chmod 600)
#
# Daily use: just run this script. URL/token never change -> never recreate the ChatGPT app.

set -euo pipefail

# ---- config (override via env if needed) ----------------------------------
ROOT="${CODEXPRO_ROOT:-/Users/danielpak/AlphaLab}"
CF_HOSTNAME="${CF_HOSTNAME:-mcp.pak-labs.com}"          # fallback: codex.pak-labs.com
CF_TUNNEL_NAME="${CF_TUNNEL_NAME:-codexpro-alphalab}"
TOKEN_FILE="${CODEXPRO_TOKEN_FILE:-$HOME/.codexpro/alphalab-mcp.token}"
PORT="${CODEXPRO_PORT:-8799}"
CLOUDFLARED_BIN="${CLOUDFLARED_BIN:-$HOME/.codexpro/bin/cloudflared}"
# ---------------------------------------------------------------------------

# REQUIRED extended blocklist (closes the sqlite/logs/reports/data/secrets gap).
export CODEXPRO_BLOCKED_GLOBS='*.sqlite3,*.sqlite,*.db,**/*.sqlite3,**/*.sqlite,**/*.db,logs,logs/**,**/logs/**,reports,reports/**,**/reports/**,data,data/**,**/data/**,credentials,credentials/**,**/credentials/**,secrets,secrets/**,**/secrets/**'

# point CodexPro at the bundled cloudflared
export CLOUDFLARED_BIN
export PATH="$(dirname "$CLOUDFLARED_BIN"):$PATH"

# load Node via nvm
export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"

# --- preflight guards ------------------------------------------------------
if [ ! -x "$CLOUDFLARED_BIN" ]; then
  echo "ERROR: cloudflared not found/executable at $CLOUDFLARED_BIN" >&2; exit 1
fi
if [ ! -d "$HOME/.cloudflared" ]; then
  echo "ERROR: not logged in to Cloudflare. Run: $CLOUDFLARED_BIN tunnel login" >&2; exit 1
fi
if ! "$CLOUDFLARED_BIN" tunnel list 2>/dev/null | grep -q "$CF_TUNNEL_NAME"; then
  echo "ERROR: named tunnel '$CF_TUNNEL_NAME' not found. Create it first (see header)." >&2; exit 1
fi
if [ ! -f "$TOKEN_FILE" ]; then
  echo "ERROR: token file not found: $TOKEN_FILE" >&2
  echo "Create it: umask 077; openssl rand -hex 24 > \"$TOKEN_FILE\"" >&2; exit 1
fi
PERM="$(stat -f '%Lp' "$TOKEN_FILE" 2>/dev/null || stat -c '%a' "$TOKEN_FILE" 2>/dev/null || echo '')"
case "$PERM" in
  600|400) ;;
  *) echo "ERROR: $TOKEN_FILE perms are $PERM; must be 600. Run: chmod 600 \"$TOKEN_FILE\"" >&2; exit 1 ;;
esac

MCP_TOKEN="$(tr -d ' \t\r\n' < "$TOKEN_FILE")"
if [ -z "$MCP_TOKEN" ]; then echo "ERROR: token file is empty: $TOKEN_FILE" >&2; exit 1; fi

echo "CodexPro stable (Cloudflare named) — read-only, bash off, blocklist on"
echo "  root      $ROOT"
echo "  hostname  https://$CF_HOSTNAME"
echo "  tunnel    $CF_TUNNEL_NAME"
echo "  url       https://$CF_HOSTNAME/mcp?codexpro_token=<redacted>"
echo "  token     (read from $TOKEN_FILE; not printed)"
echo

# --- launch (safety flags are fixed, not configurable) ---------------------
exec codexpro stable \
  --root "$ROOT" \
  --hostname "$CF_HOSTNAME" \
  --tunnel-name "$CF_TUNNEL_NAME" \
  --host 127.0.0.1 \
  --port "$PORT" \
  --token "$MCP_TOKEN" \
  --write off \
  --bash off \
  --no-profile
