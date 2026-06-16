#!/bin/zsh
#
# verify_old_mac_runtime.sh — post-deploy runtime check, run ON the OLD MAC
# (the production server) from inside ~/AlphaLab:
#
#   cd ~/AlphaLab && ./scripts/verify_old_mac_runtime.sh
#
# It confirms the deployed code, environment, database, launchd agents, and the
# read-only report/diagnostic commands are all wired to the SAME database and
# working. It is read-only except for ONE scanner_runs smoke row written via the
# documented runtime diagnostics path (proves the DB is writable end-to-end).
#
# It NEVER prints secret values — only whether a key/user-agent is present. No
# trades are placed and no Alpaca order endpoints are touched.
#
# Exit code: 0 if all hard checks pass, 1 otherwise (safe to use as a gate).

set -u
emulate -L zsh
setopt pipefail

PROJECT_DIR="$HOME/AlphaLab"
PY="$PROJECT_DIR/.venv/bin/python"
PORT="${ALPHALAB_PORT:-8787}"
EXPECTED_JOBS="${ALPHALAB_EXPECTED_JOBS:-17}"
UID_NUM="$(id -u)"
DASHBOARD_LABEL="com.alphalab.dashboard"
SCHEDULER_LABEL="com.alphalab.scheduler"

FAILS=0
ok()   { print -P "%F{green}[OK]%f   $*"; }
warn() { print -P "%F{yellow}[WARN]%f $*"; }
err()  { print -P "%F{red}[FAIL]%f $*"; FAILS=$((FAILS+1)); }
step() { print -P "\n%F{cyan}== $* ==%f"; }

# --- 1. Location + interpreter ---------------------------------------------
step "Location + interpreter"
if [ "$PWD" = "$PROJECT_DIR" ]; then
  ok "current path is $PROJECT_DIR"
else
  err "run this from $PROJECT_DIR (currently in $PWD)"
fi
if [ -x "$PY" ]; then
  ok "venv python: $("$PY" --version 2>&1)"
else
  err "venv python missing at $PY — run scripts/setup_old_mac.sh"
  print "Cannot continue without the venv."; exit 1
fi

# --- 2. .env: presence, permissions, required key NAMES --------------------
step ".env file + required variables"
if [ -f "$PROJECT_DIR/.env" ]; then
  ok ".env exists"
  PERM="$(stat -f '%Lp' "$PROJECT_DIR/.env" 2>/dev/null)"
  if [ "$PERM" = "600" ]; then
    ok ".env permissions are 600 (owner-only)"
  else
    err ".env permissions are ${PERM:-unknown}, expected 600 — fix: chmod 600 .env"
  fi
  # Source in a SUBSHELL only to test presence; never echo a value.
  set -a; source "$PROJECT_DIR/.env"; set +a
  [ -n "${POLYGON_API_KEY:-}" ] && ok "POLYGON_API_KEY is present (value hidden)" || err "POLYGON_API_KEY is not set"
  [ -n "${SEC_USER_AGENT:-}" ]  && ok "SEC_USER_AGENT is present (value hidden)"  || err "SEC_USER_AGENT is not set"
  MODE="${ALPHALAB_SCHEDULER_MODE:-dry_run}"
  if [ "$MODE" = "dry_run" ]; then
    ok "ALPHALAB_SCHEDULER_MODE=dry_run (no live/paper orders)"
  else
    warn "ALPHALAB_SCHEDULER_MODE=$MODE (NOT dry_run — confirm this is intentional)"
  fi
else
  err ".env not found at $PROJECT_DIR/.env"
fi

# --- 3. Database: resolved path exists and is writable ---------------------
step "Database path"
DB_PATH="$("$PY" - <<'PY'
from pathlib import Path
from alpha_lab.database import resolve_db_path
# Absolute so it matches runtime_diagnostics' resolved db_path exactly.
print(Path(resolve_db_path()).expanduser().resolve())
PY
)"
if [ -n "$DB_PATH" ]; then
  print "  resolved DB path: $DB_PATH"
  DB_DIR="$(dirname "$DB_PATH")"
  if [ -f "$DB_PATH" ] && [ -w "$DB_PATH" ]; then
    ok "DB file exists and is writable"
  elif [ -d "$DB_DIR" ] && [ -w "$DB_DIR" ]; then
    ok "DB dir exists and is writable (file will be created on first write)"
  else
    err "DB path is not writable: $DB_PATH"
  fi
