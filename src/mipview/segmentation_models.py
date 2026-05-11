from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from mipview.nifti_io import NiftiLoadResult

SegmentationKind = Literal["file", "annotation"]


@dataclass(frozen=True)
class LoadedSegmentation:
    id: str
    path: Path | None
    volume: NiftiLoadResult
    kind: SegmentationKind = "file"
    display_name_override: str | None = None

    @property
    def display_name(self) -> str:
        if self.display_name_override is not None:
            return self.display_name_override
        if self.path is None:
            return self.id
        return self.path.name
