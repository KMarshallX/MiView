from __future__ import annotations

from pathlib import Path
from typing import Iterable

from PySide6.QtCore import QUrl


def is_supported_nifti_path(path: str | Path) -> bool:
    file_name = Path(path).name.lower()
    return file_name.endswith(".nii") or file_name.endswith(".nii.gz")


def is_supported_graph_state_path(path: str | Path) -> bool:
    return Path(path).name.lower().endswith(".mipgraph.json")


def is_supported_graphml_path(path: str | Path) -> bool:
    return Path(path).name.lower().endswith(".graphml")


def first_supported_local_drop_path(urls: Iterable[QUrl]) -> Path | None:
    candidates = list(urls)
    if len(candidates) != 1:
        return None
    candidate_url = candidates[0]
    if not candidate_url.isLocalFile():
        return None
    candidate = Path(candidate_url.toLocalFile())
    if not (
        is_supported_nifti_path(candidate)
        or is_supported_graph_state_path(candidate)
        or is_supported_graphml_path(candidate)
    ):
        return None
    return candidate


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
