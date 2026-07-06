#!/bin/zsh
#
# Wrapper for the scheduled (launchd) paper options lifecycle validation.
#
# launchd starts jobs with a bare environment and no shell profile, so this
# script is responsible for: locating the project, loading .env (Alpaca keys,
# POLYGON, ALPHA_LAB_DB_PATH, automation flags), and invoking the validator
# under the project venv. Every run is logged to a timestamped file under logs/.
#
# Paper-only: the validator routes orders through AlpacaClient, which refuses any
# non-paper host. This wrapper adds no live-trading capability of its own.
#
# `caffeinate -i` holds off idle sleep for the duration of the run so a fill +
# close can complete even if the machine would otherwise nap.

set -u
PROJECT_DIR="$HOME/Projects/AlphaLab"
cd "$PROJECT_DIR" || { echo "FATAL: project dir not found: $PROJECT_DIR"; exit 1; }

mkdir -p logs
STAMP="$(date +%Y%m%d_%H%M%S)"
LOG="logs/options_validation_${STAMP}.log"

{
  echo "==================================================================="
  echo "RUN START: $(date)  (host: $(hostname))"
  echo "tz: $(date +%Z%z)  | project: $PROJECT_DIR"
  echo "==================================================================="

  if [ -f ".env" ]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
    echo "env: loaded .env (db=${ALPHA_LAB_DB_PATH:-default})"
  else
    echo "WARNING: .env not found; Alpaca calls will fail without credentials"
  fi

  if [ ! -x ".venv/bin/python" ]; then
    echo "FATAL: .venv/bin/python not found"
    exit 1
  fi

  # -i: prevent idle sleep only while the validator runs. Pass through any args.
  caffeinate -i .venv/bin/python scripts/validate_options_lifecycle.py "$@"
  CODE=$?

  echo "-------------------------------------------------------------------"
  echo "RUN END:   $(date)  | exit_code=$CODE"
  echo "==================================================================="
  exit $CODE
} 2>&1 | tee -a "$LOG"

# Propagate the python exit code (tee would otherwise mask it).
exit ${pipestatus[1]}
