from __future__ import annotations

import numpy as np
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QGridLayout, QWidget

from miview.state.cursor_state import CursorState
from miview.viewer.slice_geometry import center_cursor_for_volume
from miview.viewer.slice_viewer_widget import SliceViewerWidget


class TriPlanarViewerWidget(QWidget):
    """Minimal tri-planar viewer with a shared logical cursor."""

    cursor_inspection_changed = Signal(object, object, object, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._volume: np.ndarray | None = None
        self.cursor_state = CursorState(self)

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
        self.cursor_state.cursor_changed.connect(self._on_cursor_changed)

        layout = QGridLayout(self)
        layout.addWidget(self.axial_view, 0, 0)
        layout.addWidget(self.coronal_view, 0, 1)
        layout.addWidget(self.sagittal_view, 0, 2)
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(2, 1)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

    def load_volume(self, volume: np.ndarray) -> None:
        if volume.ndim != 3:
            raise ValueError(
                f"Tri-planar viewer expects a 3D volume, got {volume.ndim}D."
            )

        self._volume = np.asarray(volume)
        self.cursor_state.set_volume_shape(tuple(self._volume.shape))
        for view in self._views:
            view.load_volume(self._volume)

        self.cursor_state.set_cursor_position(center_cursor_for_volume(tuple(self._volume.shape)))

    def current_cursor_position(self) -> tuple[int, int, int] | None:
        return self.cursor_state.cursor_position()

    def set_cursor_overlay_visible(self, visible: bool) -> None:
        for view in self._views:
            view.set_cursor_overlay_visible(visible)

    def _on_cursor_selected(self, x: int, y: int, z: int) -> None:
        self.cursor_state.set_cursor_position((x, y, z))

    def _on_cursor_changed(self, x: int, y: int, z: int) -> None:
        if self._volume is None:
            return

        cursor_position = (x, y, z)
        for view in self._views:
            view.set_cursor_position(cursor_position)

        intensity = self._volume[y, x, z].item()
        self.cursor_inspection_changed.emit(x, y, z, intensity)
