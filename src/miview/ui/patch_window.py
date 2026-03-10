from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMainWindow, QSplitter, QVBoxLayout, QWidget

from miview.io.nifti_loader import NiftiLoadResult
from miview.state.contrast_state import ContrastState
from miview.ui.contrast_control_bar import ContrastControlBar
from miview.ui.cursor_panel import CursorInspectionPanel
from miview.viewer.intensity import robust_auto_window, volume_intensity_range
from miview.viewer.triplanar_viewer_widget import TriPlanarViewerWidget


class PatchViewerWindow(QMainWindow):
    """Secondary window for inspecting an extracted patch volume."""

    def __init__(self, patch_volume: NiftiLoadResult, parent: QMainWindow | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Selected Patch")
        self.resize(900, 560)

        self._patch_data = patch_volume.data
        self.contrast_state = ContrastState(self)
        self.contrast_control_bar = ContrastControlBar(self)
        self.slice_viewer = TriPlanarViewerWidget(self)
        self.cursor_panel = CursorInspectionPanel(self)
        self.cursor_panel.set_patch_controls_visible(False)

        self.slice_viewer.cursor_inspection_changed.connect(
            self.cursor_panel.set_cursor_values
        )
        self.contrast_control_bar.window_changed.connect(self.contrast_state.set_window)
        self.contrast_control_bar.auto_requested.connect(self._on_auto_contrast)
        self.contrast_state.availability_changed.connect(
            self.contrast_control_bar.set_enabled_state
        )
        self.contrast_state.range_changed.connect(self.contrast_control_bar.set_available_range)
        self.contrast_state.window_changed.connect(self.contrast_control_bar.set_window)
        self.contrast_state.window_changed.connect(self.slice_viewer.set_contrast_window)
        self.slice_viewer.load_volume(patch_volume)
        self._initialize_contrast(patch_volume)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.addWidget(self.slice_viewer)
        splitter.addWidget(self.cursor_panel)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)

        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.contrast_control_bar)
        layout.addWidget(splitter, 1)
        self.setCentralWidget(central)

    def _initialize_contrast(self, patch_volume: NiftiLoadResult) -> None:
        range_min, range_max = volume_intensity_range(patch_volume.data)
        self.contrast_state.set_available_range(range_min, range_max)
        self.contrast_state.set_window(range_min, range_max, force_emit=True)

    def _on_auto_contrast(self) -> None:
        if not self.contrast_state.is_enabled():
            return
        window_min, window_max = robust_auto_window(self._patch_data)
        self.contrast_state.set_window(window_min, window_max)
