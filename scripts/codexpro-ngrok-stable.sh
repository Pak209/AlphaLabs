#!/usr/bin/env bash
# Safe stable-URL launcher for CodexPro on AlphaLabs via an ngrok free dev domain.
#
# Posture (non-negotiable, baked in below): read-only (--write off), no shell
# (--bash off), local bind 127.0.0.1, extended secret/data blocklist. The public
# hostname is STABLE, so the MCP token is the only gate -> keep it private.
#
# One-time setup before first run:
#   1) ngrok account + authtoken:   ngrok config add-authtoken <your-ngrok-token>
#   2) Reserve your free dev domain (ngrok dashboard -> Universal Gateway -> Domains)
#      and put it in NGROK_HOSTNAME below (or export it before running).
#   3) Create the private MCP token file (chmod 600), e.g.:
#        umask 077; openssl rand -hex 24 > ~/.codexpro/alphalab-mcp.token
#   4) In ChatGPT Developer Mode, create the app ONCE with Server URL:
#        https://<NGROK_HOSTNAME>/mcp?codexpro_token=<contents of the token file>
#      Paste it into the connector's Server URL field ONLY -- never into a chat box.
#
# Daily use: just run this script. The URL/token never change, so you do not
# recreate the ChatGPT app.

set -euo pipefail

# ---- config (edit these two, or override via env) -------------------------
ROOT="${CODEXPRO_ROOT:-/Users/danielpak/AlphaLab}"
NGROK_HOSTNAME="${NGROK_HOSTNAME:-CHANGE-ME.ngrok-free.dev}"
TOKEN_FILE="${CODEXPRO_TOKEN_FILE:-$HOME/.codexpro/alphalab-mcp.token}"
PORT="${CODEXPRO_PORT:-8799}"
# ---------------------------------------------------------------------------

# REQUIRED extended blocklist (closes the sqlite/logs/reports/data/secrets gap).
export CODEXPRO_BLOCKED_GLOBS='*.sqlite3,*.sqlite,*.db,**/*.sqlite3,**/*.sqlite,**/*.db,logs,logs/**,**/logs/**,reports,reports/**,**/reports/**,data,data/**,**/data/**,credentials,credentials/**,**/credentials/**,secrets,secrets/**,**/secrets/**'

# load Node via nvm
export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"

# --- preflight guards ------------------------------------------------------
if [ "$NGROK_HOSTNAME" = "CHANGE-ME.ngrok-free.dev" ]; then
  echo "ERROR: set NGROK_HOSTNAME (edit this script or export NGROK_HOSTNAME)." >&2
  exit 1
fi
if [ ! -f "$TOKEN_FILE" ]; then
  echo "ERROR: token file not found: $TOKEN_FILE" >&2
  echo "Create it: umask 077; openssl rand -hex 24 > \"$TOKEN_FILE\"" >&2
  exit 1
fi
# refuse to run if the token file is group/world readable
PERM="$(stat -f '%Lp' "$TOKEN_FILE" 2>/dev/null || stat -c '%a' "$TOKEN_FILE" 2>/dev/null || echo '')"
case "$PERM" in
  600|400) ;;
  *) echo "ERROR: $TOKEN_FILE perms are $PERM; must be 600. Run: chmod 600 \"$TOKEN_FILE\"" >&2; exit 1 ;;
esac

MCP_TOKEN="$(tr -d ' \t\r\n' < "$TOKEN_FILE")"
if [ -z "$MCP_TOKEN" ]; then echo "ERROR: token file is empty: $TOKEN_FILE" >&2; exit 1; fi

echo "CodexPro stable (ngrok) — read-only, bash off, blocklist on"
echo "  root      $ROOT"
echo "  hostname  https://$NGROK_HOSTNAME"
echo "  url       https://$NGROK_HOSTNAME/mcp?codexpro_token=<redacted>"
echo "  token     (read from $TOKEN_FILE; not printed)"
echo

# --- launch (safety flags are fixed, not configurable) ---------------------
exec codexpro ngrok \
  --root "$ROOT" \
  --hostname "$NGROK_HOSTNAME" \
  --host 127.0.0.1 \
  --port "$PORT" \
  --token "$MCP_TOKEN" \
  --write off \
  --bash off \
  --no-profile
