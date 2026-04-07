#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
COMMON_HELPERS="$SCRIPT_DIR/scripts/bootstrap_helpers.sh"
if [[ ! -f "$COMMON_HELPERS" ]]; then
  echo "Error: Missing bootstrap helpers at $COMMON_HELPERS" >&2
  exit 1
fi
source "$COMMON_HELPERS"

PROJECT_ROOT="$(resolve_project_root_from_script "${BASH_SOURCE[0]}")"
LOCAL_VENV_MIPVIEW="$PROJECT_ROOT/.venv/bin/mipview"

cd "$PROJECT_ROOT"

if [[ -x "$LOCAL_VENV_MIPVIEW" ]]; then
  echo "Launching MipView from repo-local virtual environment"
  exec "$LOCAL_VENV_MIPVIEW" "$@"
fi

if command -v mipview >/dev/null 2>&1; then
  echo "Launching MipView from PATH"
  exec mipview "$@"
fi

if PYTHON_BIN="$(detect_python_bin)"; then
  echo "Launching MipView from source checkout via PYTHONPATH fallback"
  exec env PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON_BIN" -m mipview "$@"
else
  echo "Error: Neither an installed 'mipview' command nor a Python interpreter was found." >&2
  exit 1
fi
