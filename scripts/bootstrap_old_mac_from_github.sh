#!/bin/zsh
#
# Bootstrap/update AlphaLabs on the old Mac from GitHub.
#
# Run ON the old Mac:
#   /bin/zsh -c "$(curl -fsSL https://raw.githubusercontent.com/Pak209/AlphaLabs/main/scripts/bootstrap_old_mac_from_github.sh)"
#
# Or, after the repo exists:
#   cd ~/AlphaLab && ./scripts/bootstrap_old_mac_from_github.sh
#
# This script never overwrites .env, alpha_lab/data/, logs/, or local server
# config. It refuses to update a dirty checkout so local runtime state is not
# accidentally folded into Git operations.

set -u
emulate -L zsh
setopt pipefail

REPO_URL="${ALPHALAB_REPO_URL:-https://github.com/Pak209/AlphaLabs.git}"
PROJECT_DIR="${ALPHALAB_PROJECT_DIR:-$HOME/Projects/AlphaLab}"
BRANCH="${ALPHALAB_BRANCH:-main}"

ok()   { print -P "%F{green}[OK]%f   $*"; }
warn() { print -P "%F{yellow}[WARN]%f $*"; }
err()  { print -P "%F{red}[FAIL]%f $*"; }
step() { print -P "\n%F{cyan}== $* ==%f"; }

step "Prerequisites"
if ! command -v git >/dev/null 2>&1; then
  err "git is not installed. Install Xcode Command Line Tools with: xcode-select --install"
  exit 1
fi
ok "git: $(git --version)"

PY="$(command -v python3 || true)"
if [ -z "$PY" ]; then
  err "python3 is not on PATH. Install python.org Python or Homebrew Python, then re-run."
  exit 1
fi
ok "python3: $("$PY" --version 2>&1)"

step "Git checkout"
if [ ! -d "$PROJECT_DIR" ]; then
  mkdir -p "$(dirname "$PROJECT_DIR")"
  git clone "$REPO_URL" "$PROJECT_DIR" || { err "git clone failed"; exit 1; }
  ok "cloned $REPO_URL into $PROJECT_DIR"
fi

cd "$PROJECT_DIR" || { err "cannot cd to $PROJECT_DIR"; exit 1; }

if [ ! -d ".git" ]; then
  err "$PROJECT_DIR exists but is not a Git checkout. Move it aside or back it up, then clone from $REPO_URL."
  exit 1
fi

CURRENT_ORIGIN="$(git remote get-url origin 2>/dev/null || true)"
if [ -z "$CURRENT_ORIGIN" ]; then
  git remote add origin "$REPO_URL"
  ok "added origin $REPO_URL"
elif [ "$CURRENT_ORIGIN" != "$REPO_URL" ]; then
  warn "origin is $CURRENT_ORIGIN, expected $REPO_URL"
  warn "leaving origin unchanged; fix manually if this is not intentional."
else
  ok "origin: $CURRENT_ORIGIN"
fi

if [ -n "$(git status --porcelain)" ]; then
  err "checkout has uncommitted source changes. Refusing to pull."
  print "Review with: git status --short"
  print "Runtime files such as .env, alpha_lab/data/, logs/, reports/ should be ignored and are safe to leave local."
  exit 1
fi

git fetch origin "$BRANCH" || { err "git fetch failed"; exit 1; }
git checkout "$BRANCH" || { err "git checkout $BRANCH failed"; exit 1; }
git pull --ff-only origin "$BRANCH" || { err "git pull --ff-only failed"; exit 1; }
ok "checkout at $(git rev-parse --short HEAD) on $BRANCH"

step "Python virtualenv"
if [ ! -x ".venv/bin/python" ]; then
  "$PY" -m venv .venv || { err "venv creation failed"; exit 1; }
  ok "created .venv"
else
  ok ".venv already exists"
fi
.venv/bin/python -m pip install --quiet --upgrade pip >/dev/null 2>&1 || true
.venv/bin/python -m pip install --quiet -r requirements.txt || { err "dependency install failed"; exit 1; }
ok "requirements installed"

step "Runtime directories and local config"
mkdir -p logs alpha_lab/data paper_trader/logs paper_trader/inbox paper_trader/processed paper_trader/rejected paper_trader/generated
ok "runtime dirs exist"

if [ -f ".env" ]; then
  chmod 600 .env 2>/dev/null || true
  ok ".env exists and was left in place"
else
  warn ".env is missing. Create it manually from .env.example, fill real values on this Mac, then chmod 600 .env."
  warn "Do not commit or paste secrets into chat."
fi

step "Local DB diagnostics"
if .venv/bin/python -m alpha_lab.db_status --json >/tmp/alphalab_db_status.json 2>/tmp/alphalab_db_status.err; then
  ok "db_status ran; see /tmp/alphalab_db_status.json"
else
  warn "db_status could not find an active DB yet. This is normal before first startup; see /tmp/alphalab_db_status.err"
fi

step "Next steps"
print "1. Edit ~/AlphaLab/.env on the old Mac if needed; keep ALPHA_LAB_DB_PATH old-Mac-local."
print "2. Run: cd ~/AlphaLab && ./scripts/setup_old_mac.sh"
print "3. Verify: cd ~/AlphaLab && ./scripts/verify_old_mac_runtime.sh"
print "4. Dashboard local URL: http://127.0.0.1:8787/"
print ""
print "Rollback note:"
print "  cp alpha_lab/data/alpha_lab.sqlite3 alpha_lab/data/alpha_lab.sqlite3.before-rollback-$(date +%Y%m%d%H%M%S) 2>/dev/null || true"
print "  git log --oneline -5"
print "  git checkout <previous_commit>"
print "  .venv/bin/python -m pip install -r requirements.txt"
print "  launchctl kickstart -k gui/$(id -u)/com.alphalab.dashboard"
print "  launchctl kickstart -k gui/$(id -u)/com.alphalab.scheduler"
