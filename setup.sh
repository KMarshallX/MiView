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
PYPROJECT_PATH="$PROJECT_ROOT/pyproject.toml"
VENV_DIR="$PROJECT_ROOT/.venv"

fail() {
  echo "Error: $1" >&2
  exit 1
}

if [[ ! -f "$PYPROJECT_PATH" ]]; then
  fail "Missing dependency definition: $PYPROJECT_PATH"
fi

if ! SYSTEM_PYTHON="$(detect_python_bin)"; then
  fail "Python is not installed or not on PATH. Install Python 3.11+ first."
fi

if ! require_python_min_version "$SYSTEM_PYTHON" 3 11; then
  fail "MipView requires Python 3.11 or newer."
fi

cd "$PROJECT_ROOT"

echo "Setting up MipView in $PROJECT_ROOT"

if [[ ! -d "$VENV_DIR" ]]; then
  echo "Creating virtual environment at $VENV_DIR"
  "$SYSTEM_PYTHON" -m venv "$VENV_DIR"
else
  echo "Using existing virtual environment at $VENV_DIR"
fi

VENV_PYTHON="$VENV_DIR/bin/python"
if [[ ! -x "$VENV_PYTHON" ]]; then
  fail "Virtual environment python not found at $VENV_PYTHON"
fi

echo "Installing project dependencies from pyproject.toml"
if ! PIP_DISABLE_PIP_VERSION_CHECK=1 "$VENV_PYTHON" -m pip install --upgrade pip; then
  fail "Failed to update pip in $VENV_DIR"
fi
if ! PIP_DISABLE_PIP_VERSION_CHECK=1 "$VENV_PYTHON" -m pip install -e .; then
  fail "Dependency installation failed. Check your internet connection and pip output above."
fi

echo "Setup complete."
echo "Next step: bash run.sh"
