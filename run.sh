#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"
ENTRYPOINT_PATH="$PROJECT_ROOT/src/miview/__main__.py"

if [[ ! -f "$ENTRYPOINT_PATH" ]]; then
  echo "Error: MiView entrypoint not found at $ENTRYPOINT_PATH" >&2
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
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
else
  echo "Error: Python is not installed or not on PATH." >&2
  exit 1
fi

cd "$PROJECT_ROOT"

echo "Launching MiView from $PROJECT_ROOT using $PYTHON_BIN -m miview"
if ! PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON_BIN" -m miview "$@"; then
  echo "Error: MiView failed to launch." >&2
  exit 1
fi
