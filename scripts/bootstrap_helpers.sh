#!/usr/bin/env bash

resolve_project_root_from_script() {
  local script_path="$1"
  local script_dir
  script_dir="$(cd -- "$(dirname -- "$script_path")" && pwd)"
  printf '%s\n' "$script_dir"
}

detect_python_bin() {
  if command -v python3 >/dev/null 2>&1; then
    printf '%s\n' "python3"
    return 0
  fi
  if command -v python >/dev/null 2>&1; then
    printf '%s\n' "python"
    return 0
  fi
  return 1
}

require_python_min_version() {
  local python_bin="$1"
  local major="$2"
  local minor="$3"

  "$python_bin" - <<PY >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (${major}, ${minor}) else 1)
PY
}
