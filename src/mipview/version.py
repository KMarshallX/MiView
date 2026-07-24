from __future__ import annotations

from functools import cache
from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path
import tomllib


@cache
def current_version() -> str:
    """Return the source-tree or installed MipView package version."""
    pyproject_path = Path(__file__).resolve().parents[2] / "pyproject.toml"
    if pyproject_path.is_file():
        try:
            with pyproject_path.open("rb") as pyproject_file:
                project = tomllib.load(pyproject_file).get("project", {})
            version = project.get("version")
            if isinstance(version, str) and version.strip():
                return version.strip()
        except (OSError, tomllib.TOMLDecodeError):
            pass

    try:
        return package_version("mipview")
    except PackageNotFoundError:
        return "unknown"


def versioned_window_title(title: str) -> str:
    """Append the current MipView version to a window title."""
    return f"{title} (Version: {current_version()})"
