#!/usr/bin/env bash
# Read-only status check for CodexPro on AlphaLabs. Reports whether the local
# server, a tunnel, and a watchdog are running, and whether the private MCP
# token file exists with safe perms. Never prints the token. Starts/changes
# nothing.
#
# Usage: ./scripts/codexpro-status.sh

set -uo pipefail

PORT="${CODEXPRO_PORT:-8799}"
TOKEN_FILE="${CODEXPRO_TOKEN_FILE:-$HOME/.codexpro/alphalab-mcp.token}"

echo "== CodexPro status =="

# local server listener
LISTEN="$(lsof -nP -iTCP -sTCP:LISTEN 2>/dev/null | grep -E ":${PORT}" || true)"
if [ -n "$LISTEN" ]; then echo "server   : LISTENING on 127.0.0.1:${PORT}"; else echo "server   : not running"; fi

# tunnels
CF="$(pgrep -fl 'cloudflared tunnel' 2>/dev/null || true)"
NG="$(pgrep -fl 'ngrok http' 2>/dev/null || true)"
[ -n "$CF" ] && echo "tunnel   : cloudflared running" || true
[ -n "$NG" ] && echo "tunnel   : ngrok running" || true
[ -z "$CF" ] && [ -z "$NG" ] && echo "tunnel   : none"

# watchdog
WD="$(pgrep -fl 'tunnel-watchdog' 2>/dev/null || true)"
[ -n "$WD" ] && echo "watchdog : running" || echo "watchdog : none"

# token file (existence + perms only; never contents)
if [ -f "$TOKEN_FILE" ]; then
  PERM="$(stat -f '%Lp' "$TOKEN_FILE" 2>/dev/null || stat -c '%a' "$TOKEN_FILE" 2>/dev/null || echo '?')"
  case "$PERM" in
    600|400) echo "token    : present ($TOKEN_FILE, perms $PERM OK; not printed)";;
    *)       echo "token    : present ($TOKEN_FILE, perms $PERM INSECURE -> chmod 600)";;
  esac
else
  echo "token    : absent ($TOKEN_FILE)"
fi

# overall posture line
if [ -z "$LISTEN" ] && [ -z "$CF" ] && [ -z "$NG" ]; then
  echo "posture  : CLEAN (nothing exposed)"
else
  echo "posture  : ACTIVE (server/tunnel up)"
fi
