from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

from miview.nifti_io import NiftiLoadResult
from miview.patch_selector import PatchBounds
from miview.segmentation_models import LoadedSegmentation


@dataclass
class AppState:
    loaded_file_path: Path | None = None
    volume: NiftiLoadResult | None = None
    cursor_position: tuple[int, int, int] | None = None
    selected_patch_bounds: PatchBounds | None = None
    selected_patch_data: NiftiLoadResult | None = None
    segmentation_image_path: Path | None = None
    loaded_segmentations: list[LoadedSegmentation] = field(default_factory=list)
    active_segmentation_id: str | None = None
    segmentation_opacity: float = 0.5
