from __future__ import annotations

import numpy as np
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QGridLayout, QWidget

from miview.state.cursor_state import CursorState
from miview.state.zoom_state import ZoomState
from miview.io.nifti_loader import NiftiLoadResult
from miview.viewer.oriented_volume import OrientedVolume, build_oriented_volume
from miview.viewer.slice_geometry import (
    center_cursor_for_volume,
    compute_shared_base_scale,
    plane_shape_for_orientation,
)
from miview.viewer.slice_viewer_widget import SliceViewerWidget


class TriPlanarViewerWidget(QWidget):
    """Minimal tri-planar viewer with a shared logical cursor."""

    cursor_inspection_changed = Signal(object, object, object, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._display_volume: OrientedVolume | None = None
        self.cursor_state = CursorState(self)
        self.zoom_state = ZoomState(self)

        self.axial_view = SliceViewerWidget("axial", self)
        self.coronal_view = SliceViewerWidget("coronal", self)
        self.sagittal_view = SliceViewerWidget("sagittal", self)
        self._views = (
            self.axial_view,
            self.coronal_view,
            self.sagittal_view,
        )

        for view in self._views:
            view.cursor_position_selected.connect(self._on_cursor_selected)
            view.zoom_factor_requested.connect(self.zoom_state.set_zoom_factor)
            view.viewport_resized.connect(self._update_shared_base_scale)
        self.cursor_state.cursor_changed.connect(self._on_cursor_changed)
        self.zoom_state.zoom_changed.connect(self._on_zoom_changed)

        layout = QGridLayout(self)
        layout.addWidget(self.axial_view, 0, 0)
        layout.addWidget(self.coronal_view, 0, 1)
        layout.addWidget(self.sagittal_view, 0, 2)
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(2, 1)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

    def load_volume(self, volume: NiftiLoadResult) -> None:
        if volume.data.ndim != 3:
            raise ValueError(
                f"Tri-planar viewer expects a 3D volume, got {volume.data.ndim}D."
            )

        self._display_volume = build_oriented_volume(volume.data, volume.affine)
        self.cursor_state.set_volume_shape(self._display_volume.source_shape)
        for view in self._views:
            view.load_volume(self._display_volume)

        self._update_shared_base_scale()
        self.zoom_state.set_zoom_factor(1.0)
        self.cursor_state.set_cursor_position(center_cursor_for_volume(self._display_volume.source_shape))

    def unload_volume(self) -> None:
        self._display_volume = None
        self.cursor_state.clear()
        self.zoom_state.set_zoom_factor(1.0)
        for view in self._views:
            view.unload_volume()

    def current_cursor_position(self) -> tuple[int, int, int] | None:
        return self.cursor_state.cursor_position()

    def set_cursor_overlay_visible(self, visible: bool) -> None:
        for view in self._views:
            view.set_cursor_overlay_visible(visible)

    def _on_cursor_selected(self, x: int, y: int, z: int) -> None:
        self.cursor_state.set_cursor_position((x, y, z))

    def _on_cursor_changed(self, x: int, y: int, z: int) -> None:
        if self._display_volume is None:
            return

        cursor_position = (x, y, z)
        for view in self._views:
            view.set_cursor_position(cursor_position)

        intensity = self._display_volume.source_data[x, y, z].item()
        self.cursor_inspection_changed.emit(x, y, z, intensity)

    def _on_zoom_changed(self, zoom_factor: float) -> None:
        for view in self._views:
            view.set_zoom_factor(zoom_factor)

    def _update_shared_base_scale(self) -> None:
        if self._display_volume is None:
            return

        plane_sizes = [
            plane_shape_for_orientation(self._display_volume.display_shape, view.orientation)
            for view in self._views
        ]
        viewport_sizes = [view.viewport_size() for view in self._views]
        base_scale = compute_shared_base_scale(plane_sizes, viewport_sizes)
        for view in self._views:
            view.set_base_scale(base_scale)