else
  err "could not resolve DB path"
fi

# --- 4. Runtime diagnostics ------------------------------------------------
step "Runtime diagnostics"
if "$PY" -m alpha_lab.runtime_diagnostics >/tmp/alphalab_diag.json 2>/tmp/alphalab_diag.err; then
  ok "runtime diagnostics passed"
  DIAG_DB="$("$PY" -c "import json;print(json.load(open('/tmp/alphalab_diag.json'))['db_path'])" 2>/dev/null)"
  [ "$DIAG_DB" = "$DB_PATH" ] && ok "diagnostics DB path matches resolver ($DIAG_DB)" \
    || warn "diagnostics DB path ($DIAG_DB) differs from resolver ($DB_PATH)"
else
  err "runtime diagnostics failed (see /tmp/alphalab_diag.err)"
fi

# --- 5. launchd agents ------------------------------------------------------
step "launchd agents"
for LABEL in "$DASHBOARD_LABEL" "$SCHEDULER_LABEL"; do
  STATE="$(launchctl print "gui/${UID_NUM}/${LABEL}" 2>/dev/null | awk -F'= ' '/state =/{print $2; exit}')"
  if [ -n "$STATE" ]; then
    ok "agent ${LABEL} loaded (state: $STATE)"
  else
    err "agent ${LABEL} not loaded — run scripts/setup_old_mac.sh"
  fi
done

# --- 6. Scheduler job count -------------------------------------------------
step "Scheduler job count"
JOBS="$("$PY" -c "import json;print(json.load(open('/tmp/alphalab_diag.json'))['scheduler_job_count'])" 2>/dev/null)"
if [ -n "$JOBS" ]; then
  if [ "$JOBS" = "$EXPECTED_JOBS" ]; then
    ok "scheduler has $JOBS jobs (expected $EXPECTED_JOBS, incl. futures + options preview)"
  else
    warn "scheduler has $JOBS jobs (expected $EXPECTED_JOBS) — verify the job set"
  fi
else
  warn "could not read scheduler job count from diagnostics"
fi

# --- 7. Dashboard listening on loopback ------------------------------------
step "Dashboard bind (127.0.0.1:${PORT})"
LISTEN="$(lsof -nP -iTCP:"${PORT}" -sTCP:LISTEN 2>/dev/null)"
if print -r -- "$LISTEN" | grep -q "127.0.0.1:${PORT}"; then
  ok "dashboard is listening on 127.0.0.1:${PORT} (loopback only)"
elif print -r -- "$LISTEN" | grep -q "\*:${PORT}"; then
  err "port ${PORT} is bound to ALL interfaces (*), expected 127.0.0.1 only"
else
  warn "nothing listening on 127.0.0.1:${PORT} yet (dashboard may be starting — check logs/dashboard.err.log)"
fi

# --- 8. scanner_runs write smoke test (the one write) ----------------------
step "scanner_runs write smoke test"
if "$PY" -m alpha_lab.runtime_diagnostics --write-smoke-test --scheduler-label "$SCHEDULER_LABEL" \
     >/tmp/alphalab_smoke.json 2>/tmp/alphalab_smoke.err; then
  ROWID="$("$PY" -c "import json;print(json.load(open('/tmp/alphalab_smoke.json')).get('smoke_test_scanner_run_id',''))" 2>/dev/null)"
  ok "wrote scanner_runs smoke row (id=${ROWID:-?}) to $DB_PATH"
else
  err "scanner_runs smoke write failed (see /tmp/alphalab_smoke.err)"
fi

# --- 9. Report commands run -------------------------------------------------
step "Report commands"
if "$PY" -m alpha_lab.source_coverage_report --date today >/tmp/alphalab_cov.out 2>&1; then
  ok "source_coverage_report ran"
else
  err "source_coverage_report failed (see /tmp/alphalab_cov.out)"
fi
if "$PY" -m alpha_lab.daily_activity_report --date today >/tmp/alphalab_act.out 2>&1; then
  ok "daily_activity_report ran"
else
  err "daily_activity_report failed (see /tmp/alphalab_act.out)"
fi

# --- Summary ---------------------------------------------------------------
step "Summary"
if [ "$FAILS" -eq 0 ]; then
  print -P "%F{green}All hard checks passed.%f Next: python -m alpha_lab.source_smoke_test"
  exit 0
else
  print -P "%F{red}${FAILS} check(s) failed.%f Resolve the items above, then re-run."
  exit 1
fi
