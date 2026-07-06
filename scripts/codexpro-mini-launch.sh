#!/usr/bin/env bash
# Mac Mini CodexPro HTTP server launcher.
# Runs the local MCP server only — cloudflared tunnel is a separate LaunchAgent.
# Safety flags are fixed (write off, bash off, blocklist required).
set -euo pipefail

export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"

export CODEXPRO_BLOCKED_GLOBS='*.sqlite3,*.sqlite,*.db,**/*.sqlite3,**/*.sqlite,**/*.db,logs,logs/**,**/logs/**,reports,reports/**,**/reports/**,data,data/**,**/data/**,credentials,credentials/**,**/credentials/**,secrets,secrets/**,**/secrets/**'

TOKEN_FILE="$HOME/.codexpro/mini-mcp.token"
if [ ! -f "$TOKEN_FILE" ]; then
  echo "ERROR: token file not found: $TOKEN_FILE" >&2; exit 1
fi
export CODEXPRO_HTTP_TOKEN
CODEXPRO_HTTP_TOKEN=$(cat "$TOKEN_FILE")

exec codexpro-mcp-http \
  --root /Users/pak/Projects/AlphaLab \
  --host 127.0.0.1 \
  --port 8788 \
  --write off \
  --bash off
