#!/bin/bash
# deploy_mini.sh — one-command deploy for the Mac mini.
#
#   merge PR on GitHub  ->  ./scripts/deploy_mini.sh
#
# Does exactly one thing, safely: fast-forward main to origin/main, restart the
# dashboard + scheduler LaunchAgents, and run the post-deploy verification the
# engineering handbook requires. Refuses to run under any ambiguity:
#   - not on main                      -> abort (deploys ship main only)
#   - tracked files modified/staged    -> abort (never clobber local work)
#   - pull is not a clean fast-forward -> abort (never merge/rebase implicitly)
# Untracked files are tolerated (runtime data dirs live in the tree).
set -euo pipefail

REPO="/Users/pak/Projects/AlphaLab"
cd "$REPO"

say()  { printf '\033[1m%s\033[0m\n' "$*"; }
fail() { printf '\033[31mDEPLOY ABORTED: %s\033[0m\n' "$*" >&2; exit 1; }

branch=$(git rev-parse --abbrev-ref HEAD)
[ "$branch" = "main" ] || fail "on branch '$branch' — deploys run from main (git switch main first)"

git update-index -q --refresh
# The handoff journal is an append-only operational log that every agent
# updates between commits; a dirty journal never affects the deployed code,
# so it must not block a deploy. Everything else still must be clean.
dirty=$(git diff-index --name-only HEAD -- | grep -v "^\.ai/LEX_REVIEW_HANDOFF\.md$" || true)
[ -z "$dirty" ] || fail "tracked files are modified — commit or stash before deploying: $dirty"
[ -z "$(git diff --cached --name-only)" ] || fail "staged changes present"

say "Fetching origin..."
git fetch origin --prune
before=$(git rev-parse --short HEAD)
target=$(git rev-parse --short origin/main)

if [ "$before" = "$target" ]; then
  say "Already at origin/main ($before) — restarting services anyway."
else
  git merge-base --is-ancestor HEAD origin/main \
    || fail "local main has diverged from origin/main — resolve manually"
  say "Fast-forwarding $before -> $target"
  git merge --ff-only origin/main
fi

say "Restarting agents..."
uid=$(id -u)
launchctl kickstart -k "gui/$uid/com.alphalab.scheduler"
launchctl kickstart -k "gui/$uid/com.alphalab.dashboard"
# intel-api is optional (only present once the Track-3 agent is installed)
launchctl kickstart -k "gui/$uid/com.alphalab.intel-api" 2>/dev/null || true

say "Waiting for the dashboard to come up..."
for i in $(seq 1 15); do
  sleep 2
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 http://127.0.0.1:8787/api/health || true)
  [ "$code" = "200" ] && break
done
[ "$code" = "200" ] || fail "dashboard health check did not return 200 after restart"

say "Health: dashboard 200. Safety status:"
curl -s http://127.0.0.1:8787/api/safety-status; echo

say "Post-deploy verification (diagnose_trading_pipeline):"
"$REPO/.venv/bin/python" "$REPO/scripts/diagnose_trading_pipeline.py" 2>/dev/null \
  | sed -n '1,12p' || printf 'WARN: diagnose script did not complete cleanly — investigate\n'

say "Deployed: $(git rev-parse --short HEAD) ($(git log -1 --format=%s | head -c 70))"
say "Scheduler + dashboard PIDs:"
launchctl list | grep -E "com.alphalab.(scheduler|dashboard)$" || true
say "Done. Reminder: phone/browser may need a hard refresh (SW picks up new assets on second load)."
