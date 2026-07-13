#!/bin/zsh
# Wrapper for the launchd intel-api service (commercial surface, port 8790).
# launchd provides a bare environment, so this script sources .env before
# launching uvicorn. Loopback bind ONLY — public exposure happens at the
# Cloudflare tunnel layer (api.pak-labs.com), never by binding wide here.

set -u
PROJECT_DIR="${ALPHALAB_PROJECT_DIR:-$HOME/Projects/AlphaLab}"
cd "$PROJECT_DIR" || { echo "FATAL: project dir not found: $PROJECT_DIR"; exit 1; }

mkdir -p logs

if [ -f ".env" ]; then
    chmod 600 ".env" 2>/dev/null || true
    set -a
    source ".env"
    set +a
fi

exec "$PROJECT_DIR/.venv/bin/python" -m alpha_lab.intel_api --host 127.0.0.1 --port 8790
