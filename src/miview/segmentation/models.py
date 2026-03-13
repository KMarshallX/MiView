from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from miview.io.nifti_loader import NiftiLoadResult


@dataclass(frozen=True)
class LoadedSegmentation:
    id: str
    path: Path
    volume: NiftiLoadResult

    @property
    def display_name(self) -> str:
        return self.path.name