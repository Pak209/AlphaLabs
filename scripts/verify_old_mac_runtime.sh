#!/bin/zsh
#
# verify_old_mac_runtime.sh — post-deploy runtime check, run ON the OLD MAC
# (the production server) from inside ~/AlphaLab:
#
#   cd ~/AlphaLab && ./scripts/verify_old_mac_runtime.sh
#
# It confirms the deployed code, environment, database, launchd agents, local API,
# Catalyst Intelligence endpoint, and read-only report/diagnostic commands are all
# wired to the SAME database and working. It is read-only except for ONE
# scanner_runs smoke row written via the documented runtime diagnostics path
# (proves the DB is writable end-to-end).
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
EXPECTED_JOBS="${ALPHALAB_EXPECTED_JOBS:-18}"
EXPECTED_COMMIT="${ALPHALAB_EXPECTED_COMMIT:-}"
UID_NUM="$(id -u)"
DASHBOARD_LABEL="com.alphalab.dashboard"
SCHEDULER_LABEL="com.alphalab.scheduler"

FAILS=0
ok()   { print -P "%F{green}[OK]%f   $*"; }
warn() { print -P "%F{yellow}[WARN]%f $*"; }
err()  { print -P "%F{red}[FAIL]%f $*"; FAILS=$((FAILS+1)); }
step() { print -P "\n%F{cyan}== $* ==%f"; }

http_code() {
  local URL="$1"
  local OUT="$2"
  curl -sS --max-time 12 -o "$OUT" -w "%{http_code}" "$URL" 2>/tmp/alphalab_curl.err || print "000"
}

check_http_200() {
  local URL="$1"
  local LABEL="$2"
  local OUT="$3"
  local CODE=""
  local I=0
  while [ "$I" -lt 5 ]; do
    CODE="$(http_code "$URL" "$OUT")"
    if [ "$CODE" = "200" ]; then
      ok "${LABEL} returned HTTP 200"
      return 0
    fi
    I=$((I+1))
    sleep 2
  done
  err "${LABEL} returned HTTP ${CODE:-unknown} for $URL"
  return 1
}

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

# --- 1b. Git checkout -------------------------------------------------------
step "Git checkout"
if [ -d "$PROJECT_DIR/.git" ]; then
  HEAD_HASH="$(git -C "$PROJECT_DIR" rev-parse HEAD 2>/dev/null || true)"
  BRANCH="$(git -C "$PROJECT_DIR" branch --show-current 2>/dev/null || true)"
  ORIGIN_URL="$(git -C "$PROJECT_DIR" remote get-url origin 2>/dev/null || true)"
  DIRTY="$(git -C "$PROJECT_DIR" status --porcelain 2>/dev/null | wc -l | tr -d ' ')"
  ok "commit: ${HEAD_HASH:-unknown}"
  ok "branch: ${BRANCH:-detached}"
  [ -n "$ORIGIN_URL" ] && ok "origin: $ORIGIN_URL" || warn "origin remote not configured"
  [ "$DIRTY" = "0" ] && ok "working tree clean" || warn "working tree has $DIRTY uncommitted source change(s)"
  if [ -n "$EXPECTED_COMMIT" ]; then
    if [ "$HEAD_HASH" = "$EXPECTED_COMMIT" ]; then
      ok "commit matches ALPHALAB_EXPECTED_COMMIT"
    else
      err "commit $HEAD_HASH does not match ALPHALAB_EXPECTED_COMMIT=$EXPECTED_COMMIT"
    fi
  fi
else
  err "$PROJECT_DIR is not a Git checkout. Clone https://github.com/Pak209/AlphaLabs.git into ~/AlphaLab."
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

if "$PY" -m alpha_lab.db_status --json >/tmp/alphalab_db_status.json 2>/tmp/alphalab_db_status.err; then
  ok "db_status command ran"
  DB_EXISTS="$("$PY" -c "import json;print(json.load(open('/tmp/alphalab_db_status.json')).get('db_exists'))" 2>/dev/null)"
  IDEAS_COUNT="$("$PY" -c "import json;print(json.load(open('/tmp/alphalab_db_status.json')).get('ideas_count'))" 2>/dev/null)"
  TRADES_COUNT="$("$PY" -c "import json;print(json.load(open('/tmp/alphalab_db_status.json')).get('trades_count'))" 2>/dev/null)"
  CATALYST_EVENTS_COUNT="$("$PY" -c "import json;print(json.load(open('/tmp/alphalab_db_status.json')).get('catalyst_events_count'))" 2>/dev/null)"
  HEARTBEAT_AT="$("$PY" -c "import json;print(json.load(open('/tmp/alphalab_db_status.json')).get('scheduler_heartbeat_at'))" 2>/dev/null)"
  if [ "$DB_EXISTS" = "True" ]; then
    ok "db_status confirms DB exists (ideas=${IDEAS_COUNT}, trades=${TRADES_COUNT}, catalyst_events=${CATALYST_EVENTS_COUNT})"
    if [ -n "$HEARTBEAT_AT" ] && [ "$HEARTBEAT_AT" != "None" ]; then
      ok "scheduler heartbeat at ${HEARTBEAT_AT}"
    else
      warn "no scheduler heartbeat recorded yet (scheduler not started?)"
    fi
  else
    err "db_status reports DB missing"
  fi
