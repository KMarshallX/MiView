#!/usr/bin/env python3
"""Validate patch-only release progression for master releases."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tomllib
from pathlib import Path

VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
RELEASE_SERIES = (0, 1)


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


def _latest_patch_from_tags() -> int | None:
    major, minor = RELEASE_SERIES
    pattern = f"v{major}.{minor}.*"
    tag_output = _run_git("tag", "--list", pattern)
    latest_patch: int | None = None
    for tag in tag_output.splitlines():
        clean_tag = tag.strip()
        if not clean_tag:
            continue
        match = VERSION_RE.fullmatch(clean_tag.removeprefix("v"))
        if not match:
            continue
        tag_major, tag_minor, patch = (int(value) for value in match.groups())
        if (tag_major, tag_minor) != RELEASE_SERIES:
            continue
        if latest_patch is None or patch > latest_patch:
            latest_patch = patch
    return latest_patch


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

    major, minor, patch = _load_project_version(Path(args.pyproject))
    if (major, minor) != RELEASE_SERIES:
        expected = ".".join(str(value) for value in RELEASE_SERIES)
        raise ValueError(
            f"Release series mismatch: expected {expected}.x, found {major}.{minor}.{patch}."
        )

    latest_patch = _latest_patch_from_tags()
    expected_patch = 0 if latest_patch is None else latest_patch + 1
    if patch != expected_patch:
        latest_text = (
            "none"
            if latest_patch is None
            else f"v{RELEASE_SERIES[0]}.{RELEASE_SERIES[1]}.{latest_patch}"
        )
        raise ValueError(
            f"Invalid patch progression: latest tag is {latest_text}, "
            f"so expected {major}.{minor}.{expected_patch}, found {major}.{minor}.{patch}."
        )

    tag = f"v{major}.{minor}.{patch}"
    existing_tag = _run_git("tag", "--list", tag)
    if existing_tag:
        raise ValueError(f"Tag {tag} already exists.")

    print(f"Validated release version: {major}.{minor}.{patch}")
    print(f"TAG={tag}")
    print(f"VERSION={major}.{minor}.{patch}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"Version validation failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
