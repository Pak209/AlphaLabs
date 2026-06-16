#!/bin/zsh
#
# check_old_mac.sh — one-glance health check of the OLD MacBook runner, from the
# NEW Mac. Confirms it's reachable, the schedule is loaded, power settings are
# right, and shows the most recent run. Read-only: changes nothing.
#
#   ./scripts/check_old_mac.sh           # status summary
#   ./scripts/check_old_mac.sh --logs    # also print the tail of the last run log

set -u
emulate -L zsh
setopt pipefail

SCRIPT_DIR="${0:A:h}"
CONF="$SCRIPT_DIR/server.conf"
LABEL="com.alphalab.options-validation"

ok()   { print -P "%F{green}[OK]%f   $*"; }
warn() { print -P "%F{yellow}[WARN]%f $*"; }
err()  { print -P "%F{red}[FAIL]%f $*"; }

if [ ! -f "$CONF" ]; then
  err "missing $CONF — run: cp scripts/server.conf.example scripts/server.conf (then edit)"
  exit 1
fi
source "$CONF"
: "${SERVER_USER:?set SERVER_USER in server.conf}"
: "${SERVER_HOST:?set SERVER_HOST in server.conf}"
: "${REMOTE_PATH:=AlphaLab}"

SHOW_LOGS=0
[ "${1:-}" = "--logs" ] && SHOW_LOGS=1

TARGET="${SERVER_USER}@${SERVER_HOST}"
print -P "%F{cyan}== AlphaLab server check: $TARGET ==%f"

# Single SSH session runs a small report remotely and streams it back.
# (Connect timeout keeps a dead host from hanging the terminal.)
REMOTE_REPORT='
LABEL="'"$LABEL"'"
PROJ="$HOME/'"$REMOTE_PATH"'"
UIDN="$(id -u)"
echo "HOST $(hostname) | up $(uptime | sed "s/.*up //; s/,.*users.*//")"
echo "TIME $(date "+%Y-%m-%d %H:%M:%S %Z")"
TZN="$(readlink /etc/localtime | sed "s|.*/zoneinfo/||")"
echo "TZ $TZN"
STATE="$(launchctl print gui/$UIDN/$LABEL 2>/dev/null | awk -F"= " "/state =/{print \$2; exit}")"
echo "AGENT ${STATE:-NOT_LOADED}"
echo "SLEEP $(pmset -g | awk "/ sleep /{print \$2; exit}")"
echo "DISABLESLEEP $(pmset -g | awk "/disablesleep/{print \$2; exit}")"
echo "AUTORESTART $(pmset -g | awk "/autorestart/{print \$2; exit}")"
if [ -x "$PROJ/.venv/bin/python" ]; then
  echo "VENV $($PROJ/.venv/bin/python --version 2>&1)"
else
  echo "VENV MISSING"
fi
LAST="$(ls -t $PROJ/logs/options_validation_*.log 2>/dev/null | head -1)"
if [ -n "$LAST" ]; then
  echo "LASTLOG $LAST"
  echo "LASTEND $(grep "RUN END" "$LAST" | tail -1 | sed "s/RUN END:[[:space:]]*//")"
  echo "RUNCOUNT $(ls $PROJ/logs/options_validation_*.log 2>/dev/null | wc -l | tr -d " ")"
else
  echo "LASTLOG NONE"
fi
'

REPORT="$(ssh -o ConnectTimeout=8 -o BatchMode=no "$TARGET" "$REMOTE_REPORT" 2>/dev/null)" || {
  err "cannot reach $TARGET over SSH."
  print "  - Is the old Mac awake and on the network?"
  print "  - Is Remote Login on? (System Settings > General > Sharing > Remote Login)"
  print "  - Try: ssh $TARGET 'echo ok'"
  exit 1
}
ok "reachable over SSH"

# Parse the report into friendly lines.
get() { print -r -- "$REPORT" | awk -v k="$1" '$1==k{$1="";sub(/^ /,"");print;exit}'; }

print "  host:        $(get HOST)"
print "  time:        $(get TIME)"

TZV="$(get TZ)"
if [ "$TZV" = "America/Los_Angeles" ]; then ok "timezone:    $TZV"; else warn "timezone:    $TZV (schedule expects America/Los_Angeles)"; fi

AG="$(get AGENT)"
if [ "$AG" = "running" ] || [ "$AG" = "waiting" ]; then ok "schedule:    loaded ($AG)"; else warn "schedule:    $AG"; fi

SL="$(get SLEEP)"; DS="$(get DISABLESLEEP)"; AR="$(get AUTORESTART)"
if [ "$SL" = "0" ] || [ "$DS" = "1" ]; then ok "sleep:       won't sleep on AC (sleep=$SL disablesleep=$DS)"; else warn "sleep:       may sleep (sleep=$SL disablesleep=$DS) — re-run setup_old_mac.sh"; fi
if [ "$AR" = "1" ]; then ok "power-loss:  auto-restart ON"; else warn "power-loss:  auto-restart OFF (set: sudo pmset -c autorestart 1)"; fi

VV="$(get VENV)"
[ "$VV" = "MISSING" ] && warn "venv:        MISSING — run setup_old_mac.sh on the server" || ok "venv:        $VV"

LL="$(get LASTLOG)"
if [ "$LL" = "NONE" ]; then
  warn "last run:    none yet (runs weekdays 06:32 local)"
else
  print "  last log:    $LL"
  print "  last end:    $(get LASTEND)"
  print "  total runs:  $(get RUNCOUNT)"
fi

if [ "$SHOW_LOGS" -eq 1 ] && [ "$LL" != "NONE" ]; then
  print -P "\n%F{cyan}== tail of last run log ==%f"
  ssh -o ConnectTimeout=8 "$TARGET" "tail -n 25 '$LL'" 2>/dev/null
fi
