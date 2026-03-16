from __future__ import annotations

from pathlib import Path
from typing import Iterable

from PySide6.QtCore import QUrl


def is_supported_nifti_path(path: str | Path) -> bool:
    file_name = Path(path).name.lower()
    return file_name.endswith(".nii") or file_name.endswith(".nii.gz")


def first_supported_local_nifti_path(urls: Iterable[QUrl]) -> Path | None:
    candidates = list(urls)
    if len(candidates) != 1:
        return None

    candidate_url = candidates[0]
    if not candidate_url.isLocalFile():
        return None

    candidate = Path(candidate_url.toLocalFile())
    if not is_supported_nifti_path(candidate):
        return None
    return candidate
