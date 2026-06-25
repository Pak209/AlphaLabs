#!/bin/zsh
#
# verify_server_runtime.sh — canonical post-deploy runtime check for the AlphaLabs
# SERVER (the Mac mini, dans-mac-mini). Run ON the server from inside ~/AlphaLab:
#
#   cd ~/AlphaLab && ./scripts/verify_server_runtime.sh
#
# This is a thin, forward-named wrapper around scripts/verify_old_mac_runtime.sh
# (the original, server-agnostic verifier) so existing tooling that still calls the
# legacy name keeps working unchanged. All validation logic lives in that script:
#   .env perms · required env vars · DB path · scheduler heartbeat · dashboard
#   health · safety posture · scheduler job count · API endpoints · source-coverage
#   and daily-activity reports.
#
# Exit code is passed through (0 = all hard checks passed, 1 = something failed),
# so it is safe to use as a deploy gate.

set -u
emulate -L zsh
setopt pipefail

HERE="${0:A:h}"
LEGACY="$HERE/verify_old_mac_runtime.sh"

if [ ! -x "$LEGACY" ]; then
  print -P "%F{red}[FAIL]%f missing or non-executable verifier: $LEGACY"
  exit 1
fi

print -P "%F{cyan}== AlphaLabs server runtime verification (Mac mini / dans-mac-mini) ==%f"
exec "$LEGACY" "$@"
