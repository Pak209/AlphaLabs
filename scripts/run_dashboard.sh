#!/bin/zsh
# Wrapper for the launchd dashboard service.
# launchd provides a bare environment, so this script sources .env before
# launching the uvicorn server.

set -u
PROJECT_DIR="${ALPHALAB_PROJECT_DIR:-$HOME/AlphaLab}"
cd "$PROJECT_DIR" || { echo "FATAL: project dir not found: $PROJECT_DIR"; exit 1; }

mkdir -p logs

if [ -f ".env" ]; then
    chmod 600 ".env" 2>/dev/null || true
    set -a
    source ".env"
    set +a
fi

exec "$PROJECT_DIR/.venv/bin/python" -m alpha_lab.main --host 127.0.0.1 --port 8787
