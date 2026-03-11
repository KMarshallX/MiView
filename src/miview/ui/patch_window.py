from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QMainWindow,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

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
        self.mip_minip_panel = self._build_mip_minip_panel(self)
        self._right_control_container = QWidget(self)
        self._right_control_container.setFixedWidth(self.cursor_panel.width())
        self._right_control_stack_layout = QVBoxLayout(self._right_control_container)
        self._right_control_stack_layout.setContentsMargins(0, 0, 0, 0)
        self._right_control_stack_layout.setSpacing(8)
        self._right_control_stack_layout.addWidget(self.cursor_panel)
        self._right_control_stack_layout.addStretch(1)
        self.add_right_control_panel(self.mip_minip_panel)

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
        self._sync_projection_controls()

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.addWidget(self.slice_viewer)
        splitter.addWidget(self._right_control_container)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)

        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.contrast_control_bar)
        layout.addWidget(splitter, 1)
        self.setCentralWidget(central)

    def add_right_control_panel(self, panel: QWidget) -> None:
        """Insert a tool/config panel below cursor inspection in the right stack."""
        insert_at = max(self._right_control_stack_layout.count() - 1, 0)
        self._right_control_stack_layout.insertWidget(insert_at, panel)

    def _build_mip_minip_panel(self, parent: QWidget | None = None) -> QGroupBox:
        panel = QGroupBox("MIP / MinIP", parent)
        form = QFormLayout(panel)

        self.projection_mode_combo = QComboBox(panel)
        self.projection_mode_combo.addItems(["MIP", "MinIP"])
        self.projection_mode_combo.currentTextChanged.connect(self._on_projection_mode_changed)

        direction_row = QWidget(panel)
        direction_layout = QHBoxLayout(direction_row)
        direction_layout.setContentsMargins(0, 0, 0, 0)
        direction_layout.setSpacing(6)

        self.axial_toggle_button = QPushButton("Axial", direction_row)
        self.axial_toggle_button.setCheckable(True)
        self.axial_toggle_button.toggled.connect(
            lambda enabled: self._on_projection_direction_toggled("axial", enabled)
        )
        direction_layout.addWidget(self.axial_toggle_button)

        self.coronal_toggle_button = QPushButton("Coronal", direction_row)
        self.coronal_toggle_button.setCheckable(True)
        self.coronal_toggle_button.toggled.connect(
            lambda enabled: self._on_projection_direction_toggled("coronal", enabled)
        )
        direction_layout.addWidget(self.coronal_toggle_button)

        self.sagittal_toggle_button = QPushButton("Sagittal", direction_row)
        self.sagittal_toggle_button.setCheckable(True)
        self.sagittal_toggle_button.toggled.connect(
            lambda enabled: self._on_projection_direction_toggled("sagittal", enabled)
        )
        direction_layout.addWidget(self.sagittal_toggle_button)

        form.addRow("Mode:", self.projection_mode_combo)
        form.addRow("Direction:", direction_row)
        return panel

    def _sync_projection_controls(self) -> None:
        self.slice_viewer.set_projection_mode(self.projection_mode_combo.currentText())
        self.slice_viewer.set_projection_enabled(
            "axial", self.axial_toggle_button.isChecked()
        )
        self.slice_viewer.set_projection_enabled(
            "sagittal", self.sagittal_toggle_button.isChecked()
        )
        self.slice_viewer.set_projection_enabled(
            "coronal", self.coronal_toggle_button.isChecked()
        )

    def _on_projection_mode_changed(self, mode: str) -> None:
        self.slice_viewer.set_projection_mode(mode)

    def _on_projection_direction_toggled(self, orientation: str, enabled: bool) -> None:
        self.slice_viewer.set_projection_enabled(orientation, enabled)

    def _initialize_contrast(self, patch_volume: NiftiLoadResult) -> None:
        range_min, range_max = volume_intensity_range(patch_volume.data)
        self.contrast_state.set_available_range(range_min, range_max)
        self.contrast_state.set_window(range_min, range_max, force_emit=True)

    def _on_auto_contrast(self) -> None:
        if not self.contrast_state.is_enabled():
            return
        window_min, window_max = robust_auto_window(self._patch_data)
        self.contrast_state.set_window(window_min, window_max)
