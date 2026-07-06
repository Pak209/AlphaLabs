#!/bin/zsh
#
# launchd entry point for the AlphaLab automation scheduler (idea generation +
# catalyst polling during market hours). KeepAlive restarts it if it exits.
#
# launchd starts jobs with a bare environment, so this sources .env (Alpaca keys,
# POLYGON, ALPHA_LAB_DB_PATH, automation flags, and ALPHALAB_SCHEDULER_MODE) and
# then exec's python so launchd holds the real PID.
#
# Mode is set in .env:
#   ALPHALAB_SCHEDULER_MODE=dry_run  -> generate + score only, no orders (default)
#   ALPHALAB_SCHEDULER_MODE=paper    -> idea-testing jobs place Alpaca PAPER orders
# After changing .env, reload the agent so it re-reads the value:
#   launchctl kickstart -k gui/$(id -u)/com.alphalab.scheduler
set -e
cd "$HOME/Projects/AlphaLab"
if [ -f ".env" ]; then
  chmod 600 ".env" 2>/dev/null || true
  set -a; source .env; set +a
else
  echo "WARNING: .env not found; scheduler will run with defaults and no external API keys"
fi
mkdir -p logs alpha_lab/data paper_trader/logs
exec .venv/bin/python -m alpha_lab.scheduler >> logs/scheduler.log 2>&1
