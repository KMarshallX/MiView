from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

from mipview.annotation import AnnotationState
from mipview.io.nifti_io import NiftiLoadResult
from mipview.patch.selector import PatchBounds
from mipview.segmentation.models import LoadedSegmentation
from mipview.vessel_graph.model import VesselGraphLayer


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
    loaded_vessel_graphs: list[VesselGraphLayer] = field(default_factory=list)
    active_vessel_graph_id: str | None = None
    annotation: AnnotationState = field(default_factory=AnnotationState)
