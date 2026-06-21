#!/usr/bin/env bash
# Stop any running CodexPro server + tunnel (cloudflared / ngrok) for AlphaLabs,
# then confirm the machine is CLEAN. Read-only w.r.t. the repo; only kills the
# tool's own processes. Does NOT touch the token file or any repo code.
#
# Usage: ./scripts/codexpro-stop.sh

set -uo pipefail

PORT="${CODEXPRO_PORT:-8799}"

echo "[codexpro-stop] stopping CodexPro server + tunnels..."
pkill -f 'codexpro' 2>/dev/null || true
pkill -f 'cloudflared tunnel' 2>/dev/null || true
pkill -f 'ngrok http' 2>/dev/null || true
pkill -f 'tunnel-watchdog' 2>/dev/null || true
sleep 2

echo "[codexpro-stop] verifying CLEAN..."
LISTEN="$(lsof -nP -iTCP -sTCP:LISTEN 2>/dev/null | grep -E ":${PORT}|cloudflared|ngrok" || true)"
PROCS="$(pgrep -fl 'codexpro/dist|cloudflared tunnel|ngrok http' 2>/dev/null || true)"

if [ -z "$LISTEN" ] && [ -z "$PROCS" ]; then
  echo "CLEAN"
  exit 0
else
  echo "NOT CLEAN — still present:" >&2
  [ -n "$LISTEN" ] && echo "$LISTEN" >&2
  [ -n "$PROCS" ] && echo "$PROCS" >&2
  exit 1
fi
