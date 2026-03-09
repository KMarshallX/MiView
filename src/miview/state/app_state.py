from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from miview.io.nifti_loader import NiftiLoadResult


@dataclass
class AppState:
    loaded_file_path: Path | None = None
    volume: NiftiLoadResult | None = None

