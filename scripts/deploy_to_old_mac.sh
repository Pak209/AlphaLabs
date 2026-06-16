#!/bin/zsh
#
# deploy_to_old_mac.sh — push code from the NEW MacBook (source of truth) to the
# OLD MacBook (runner) over SSH with rsync. Run this ON the new Mac.
#
#   ./scripts/deploy_to_old_mac.sh            # preview, then confirm, then sync
#   ./scripts/deploy_to_old_mac.sh --dry-run  # preview only, change nothing
#   ./scripts/deploy_to_old_mac.sh --yes      # skip the confirm prompt
#
# It NEVER touches server-only state: .env, the venv, logs, and the SQLite DB are
# excluded, so the old Mac keeps its own secrets, environment, and trade history.
# --delete is used so files you remove on the dev Mac also disappear on the server
# (within the synced code only — excluded paths are protected from deletion).

set -u
emulate -L zsh
setopt pipefail

SCRIPT_DIR="${0:A:h}"
CONF="$SCRIPT_DIR/server.conf"

ok()   { print -P "%F{green}[OK]%f   $*"; }
warn() { print -P "%F{yellow}[WARN]%f $*"; }
err()  { print -P "%F{red}[FAIL]%f $*"; }

if [ ! -f "$CONF" ]; then
  err "missing $CONF"
  print "Create it once:  cp scripts/server.conf.example scripts/server.conf  (then edit host/user)"
  exit 1
fi
source "$CONF"
: "${SERVER_USER:?set SERVER_USER in server.conf}"
: "${SERVER_HOST:?set SERVER_HOST in server.conf}"
: "${REMOTE_PATH:=AlphaLab}"

DRY_RUN=0
ASSUME_YES=0
for arg in "$@"; do
  case "$arg" in
    --dry-run|-n) DRY_RUN=1 ;;
    --yes|-y)     ASSUME_YES=1 ;;
    *) warn "ignoring unknown arg: $arg" ;;
  esac
done

LOCAL_DIR="${SCRIPT_DIR:h}/"            # ~/AlphaLab/ (trailing slash = copy contents)
REMOTE="${SERVER_USER}@${SERVER_HOST}:${REMOTE_PATH}/"

# Things that live ONLY on the server, or are machine-local junk.
# NOTE: --delete is in effect, so anything NOT excluded that is absent on the dev
# Mac gets DELETED on the server. The blocks below protect server-only RUNTIME
# state (DB, paper-trade history, generated reports) from being wiped on deploy.
EXCLUDES=(
  # Per-machine build/runtime junk and the server's own virtualenv.
  --exclude='.venv/'
  --exclude='__pycache__/'
  --exclude='*.pyc'
  --exclude='.git/'
  --exclude='.DS_Store'
  --exclude='*.tmp'
  --exclude='.pytest_cache/'
  # Secrets + connection config: the server keeps its OWN protected .env.
  --exclude='.env'
  --exclude='scripts/server.conf'
  # Logs are server-local and grow there; never push or delete them.
  --exclude='logs/'
  # SQLite database + WAL/journal sidecars: the server's trade/idea history.
  --exclude='*.sqlite3'
  --exclude='*.sqlite3-*'
  # The whole runtime data dir (DB, audit.jsonl, *.log) is server-owned state.
  # Excluding the dir (not just *.log) keeps the paper-trade audit log alive
  # across deploys instead of being removed by --delete.
  --exclude='alpha_lab/data/'
  # Generated report output: the server writes its own daily/coverage reports.
  --exclude='reports/'
  # Paper-trader runtime queues, generated orders, logs, and reports — all
  # server-side state produced by the scheduler's inbox processing.
  --exclude='paper_trader/inbox/'
  --exclude='paper_trader/processed/'
  --exclude='paper_trader/rejected/'
  --exclude='paper_trader/generated/'
  --exclude='paper_trader/reports/'
  --exclude='paper_trader/logs/'
)

print "Deploy plan:"
print "  from: $LOCAL_DIR"
print "  to:   $REMOTE"
print "  mode: rsync --archive --delete (excludes: venv, pycache, .git, logs, db,"
print "        .env, alpha_lab/data, reports, paper_trader runtime queues)"

# 1) Always preview first.
print "\n--- preview (no changes) ---"
if ! rsync -az --delete --itemize-changes --dry-run "${EXCLUDES[@]}" "$LOCAL_DIR" "$REMOTE"; then
  err "rsync preview failed — is the old Mac reachable and Remote Login enabled?"
  err "test with:  ssh ${SERVER_USER}@${SERVER_HOST} 'echo ok'"
  exit 1
fi

if [ "$DRY_RUN" -eq 1 ]; then
  ok "dry-run only; nothing was changed."
  exit 0
fi

# 2) Confirm unless --yes.
if [ "$ASSUME_YES" -eq 0 ]; then
  print ""
  read "REPLY?Apply these changes to the server? [y/N] "
  case "$REPLY" in
    y|Y|yes|YES) ;;
    *) warn "aborted; nothing changed."; exit 0 ;;
  esac
fi

# 3) Real sync.
print "\n--- deploying ---"
if rsync -az --delete --itemize-changes "${EXCLUDES[@]}" "$LOCAL_DIR" "$REMOTE"; then
  ok "code synced to ${SERVER_HOST}."
  print "Note: Python/code changes take effect on the next scheduled run automatically."
  print "      If you changed the launchd schedule (the plist template), re-run"
  print "      setup_old_mac.sh on the server to reload it."
else
  err "rsync failed."
  exit 1
fi
