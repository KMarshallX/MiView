#!/usr/bin/env python3
"""Validate monotonic release progression for master releases."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tomllib
from pathlib import Path

VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def _run_git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip()


def _load_project_version(pyproject_path: Path) -> tuple[int, int, int]:
    raw = pyproject_path.read_bytes()
    project_data = tomllib.loads(raw.decode("utf-8"))
    version_text = str(project_data["project"]["version"]).strip()
    match = VERSION_RE.fullmatch(version_text)
    if not match:
        raise ValueError(
            f"Invalid project.version '{version_text}'. Expected semantic version x.y.z."
        )
    return tuple(int(value) for value in match.groups())


def _format_version(version: tuple[int, int, int]) -> str:
    return ".".join(str(value) for value in version)


def _latest_version_from_tags() -> tuple[int, int, int] | None:
    tag_output = _run_git("tag", "--list", "v*.*.*")
    latest_version: tuple[int, int, int] | None = None
    for tag in tag_output.splitlines():
        clean_tag = tag.strip()
        if not clean_tag:
            continue
        match = VERSION_RE.fullmatch(clean_tag.removeprefix("v"))
        if not match:
            continue
        version = tuple(int(value) for value in match.groups())
        if latest_version is None or version > latest_version:
            latest_version = version
    return latest_version


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate release version progression for master releases."
    )
    parser.add_argument(
        "--pyproject",
        default="pyproject.toml",
        help="Path to pyproject.toml (default: pyproject.toml).",
    )
    args = parser.parse_args()

    version = _load_project_version(Path(args.pyproject))
    latest_version = _latest_version_from_tags()
    if latest_version is not None and version <= latest_version:
        raise ValueError(
            f"Invalid version progression: latest tag is v{_format_version(latest_version)}, "
            f"found {_format_version(version)}. The release version must be greater "
            "than the latest tag."
        )

    tag = f"v{_format_version(version)}"
    existing_tag = _run_git("tag", "--list", tag)
    if existing_tag:
        raise ValueError(f"Tag {tag} already exists.")

    print(f"Validated release version: {_format_version(version)}")
    print(f"TAG={tag}")
    print(f"VERSION={_format_version(version)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"Version validation failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc