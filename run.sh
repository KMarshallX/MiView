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
ENTRYPOINT_PATH="$PROJECT_ROOT/src/mipview/__main__.py"

if [[ ! -f "$ENTRYPOINT_PATH" ]]; then
  echo "Error: MipView entrypoint not found at $ENTRYPOINT_PATH" >&2
  exit 1
fi

if [[ -x "$PROJECT_ROOT/.venv/bin/python" ]] && \
  PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}" \
  "$PROJECT_ROOT/.venv/bin/python" - <<'PY' >/dev/null 2>&1
import importlib
for module_name in ("PySide6", "nibabel", "numpy"):
    importlib.import_module(module_name)
PY
then
  PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"
elif PYTHON_BIN="$(detect_python_bin)"; then
  :
else
  echo "Error: Python is not installed or not on PATH." >&2
  exit 1
fi

cd "$PROJECT_ROOT"

echo "Launching MipView from $PROJECT_ROOT using $PYTHON_BIN -m mipview"
if ! PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON_BIN" -m mipview "$@"; then
  echo "Error: MipView failed to launch." >&2
  exit 1
fi
