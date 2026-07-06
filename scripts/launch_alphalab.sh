#!/bin/zsh
set -e
cd "$HOME/Projects/AlphaLab"
if [ -f ".env" ]; then
  set -a
  source ".env"
  set +a
fi
PORT="8787"
URL="http://127.0.0.1:${PORT}"
LOG="alpha_lab/data/alphalab.log"
mkdir -p alpha_lab/data
if /usr/bin/curl -fsS "${URL}/api/health" >/dev/null 2>&1; then
  /usr/bin/open "${URL}"
  exit 0
fi
(
  for i in {1..60}; do
    if /usr/bin/curl -fsS "${URL}/api/health" >/dev/null 2>&1; then
      /usr/bin/open "${URL}"
      exit 0
    fi
    sleep 0.25
  done
) &
exec "$HOME/Projects/AlphaLab/.venv/bin/python" -m alpha_lab.main --port "${PORT}" >> "${LOG}" 2>&1
