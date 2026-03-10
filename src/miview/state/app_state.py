from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from miview.io.nifti_loader import NiftiLoadResult
from miview.patch.selector import PatchBounds


@dataclass
class AppState:
    loaded_file_path: Path | None = None
    volume: NiftiLoadResult | None = None
    cursor_position: tuple[int, int, int] | None = None
    selected_patch_bounds: PatchBounds | None = None
    selected_patch_data: NiftiLoadResult | None = None
