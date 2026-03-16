from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QResizeEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from miview.nifti_io import NiftiLoadResult
from miview.patch_saver import build_patch_default_filename, save_patch_nifti
from miview.patch_selector import PatchBounds
from miview.state.contrast_state import ContrastState
from miview.tools import get_tool
from miview.ui.contrast_helpers import (
    apply_auto_contrast,
    connect_contrast_controls,
    initialize_contrast_state,
)
from miview.ui.contrast_control_bar import ContrastControlBar
from miview.ui.cursor_panel import CursorInspectionPanel
from miview.ui.tool_actions import apply_tool_to_volume
from miview.ui.tools_menu import build_tools_submenu
from miview.ui.window_styling import (
    ResponsiveFontScaler,
    apply_window_content_frame,
)
from miview.viewer.triplanar_viewer_widget import TriPlanarViewerWidget


class PatchViewerWindow(QMainWindow):
    """Secondary window for inspecting an extracted patch volume."""

    def __init__(
        self,
        patch_volume: NiftiLoadResult,
        segmentation_volume: NiftiLoadResult | None = None,
        segmentation_opacity: float = 0.5,
        parent: QMainWindow | None = None,
        source_image_name: str = "image.nii.gz",
        source_image_path: Path | None = None,
        source_patch_bounds: PatchBounds | None = None,
        patch_center: tuple[int, int, int] | None = None,
        patch_size: tuple[int, int, int] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Selected Patch")
        self.resize(900, 560)
        self.setAcceptDrops(False)

        self._source_image_name = source_image_name
        self._source_image_path = source_image_path
        self._source_patch_bounds = source_patch_bounds
        self._patch_center = patch_center
        self._patch_size = patch_size if patch_size is not None else patch_volume.shape
        self._patch_data = patch_volume.data
        self._patch_volume = patch_volume
        self._font_scaler = ResponsiveFontScaler(
            self,
            reference_width=900,
            reference_height=560,
        )
        self.contrast_state = ContrastState(self)
        self.contrast_control_bar = ContrastControlBar(self)
        self.slice_viewer = TriPlanarViewerWidget(self)
        self.cursor_panel = CursorInspectionPanel(self)
        self.cursor_panel.set_patch_controls_visible(False)
        self.mip_minip_panel = self._build_mip_minip_panel(self)
        self.patch_save_panel = self._build_save_panel(self)
        self._right_control_container = QWidget(self)
        self._right_control_container.setFixedWidth(self.cursor_panel.width())
        self._right_control_stack_layout = QVBoxLayout(self._right_control_container)
        self._right_control_stack_layout.setContentsMargins(0, 0, 0, 0)
        self._right_control_stack_layout.setSpacing(8)
        self._right_control_stack_layout.addWidget(self.cursor_panel)
        self._right_control_stack_layout.addStretch(1)
        self.add_right_control_panel(self.mip_minip_panel)
        self.add_right_control_panel(self.patch_save_panel)
        self._setup_menu()

        self.slice_viewer.cursor_inspection_changed.connect(
            self.cursor_panel.set_cursor_values
        )
        connect_contrast_controls(
            self.contrast_control_bar,
            self.contrast_state,
            self.slice_viewer,
            self._on_auto_contrast,
        )
        self.slice_viewer.load_volume(patch_volume)
        if segmentation_volume is not None:
            self.slice_viewer.set_segmentation_overlay(
                segmentation_volume,
                opacity=segmentation_opacity,
            )
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
        apply_window_content_frame(self, central)
        self.setCentralWidget(central)
        self._font_scaler.apply()

    def _setup_menu(self) -> None:
        tools_menu = self.menuBar().addMenu("&Tools")
        build_tools_submenu(
            self,
            tools_menu,
            self._on_apply_tool_to_patch_requested,
        )
        tools_menu.addSeparator()
        auto_contrast_action = QAction("&Auto Contrast", self)
        auto_contrast_action.triggered.connect(self._on_auto_contrast)
        tools_menu.addAction(auto_contrast_action)

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

    def _build_save_panel(self, parent: QWidget | None = None) -> QGroupBox:
        panel = QGroupBox("Patch Save", parent)
        layout = QVBoxLayout(panel)
        self.save_patch_button = QPushButton("Save Patch...", panel)
        self.save_patch_button.clicked.connect(self._on_save_patch_clicked)
        layout.addWidget(self.save_patch_button)
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
        initialize_contrast_state(self.contrast_state, patch_volume)

    def _on_auto_contrast(self) -> None:
        apply_auto_contrast(self.contrast_state, self._patch_data)

    def _on_apply_tool_to_patch_requested(self, tool_id: str) -> None:
        transformed_volume, status_message = apply_tool_to_volume(
            self,
            tool_id,
            self._patch_volume,
        )
        if transformed_volume is None:
            self.statusBar().showMessage(status_message)
            return

        self._patch_volume = transformed_volume
        self._patch_data = transformed_volume.data
        self._replace_patch_viewer_volume(transformed_volume)
        self._initialize_contrast(transformed_volume)
        self.statusBar().showMessage(f"Applied {get_tool(tool_id).label} to selected patch")

    def _on_save_patch_clicked(self) -> None:
        default_name = self._default_patch_filename()
        selected_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Selected Patch",
            default_name,
            "NIfTI Files (*.nii.gz *.nii);;All Files (*)",
        )
        if not selected_path:
            self.statusBar().showMessage("Patch save canceled")
            return

        try:
            saved_path = save_patch_nifti(self._patch_volume, selected_path)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Save Patch Failed", str(exc))
            self.statusBar().showMessage("Patch save failed")
            return

        self.statusBar().showMessage(f"Patch saved: {saved_path}")

    def _default_patch_filename(self) -> str:
        center = self._patch_center if self._patch_center is not None else (0, 0, 0)
        size = (
            tuple(int(v) for v in self._patch_size)
            if self._patch_size is not None
            else tuple(int(v) for v in self._patch_volume.shape)
        )
        filename = build_patch_default_filename(
            source_image_name=self._source_image_name,
            patch_center=(int(center[0]), int(center[1]), int(center[2])),
            patch_size=(int(size[0]), int(size[1]), int(size[2])),
            extension=".nii.gz",
        )
        return str(Path.home() / filename)

    def source_image_path(self) -> Path | None:
        return self._source_image_path

    def source_patch_bounds(self) -> PatchBounds | None:
        return self._source_patch_bounds

    def update_segmentation_overlay(
        self,
        segmentation_volume: NiftiLoadResult | None,
        opacity: float,
    ) -> None:
        self.slice_viewer.set_segmentation_overlay(segmentation_volume, opacity=opacity)

    def update_segmentation_opacity(self, opacity: float) -> None:
        self.slice_viewer.set_segmentation_overlay_opacity(opacity)

    def sync_patch_from_parent(self, patch_volume: NiftiLoadResult) -> None:
        """Replace local patch data from parent-image processing updates."""
        self._patch_volume = patch_volume
        self._patch_data = patch_volume.data
        self._replace_patch_viewer_volume(patch_volume)
        self._initialize_contrast(patch_volume)

    def _replace_patch_viewer_volume(self, patch_volume: NiftiLoadResult) -> None:
        cursor_position = self.slice_viewer.current_cursor_position()
        patch_enabled = self.slice_viewer.patch_selection_enabled()
        patch_center = self.slice_viewer.current_patch_center()
        patch_size = self.slice_viewer.patch_size_xyz()
        self.slice_viewer.replace_volume(
            patch_volume,
            cursor_position=cursor_position,
            patch_center=patch_center,
            patch_size_xyz=patch_size,
            patch_selection_enabled=patch_enabled,
        )

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._font_scaler.apply()