else
  err "db_status failed (see /tmp/alphalab_db_status.err)"
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
    ok "scheduler has $JOBS jobs (expected $EXPECTED_JOBS, incl. heartbeat + futures + options preview)"
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

# --- 7b. Local API and same-DB proof ----------------------------------------
# The whole point of the single-source-of-truth setup: the dashboard the phone /
# dev Mac talk to and the always-on scheduler must read+write the SAME file. We
# ask the live API for its resolved db_path (+inode) and compare to the resolver
# and to the db_path the scheduler stamped on its last heartbeat.
step "Local API and same-DB proof"
check_http_200 "http://127.0.0.1:${PORT}/api/health" "/api/health" /tmp/alphalab_api_health.json
check_http_200 "http://127.0.0.1:${PORT}/api/db-status" "/api/db-status" /tmp/alphalab_api_db_status.json
check_http_200 "http://127.0.0.1:${PORT}/api/catalysts/intelligence" "/api/catalysts/intelligence" /tmp/alphalab_api_catalysts.json

if [ -s /tmp/alphalab_api_db_status.json ]; then
  API_DB="$("$PY" -c "import json;print(json.load(open('/tmp/alphalab_api_db_status.json')).get('db_path',''))" 2>/dev/null)"
  if [ "$API_DB" = "$DB_PATH" ]; then
    ok "dashboard API db_path matches resolver ($API_DB)"
  else
    err "dashboard API db_path ($API_DB) != resolver ($DB_PATH) — split-brain DB!"
  fi
  "$PY" -m alpha_lab.db_status --json >/tmp/alphalab_db_status.json 2>/tmp/alphalab_db_status.err
  HB_AT="$("$PY" -c "import json;print(json.load(open('/tmp/alphalab_db_status.json')).get('scheduler_heartbeat_at') or '')" 2>/dev/null)"
  HB_DB="$("$PY" -c "import json;print(json.load(open('/tmp/alphalab_db_status.json')).get('scheduler_heartbeat_db_path') or '')" 2>/dev/null)"
  if [ -z "$HB_DB" ]; then
    err "no scheduler heartbeat recorded yet (scheduler stamps one at boot + every 5 min)"
  elif [ "$HB_DB" = "$DB_PATH" ]; then
    ok "scheduler heartbeat exists (${HB_AT:-unknown time}) and db_path matches resolver ($HB_DB)"
  else
    err "scheduler wrote a DIFFERENT db_path ($HB_DB) than the resolver ($DB_PATH) — split-brain DB!"
  fi
else
  warn "could not parse dashboard /api/db-status on 127.0.0.1:${PORT} (is the dashboard agent up?)"
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
if "$PY" -m alpha_lab.db_status >/tmp/alphalab_dbstatus.out 2>&1; then
  ok "db_status ran (active DB summary below)"
else
  warn "db_status reports the DB missing (expected only on a brand-new install)"
fi
sed 's/^/    /' /tmp/alphalab_dbstatus.out
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

# --- 10. Access URL hints ----------------------------------------------------
step "Access URL hints"
ok "local dashboard URL: http://127.0.0.1:${PORT}/"
LOCAL_HOST="$(scutil --get LocalHostName 2>/dev/null || hostname -s 2>/dev/null || true)"
if [ -n "$LOCAL_HOST" ]; then
  warn "dashboard binds loopback only, so http://${LOCAL_HOST}.local:${PORT}/ is not expected to work unless you add an SSH tunnel/proxy"
fi
if command -v tailscale >/dev/null 2>&1; then
  TS_IP="$(tailscale ip -4 2>/dev/null | head -n 1 || true)"
  if [ -n "$TS_IP" ]; then
    ok "Tailscale IPv4 detected: $TS_IP"
    warn "AlphaLabs still binds 127.0.0.1; use Tailscale Serve or an SSH tunnel for phone access."
  else
    warn "tailscale command exists, but no Tailscale IPv4 was detected"
  fi
  SERVE_STATUS="$(tailscale serve status 2>/dev/null || true)"
  if [ -n "$SERVE_STATUS" ]; then
    print "$SERVE_STATUS"
  else
    warn "no Tailscale Serve status detected"
  fi
else
  warn "tailscale command not found; LAN/Tailscale URL not detectable"
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
