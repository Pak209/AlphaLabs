#!/bin/zsh
set -e
cd "$HOME/AlphaLab"
if [ -f ".env" ]; then
  set -a
  source ".env"
  set +a
fi
mkdir -p alpha_lab/data paper_trader/logs
DASHBOARD_URL="http://127.0.0.1:8787"
WEBHOOK_URL="http://127.0.0.1:8765"
if ! /usr/bin/curl -fsS "${DASHBOARD_URL}/api/health" >/dev/null 2>&1; then
  nohup "$HOME/AlphaLab/.venv/bin/python" -m alpha_lab.main --port 8787 > alpha_lab/data/alphalab.log 2>&1 &
fi
if ! /usr/bin/curl -fsS "${WEBHOOK_URL}/health" >/dev/null 2>&1; then
  nohup "$HOME/AlphaLab/.venv/bin/python" -m paper_trader.main serve --host 127.0.0.1 --port 8765 --dry-run > paper_trader/logs/webhook.log 2>&1 &
fi
for i in {1..60}; do
  if /usr/bin/curl -fsS "${DASHBOARD_URL}/api/health" >/dev/null 2>&1; then
    /usr/bin/open "${DASHBOARD_URL}"
    exit 0
  fi
  sleep 0.25
done
/usr/bin/open "${DASHBOARD_URL}"
