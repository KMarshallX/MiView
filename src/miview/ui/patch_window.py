from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QGuiApplication,
    QImage,
    QPainter,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLayout,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from miview.nifti_io import NiftiLoadResult
from miview.patch_history import PatchHistoryManager
from miview.patch_saver import build_patch_default_filename, save_patch_nifti
from miview.patch_selector import PatchBounds
from miview.state.contrast_state import ContrastState
from miview.tools import derive_volume, get_tool
from miview.tools.patch_utility import patch_utility_from_tool
from miview.ui.contrast_helpers import (
    apply_auto_contrast,
    connect_contrast_controls,
    initialize_contrast_state,
)
from miview.ui.contrast_control_bar import ContrastControlBar
from miview.ui.cursor_panel import CursorInspectionPanel
from miview.ui.patch_history_panel import PatchHistoryPanel
from miview.ui.tool_actions import apply_tool_to_volume_with_metadata
from miview.ui.tools_menu import build_tools_submenu
from miview.ui.window_styling import (
    ResponsiveFontScaler,
    apply_window_content_frame,
)
from miview.viewer.intensity import normalize_slice_to_uint8, window_slice_to_uint8
from miview.viewer.triplanar_viewer_widget import TriPlanarViewerWidget


class PatchViewerWindow(QMainWindow):
    """Secondary window for inspecting an extracted patch volume."""

    VIEW_EXPORT_SCALE_FACTOR = 3

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
        self.setAcceptDrops(False)

        self._source_image_name = source_image_name
        self._source_image_path = source_image_path
        self._source_patch_bounds = source_patch_bounds
        self._patch_center = patch_center
        self._patch_size = patch_size if patch_size is not None else patch_volume.shape
        self._patch_data = patch_volume.data
        self._patch_volume = patch_volume
        self._patch_history = PatchHistoryManager(
            patch_volume.data,
            apply_operation=self._apply_history_operation,
            checkpoint_interval=5,
        )
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
        self.patch_history_panel = PatchHistoryPanel(self)
        self.patch_history_panel.restore_requested.connect(
            self._on_restore_patch_history_node_requested
        )
        self._right_panels: list[QWidget] = []
        self._right_control_container = QWidget(self)
        self._right_control_stack_layout = QVBoxLayout(self._right_control_container)
        self._right_control_stack_layout.setContentsMargins(0, 0, 0, 0)
        self._right_control_stack_layout.setSpacing(8)
        self._right_control_stack_layout.setSizeConstraint(
            QLayout.SizeConstraint.SetMinAndMaxSize
        )
        self._right_control_stack_layout.addWidget(self.cursor_panel)
        self._right_control_stack_layout.addStretch(1)
        self.add_right_control_panel(self.mip_minip_panel)
        self.add_right_control_panel(self.patch_save_panel)
        self.add_right_control_panel(self.patch_history_panel)

        self._viewer_scroll_area = QScrollArea(self)
        self._viewer_scroll_area.setWidgetResizable(True)
        self._viewer_scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._viewer_scroll_area.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._viewer_scroll_area.setWidget(self.slice_viewer)

        self._right_control_scroll_area = QScrollArea(self)
        self._right_control_scroll_area.setWidgetResizable(True)
        self._right_control_scroll_area.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._right_control_scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._right_control_scroll_area.setWidget(self._right_control_container)
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
        self._configure_scroll_region_constraints()

        self._main_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self._main_splitter.addWidget(self._viewer_scroll_area)
        self._main_splitter.addWidget(self._right_control_scroll_area)
        self._main_splitter.setStretchFactor(0, 4)
        self._main_splitter.setStretchFactor(1, 1)

        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.contrast_control_bar)
        layout.addWidget(self._main_splitter, 1)
        apply_window_content_frame(self, central)
        self.setCentralWidget(central)
        self._font_scaler.apply()
        self._apply_initial_window_size()
        self._refresh_patch_history_panel()

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
        self._right_panels.append(panel)

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
        self.save_views_button = QPushButton("Save MIP/MinIP Image...", panel)
        self.save_views_button.clicked.connect(self._on_save_views_clicked)
        layout.addWidget(self.save_views_button)
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
        tool_result, status_message = apply_tool_to_volume_with_metadata(
            self,
            tool_id,
            self._patch_volume,
        )
        if tool_result is None:
            self.statusBar().showMessage(status_message)
            return

        transformed_volume = tool_result.transformed_volume
        utility = patch_utility_from_tool(tool_id)
        parameter_summary = utility.summarize(tool_result.parameters)
        self._patch_history.record_operation(
            operation_type=utility.utility_id,
            operation_label=utility.label,
            operation_parameters=tool_result.parameters,
            resulting_patch=transformed_volume.data,
            parameter_summary=parameter_summary,
            is_expensive=False,
        )
        self._patch_volume = transformed_volume
        self._patch_data = transformed_volume.data
        self._replace_patch_viewer_volume(transformed_volume)
        self._initialize_contrast(transformed_volume)
        self._refresh_patch_history_panel()
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

    def _on_save_views_clicked(self) -> None:
        export_default = self._default_views_filename()
        selected_path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Save Current Patch Views",
            export_default,
            "PNG Image (*.png);;JPEG Image (*.jpg *.jpeg);;All Files (*)",
        )
        if not selected_path:
            self.statusBar().showMessage("View export canceled")
            return

        try:
            export_path, format_name = self._resolve_views_export_target(
                selected_path,
                selected_filter,
            )
            composite = self._build_views_composite_image()
            if composite is None:
                QMessageBox.warning(
                    self,
                    "Export Failed",
                    "Current views are not available for export yet.",
                )
                self.statusBar().showMessage("View export failed")
                return
            if not composite.save(str(export_path), format_name):
                raise ValueError(
                    "Unable to save image. Check path permissions and file format."
                )
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Export Failed", str(exc))
            self.statusBar().showMessage("View export failed")
            return

        self.statusBar().showMessage(f"Saved current views: {export_path}")

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

    def _default_views_filename(self) -> str:
        stem = Path(self._default_patch_filename()).stem
        if stem.endswith(".nii"):
            stem = stem[:-4]
        return str(Path.home() / f"{stem}_views.png")

    def _resolve_views_export_target(
        self,
        selected_path: str,
        selected_filter: str,
    ) -> tuple[Path, str]:
        export_path = Path(selected_path)
        suffix = export_path.suffix.lower()
        if suffix == ".png":
            return export_path, "PNG"
        if suffix in {".jpg", ".jpeg"}:
            return export_path, "JPG"

        if "JPEG" in selected_filter.upper():
            return export_path.with_suffix(".jpg"), "JPG"
        return export_path.with_suffix(".png"), "PNG"

    def _build_views_composite_image(self) -> QImage | None:
        projection_planes = self._compute_projection_planes_for_export()
        if projection_planes is None:
            return None
        view_planes = [
            ("Axial", self._normalize_projection_plane_for_export(projection_planes["axial"])),
            ("Coronal", self._normalize_projection_plane_for_export(projection_planes["coronal"])),
            ("Sagittal", self._normalize_projection_plane_for_export(projection_planes["sagittal"])),
        ]

        title_height = 24
        margin = 8
        panel_gap = 8
        panel_widths = [
            int(plane.shape[1]) * self.VIEW_EXPORT_SCALE_FACTOR
            for _, plane in view_planes
        ]
        panel_heights = [
            int(plane.shape[0]) * self.VIEW_EXPORT_SCALE_FACTOR
            for _, plane in view_planes
        ]
        canvas_width = margin * 2 + sum(panel_widths) + panel_gap * (len(view_planes) - 1)
        canvas_height = margin * 2 + title_height + max(panel_heights)
        canvas = QImage(canvas_width, canvas_height, QImage.Format.Format_RGB32)
        canvas.fill(QColor(18, 18, 18))

        painter = QPainter(canvas)
        try:
            title_font = QFont(painter.font())
            title_font.setBold(True)
            painter.setFont(title_font)
            painter.setPen(QColor(230, 230, 230))

            x_offset = margin
            for title, plane in view_planes:
                contiguous = np.ascontiguousarray(plane)
                height, width = contiguous.shape
                source_image = QImage(
                    contiguous.data,
                    width,
                    height,
                    width,
                    QImage.Format.Format_Grayscale8,
                ).copy()
                scaled_image = source_image.scaled(
                    width * self.VIEW_EXPORT_SCALE_FACTOR,
                    height * self.VIEW_EXPORT_SCALE_FACTOR,
                    Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.FastTransformation,
                )
                painter.drawText(
                    x_offset,
                    margin + 16,
                    title,
                )
                painter.drawImage(
                    x_offset,
                    margin + title_height,
                    scaled_image,
                )
                x_offset += scaled_image.width() + panel_gap
        finally:
            painter.end()

        return canvas

    def _compute_projection_planes_for_export(self) -> dict[str, np.ndarray] | None:
        if self._patch_data.ndim != 3:
            return None
        mode = self._current_projection_mode_for_export()
        volume = np.asarray(self._patch_data)
        return {
            "axial": self._project_patch_volume(volume, "axial", mode),
            "coronal": self._project_patch_volume(volume, "coronal", mode),
            "sagittal": self._project_patch_volume(volume, "sagittal", mode),
        }

    def _current_projection_mode_for_export(self) -> str:
        mode = self.projection_mode_combo.currentText().strip().upper()
        return "MIP" if mode == "MIP" else "MINIP"

    def _normalize_projection_plane_for_export(self, plane: np.ndarray) -> np.ndarray:
        if self.contrast_state.is_enabled():
            window_min, window_max = self.contrast_state.window()
            return window_slice_to_uint8(plane, window_min, window_max)
        return normalize_slice_to_uint8(plane)

    @staticmethod
    def _project_patch_volume(
        volume: np.ndarray,
        orientation: str,
        mode: str,
    ) -> np.ndarray:
        reducer = np.max if mode == "MIP" else np.min
        if orientation == "axial":
            return reducer(volume, axis=2).T[::-1, ::-1]
        if orientation == "coronal":
            return reducer(volume, axis=1).T[::-1, ::-1]
        if orientation == "sagittal":
            return reducer(volume, axis=0).T[::-1, ::-1]
        raise ValueError(f"Unsupported orientation: {orientation}")

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
        self._patch_history.reset(patch_volume.data)
        self._replace_patch_viewer_volume(patch_volume)
        self._initialize_contrast(patch_volume)
        self._refresh_patch_history_panel()

    def _on_restore_patch_history_node_requested(self, node_id: str) -> None:
        try:
            restored_patch = self._patch_history.restore(node_id)
        except ValueError as exc:
            QMessageBox.warning(self, "Patch Restore Failed", str(exc))
            self.statusBar().showMessage("Patch restore failed")
            return

        restored_volume = derive_volume(self._patch_volume, restored_patch)
        self._patch_volume = restored_volume
        self._patch_data = restored_patch
        self._replace_patch_viewer_volume(restored_volume)
        self._initialize_contrast(restored_volume)
        self._refresh_patch_history_panel()
        self.statusBar().showMessage("Restored selected patch to history state")

    def _apply_history_operation(
        self,
        patch_state: np.ndarray,
        operation_type: str,
        parameters: dict[str, int | float],
    ) -> np.ndarray:
        utility = patch_utility_from_tool(operation_type)
        return utility.apply(patch_state, parameters)

    def _refresh_patch_history_panel(self) -> None:
        self.patch_history_panel.set_history(
            self._patch_history.nodes_by_step(),
            self._patch_history.active_node_id,
        )

    def _configure_scroll_region_constraints(self) -> None:
        viewer_min_width = max(
            self.slice_viewer.minimumSizeHint().width(),
            self.slice_viewer.sizeHint().width(),
            self.slice_viewer.minimumWidth(),
        )
        viewer_min_height = max(
            self.slice_viewer.minimumSizeHint().height(),
            self.slice_viewer.sizeHint().height(),
            self.slice_viewer.minimumHeight(),
        )
        self.slice_viewer.setMinimumSize(viewer_min_width, viewer_min_height)

        panel_widths = [self._required_widget_width(self.cursor_panel)]
        panel_widths.extend(self._required_widget_width(panel) for panel in self._right_panels)
        layout_margins = self._right_control_stack_layout.contentsMargins()
        right_min_width = max(panel_widths) + layout_margins.left() + layout_margins.right()
        self._right_control_container.setMinimumWidth(right_min_width)

    def _apply_initial_window_size(self) -> None:
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return

        available = screen.availableGeometry()
        viewer_width = self.slice_viewer.minimumWidth()
        right_width = self._right_control_container.minimumWidth()
        self._main_splitter.setSizes([viewer_width, right_width])

        central_widget = self.centralWidget()
        if central_widget is None:
            return

        central_hint = central_widget.sizeHint()
        status_height = self.statusBar().sizeHint().height()
        preferred_width = max(
            central_hint.width(),
            viewer_width + right_width + self._main_splitter.handleWidth(),
        )
        target_width = min(preferred_width, int(available.width() * 0.95))
        target_height = min(
            max(central_hint.height() + status_height, self.minimumSizeHint().height()),
            int(available.height() * 0.95),
        )
        self.resize(target_width, target_height)

    @staticmethod
    def _required_widget_width(widget: QWidget) -> int:
        return max(
            widget.minimumSizeHint().width(),
            widget.sizeHint().width(),
            widget.minimumWidth(),
        )

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
