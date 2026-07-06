#!/usr/bin/env bash
# Tailscale keepalive — ensures Tailscale stays connected during an active user session.
# Run by com.alphalab.tailscale-keepalive LaunchAgent (RunAtLoad + KeepAlive).
# NOT a substitute for tssentineld (which survives logout/reboot).
# Does not modify any AlphaLabs, CodexPro, or Cloudflare configuration.

TS="/Applications/Tailscale.app/Contents/MacOS/Tailscale"
LOG_TAG="tailscale-keepalive"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $LOG_TAG: $*"; }

if [ ! -x "$TS" ]; then
  log "ERROR: Tailscale binary not found at $TS"
  exit 1
fi

log "started (PID $$)"

while true; do
  STATUS=$("$TS" status --json 2>/dev/null | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('BackendState', 'unknown'))
except:
    print('error')
" 2>/dev/null)

  case "$STATUS" in
    Running)
      # Connected — sleep and check again
      sleep 30
      ;;
    Stopped|NeedsLogin|NeedsMachineAuth|unknown|error)
      log "state=$STATUS — running tailscale up"
      "$TS" up 2>&1 | sed "s/^/$(date '+%Y-%m-%d %H:%M:%S') $LOG_TAG: /"
      sleep 10
      ;;
    *)
      log "state=$STATUS — waiting"
      sleep 15
      ;;
  esac
done
