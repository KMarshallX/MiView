from __future__ import annotations

import numpy as np

from mipview.nifti_io import NiftiLoadResult
from mipview.state.contrast_state import ContrastState
from mipview.ui.contrast_control_bar import ContrastControlBar
from mipview.viewer.intensity import robust_auto_window, volume_intensity_range
from mipview.viewer.triplanar_viewer_widget import TriPlanarViewerWidget


def connect_contrast_controls(
    contrast_bar: ContrastControlBar,
    contrast_state: ContrastState,
    slice_viewer: TriPlanarViewerWidget,
    auto_handler: object,
) -> None:
    """Bind the shared contrast controls used by the main and patch windows."""
    contrast_bar.window_changed.connect(contrast_state.set_window)
    contrast_bar.auto_requested.connect(auto_handler)
    contrast_state.availability_changed.connect(contrast_bar.set_enabled_state)
    contrast_state.range_changed.connect(contrast_bar.set_available_range)
    contrast_state.window_changed.connect(contrast_bar.set_window)
    contrast_state.window_changed.connect(slice_viewer.set_contrast_window)


def initialize_contrast_state(
    contrast_state: ContrastState,
    volume: NiftiLoadResult | None,
) -> None:
    if volume is None:
        contrast_state.clear()
        return

    range_min, range_max = volume_intensity_range(volume.data)
    contrast_state.set_available_range(range_min, range_max)
    contrast_state.set_window(range_min, range_max, force_emit=True)


def apply_auto_contrast(
    contrast_state: ContrastState,
    volume_data: np.ndarray | None,
) -> None:
    if volume_data is None or not contrast_state.is_enabled():
        return
    window_min, window_max = robust_auto_window(volume_data)
    contrast_state.set_window(window_min, window_max)
