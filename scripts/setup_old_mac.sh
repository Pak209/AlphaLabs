#!/bin/zsh
#
# setup_old_mac.sh — one-time (and safely re-runnable) setup for the OLD MacBook,
# the always-on AlphaLab runner. Run this ON the old Mac after the first deploy.
#
#   ssh you@old-macbook.local         # or sit at the machine
#   cd ~/AlphaLab && ./scripts/setup_old_mac.sh
#
# What it does:
#   1. Verifies a standalone Python (not Xcode's) and rebuilds the venv.
#   2. Creates runtime dirs and locks down .env permissions.
#   3. Installs + loads the launchd schedule (renders the plist template).
#   4. Applies power settings: no sleep on AC, auto-restart after power loss.
#   5. Prints a verification summary.
#
# It is idempotent: re-running only fixes whatever drifted. Paper-only throughout.

set -u
emulate -L zsh
setopt pipefail

PROJECT_DIR="$HOME/AlphaLab"
UID_NUM="$(id -u)"
# launchd agents installed on the production Mac. dashboard + scheduler are the
# always-on services; options-validation is the weekday validator. Each has a
# deploy/<label>.plist.template rendered with $HOME and bootstrapped below.
AGENTS=(
  com.alphalab.dashboard
  com.alphalab.scheduler
  com.alphalab.options-validation
)

ok()   { print -P "%F{green}[OK]%f   $*"; }
warn() { print -P "%F{yellow}[WARN]%f $*"; }
err()  { print -P "%F{red}[FAIL]%f $*"; }
step() { print -P "\n%F{cyan}== $* ==%f"; }

cd "$PROJECT_DIR" || { err "project not found at $PROJECT_DIR (deploy it first)"; exit 1; }
ok "project dir: $PROJECT_DIR"

# --- 1. Python + venv -------------------------------------------------------
step "Python + virtualenv"
PY="$(command -v python3 || true)"
if [ -z "$PY" ]; then
  err "no python3 on PATH. Install one from https://www.python.org/downloads/macos/ (recommended) or 'brew install python', then re-run."
  exit 1
fi
case "$PY" in
  /Applications/Xcode.app/*|/Library/Developer/*)
    warn "python3 resolves to Xcode/Command-Line-Tools ($PY)."
    warn "A dedicated server should not depend on Xcode. Prefer the python.org installer, then re-run."
    ;;
  *) ok "python3: $PY ($("$PY" --version 2>&1))" ;;
esac

if [ ! -x ".venv/bin/python" ]; then
  print "Creating virtualenv (.venv)…"
  "$PY" -m venv .venv || { err "venv creation failed"; exit 1; }
  ok "created .venv"
else
  ok ".venv already present"
fi
print "Installing dependencies…"
.venv/bin/python -m pip install --quiet --upgrade pip >/dev/null 2>&1 || true
if .venv/bin/python -m pip install --quiet -r requirements.txt; then
  ok "dependencies installed (requirements.txt)"
else
  err "pip install failed"; exit 1
fi

# --- 2. Runtime dirs + secrets ---------------------------------------------
step "Runtime dirs + .env"
mkdir -p logs alpha_lab/data paper_trader/logs
ok "ensured logs/, alpha_lab/data/, paper_trader/logs/"

if [ -f ".env" ]; then
  chmod 600 .env
  ok ".env present, permissions locked to 600 (owner-only)"
else
  if [ -f ".env.example" ]; then
    cp .env.example .env && chmod 600 .env
    warn "no .env found — copied .env.example to .env. EDIT IT with your Alpaca/Polygon keys before the first scheduled run."
  else
    warn "no .env and no .env.example — create ~/AlphaLab/.env with your keys (chmod 600)."
  fi
fi

# --- 3. launchd agents ------------------------------------------------------
step "launchd agents (dashboard + scheduler + validator)"
mkdir -p "$HOME/Library/LaunchAgents"
for LABEL in "${AGENTS[@]}"; do
  PLIST_TPL="$PROJECT_DIR/deploy/${LABEL}.plist.template"
  PLIST_DST="$HOME/Library/LaunchAgents/${LABEL}.plist"
  if [ ! -f "$PLIST_TPL" ]; then
    err "plist template missing: $PLIST_TPL — skipping ${LABEL}"
    continue
  fi
  # Render __HOME__ -> $HOME so the agent uses THIS machine's home dir, not the
  # dev Mac's. Reload cleanly (bootout is harmless if not currently loaded).
  sed "s|__HOME__|$HOME|g" "$PLIST_TPL" > "$PLIST_DST"
  launchctl bootout "gui/${UID_NUM}/${LABEL}" 2>/dev/null || true
  if launchctl bootstrap "gui/${UID_NUM}" "$PLIST_DST" 2>/dev/null; then
    ok "loaded LaunchAgent ${LABEL}"
  else
    err "launchctl bootstrap failed for ${LABEL} — check $PLIST_DST"
  fi
done

TZNAME="$(readlink /etc/localtime | sed 's|.*/zoneinfo/||')"
if [ "$TZNAME" = "America/Los_Angeles" ]; then
  ok "timezone is $TZNAME (06:32 local = ~09:32 ET market open)"
else
  warn "timezone is $TZNAME, not America/Los_Angeles — the 06:32 schedule will NOT line up with the market open. Set it in System Settings > General > Date & Time."
fi

# --- 4. Power / always-on ---------------------------------------------------
step "Power settings (needs admin password)"
print "Applying: no system sleep on AC, auto-restart after power loss, wake on network."
if sudo pmset -c sleep 0 autorestart 1 womp 1 && sudo pmset -a disablesleep 1; then
  ok "power settings applied (lid may stay closed without sleeping)"
else
  warn "could not set pmset (skipped or no sudo). Apply manually:"
  warn "  sudo pmset -c sleep 0 autorestart 1 womp 1 && sudo pmset -a disablesleep 1"
fi

# --- 5. Verify --------------------------------------------------------------
step "Verification"
.venv/bin/python -c "import fastapi, pydantic" 2>/dev/null \
  && ok "venv imports core deps" || warn "venv missing deps — re-run after fixing pip"

for LABEL in "${AGENTS[@]}"; do
  STATE="$(launchctl print "gui/${UID_NUM}/${LABEL}" 2>/dev/null | awk -F'= ' '/state =/{print $2; exit}')"
  [ -n "$STATE" ] && ok "agent ${LABEL}: $STATE" || warn "agent ${LABEL}: not found in launchd"
done

print "\nDry inspection of the full chain (market may be closed → expected):"
./scripts/run_options_validation.sh --allow-closed 2>&1 | tail -n 12

print "\nRun the full runtime check next:"
print "  ./scripts/verify_old_mac_runtime.sh"
print -P "\n%F{green}Setup complete.%f Keep this Mac plugged in and on the network."
print "Dashboard binds 127.0.0.1:8787; scheduler runs in dry_run unless .env says otherwise."
