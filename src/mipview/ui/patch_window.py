from __future__ import annotations

from collections.abc import Sequence
import os
from pathlib import Path
from typing import Literal
from uuid import uuid4

import numpy as np
from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QGuiApplication,
    QImage,
    QImageWriter,
    QKeySequence,
    QPainter,
    QResizeEvent,
    QShortcut,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLayout,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from mipview.annotation import AnnotationMask
from mipview.annotation.annotation_overlay import build_annotation_overlay_rgba
from mipview.graph import (
    AngleMeasurement,
    GraphEdge,
    GraphNode,
    GraphVector,
    ProjectionGraphState,
)
from mipview.graph.spatial import (
    nearest_projected_edge_parameter,
)
from mipview.io.nifti_io import NiftiLoadResult
from mipview.patch.history import PatchHistoryManager
from mipview.patch.saver import build_patch_default_filename, save_patch_nifti
from mipview.patch.selector import PatchBounds
from mipview.segmentation.overlay import build_segmentation_overlay_rgba
from mipview.state.contrast_state import ContrastState
from mipview.tools import derive_volume, get_tool
from mipview.tools.patch_utility import patch_utility_from_tool
from mipview.ui.contrast_helpers import (
    apply_auto_contrast,
    connect_contrast_controls,
    initialize_contrast_state,
)
from mipview.ui.contrast_control_bar import ContrastControlBar
from mipview.ui.cursor_panel import CursorInspectionPanel
from mipview.ui.annotation_panel import AnnotationPanel
from mipview.ui.graph_panel import GraphPanel
from mipview.ui.overlay_opacity_control_bar import OverlayOpacityControlBar
from mipview.ui.patch_history_panel import PatchHistoryPanel
from mipview.ui.tool_actions import apply_tool_to_volume_with_metadata
from mipview.ui.tools_menu import build_tools_submenu
from mipview.ui.window_styling import (
    ResponsiveFontScaler,
    apply_window_content_frame,
)
from mipview.viewer.intensity import normalize_slice_to_uint8, window_slice_to_uint8
from mipview.viewer.oriented_volume import build_oriented_volume
from mipview.viewer.ruler import display_voxel_spacing_mm, spatial_unit_to_mm
from mipview.viewer.slice_geometry import project_oriented_volume
from mipview.viewer.slice_geometry import Orientation, plane_axes_for_orientation
from mipview.viewer.triplanar_viewer_widget import TriPlanarViewerWidget


class PatchViewerWindow(QMainWindow):
    """Secondary window for inspecting an extracted patch volume."""

    annotation_create_requested = Signal(object)
    annotation_patch_changed = Signal(object)
    annotation_undo_requested_from_patch = Signal(object)
    annotation_visibility_changed = Signal(bool)
    annotation_opacity_changed = Signal(float)
    annotation_active_label_changed = Signal(int)
    annotation_brush_radius_changed = Signal(int)
    annotation_brush_mode_changed = Signal(str)
    overlay_opacity_changed = Signal(float)
    unload_current_segmentation_requested = Signal()
    open_segmentation_configuration_requested = Signal()

    VIEW_EXPORT_SCALE_FACTOR = 3

    def __init__(
        self,
        patch_volume: NiftiLoadResult,
        segmentation_volume: NiftiLoadResult | None = None,
        segmentation_opacity: float = 0.5,
        annotation_mask: AnnotationMask | None = None,
        annotation_opacity: float = 0.5,
        annotation_visible: bool = True,
        annotation_active_label: int = 1,
        annotation_editing_enabled: bool = False,
        annotation_brush_radius: int = 1,
        annotation_brush_mode: str = "paint",
        parent: QMainWindow | None = None,
        source_image_name: str = "image.nii.gz",
        source_image_path: Path | None = None,
        source_patch_bounds: PatchBounds | None = None,
        patch_center: tuple[int, int, int] | None = None,
        patch_size: tuple[int, int, int] | None = None,
        projection_mask_layers: Sequence[
            tuple[str, str, NiftiLoadResult]
        ] | None = None,
        active_segmentation_kind: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Selected Patch")
        self.setAcceptDrops(False)

        self._source_image_name = source_image_name
        self.graph_session_id = uuid4().hex
        self._source_image_path = source_image_path
        self._source_patch_bounds = source_patch_bounds
        self._patch_center = patch_center
        self._patch_size = patch_size if patch_size is not None else patch_volume.shape
        self._patch_data = patch_volume.data
        self._patch_volume = patch_volume
        self._segmentation_patch_volume = segmentation_volume
        if active_segmentation_kind not in {None, "file", "annotation"}:
            raise ValueError(
                "Active segmentation kind must be file, annotation, or None."
            )
        self._active_segmentation_kind = active_segmentation_kind
        if self._active_segmentation_kind is None:
            if segmentation_volume is not None:
                self._active_segmentation_kind = "file"
            elif annotation_mask is not None:
                self._active_segmentation_kind = "annotation"
        self._projection_mask_layers: dict[str, NiftiLoadResult] = {}
        self._annotation_patch_mask = annotation_mask
        self._segmentation_opacity = min(
            max(float(segmentation_opacity), 0.0),
            1.0,
        )
        self._annotation_opacity = min(max(float(annotation_opacity), 0.0), 1.0)
        self._annotation_visible = bool(annotation_visible)
        self._annotation_active_label = max(int(annotation_active_label), 0)
        self.graph_state = ProjectionGraphState()
        self._graph_projection_mode = "MIP"
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
        self.overlay_opacity_control_bar = OverlayOpacityControlBar(
            self,
            opacity=self._active_overlay_opacity(),
        )
        self.overlay_opacity_control_bar.opacity_changed.connect(
            self._on_overlay_opacity_changed
        )
        self.slice_viewer = TriPlanarViewerWidget(self)
        self.slice_viewer.set_projection_segmentation_source(
            self._active_segmentation_kind
        )
        self.slice_viewer.set_projection_segmentation_enabled(False)
        self.cursor_panel = CursorInspectionPanel(self, adaptable_width=True)
        self.cursor_panel.set_axis_directions(patch_volume.affine)
        self.cursor_panel.set_patch_controls_visible(False)
        self.annotation_panel = AnnotationPanel(
            self,
            show_file_actions=False,
            adaptable_width=True,
        )
        self.graph_panel = GraphPanel(self, adaptable_width=True)
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
        self.add_right_control_panel(self.annotation_panel)
        self.add_right_control_panel(self.graph_panel)
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
        self.slice_viewer.annotation_changed.connect(self._on_annotation_changed)
        self.slice_viewer.annotation_undo_availability_changed.connect(
            self.annotation_panel.set_undo_available
        )
        self.slice_viewer.graph_context_requested.connect(
            self._on_graph_context_requested
        )
        self.slice_viewer.graph_edge_completion_requested.connect(
            self._on_graph_edge_completion_requested
        )
        self.slice_viewer.graph_edge_cancel_requested.connect(
            self._cancel_pending_graph_edge
        )
        self.slice_viewer.graph_vector_completion_requested.connect(
            self._on_graph_vector_completion_requested
        )
        self.slice_viewer.graph_orientation_interacted.connect(
            self._on_graph_orientation_interacted
        )
        self.slice_viewer.projection_state_changed.connect(
            self._on_graph_projection_state_changed
        )
        self.slice_viewer.graph_layers_cleared.connect(
            self._on_graph_layers_cleared
        )
        self.slice_viewer.graph_curve_edge_selected.connect(
            self._on_graph_curve_edge_selected
        )
        self.slice_viewer.graph_curve_control_changed.connect(
            self._on_graph_curve_control_changed
        )
        self.slice_viewer.graph_curve_drag_state_changed.connect(
            self._on_graph_curve_drag_state_changed
        )
        self.slice_viewer.graph_curve_exit_requested.connect(
            self._cancel_graph_interaction
        )
        self.slice_viewer.graph_angle_vector_selected.connect(
            self._on_graph_angle_vector_selected
        )
        self.annotation_panel.create_requested.connect(
            lambda: self.annotation_create_requested.emit(self)
        )
        self.annotation_panel.visibility_changed.connect(
            self.annotation_visibility_changed.emit
        )
        self.annotation_panel.opacity_changed.connect(self.annotation_opacity_changed.emit)
        self.annotation_panel.active_label_changed.connect(
            self.annotation_active_label_changed.emit
        )
        self.annotation_panel.brush_radius_changed.connect(
            self.annotation_brush_radius_changed.emit
        )
        self.annotation_panel.brush_mode_changed.connect(
            self.annotation_brush_mode_changed.emit
        )
        self.annotation_panel.undo_requested.connect(self._on_annotation_undo_requested)
        self.graph_panel.activation_requested.connect(
            self._on_graph_activation_requested
        )
        self.graph_panel.visibility_changed.connect(self._on_graph_visibility_changed)
        self.graph_panel.opacity_changed.connect(self._on_graph_opacity_changed)
        self.graph_panel.node_size_changed.connect(self._on_graph_node_size_changed)
        self.graph_panel.edge_thickness_changed.connect(
            self._on_graph_edge_thickness_changed
        )
        self.graph_panel.curve_tool_requested.connect(
            self._on_graph_curve_tool_requested
        )
        self.graph_panel.straighten_edge_requested.connect(
            self._on_graph_straighten_requested
        )
        self.graph_panel.clear_graph_requested.connect(self.clear_graph)
        self.graph_panel.calculate_angle_requested.connect(
            self._on_graph_calculate_angle_requested
        )
        self.graph_panel.cancel_requested.connect(self._cancel_graph_interaction)
        self.graph_panel.delete_angle_requested.connect(self.delete_graph_angle)
        self.graph_panel.clear_angles_requested.connect(self.clear_graph_angles)
        self._graph_cancel_shortcut = QShortcut(
            QKeySequence(QKeySequence.StandardKey.Cancel),
            self,
        )
        self._graph_cancel_shortcut.activated.connect(self._cancel_graph_interaction)
        connect_contrast_controls(
            self.contrast_control_bar,
            self.contrast_state,
            self.slice_viewer,
            self._on_auto_contrast,
        )
        self.slice_viewer.load_volume(patch_volume)
        self.update_projection_mask_layers(projection_mask_layers or ())
        self.slice_viewer.set_projection_graph_state(self.graph_state)
        if segmentation_volume is not None:
            self.slice_viewer.set_segmentation_overlay(
                segmentation_volume,
                opacity=self._segmentation_opacity,
            )
        self.slice_viewer.set_annotation_overlay(
            annotation_mask,
            opacity=self._annotation_opacity,
            visible=annotation_visible,
            active_label=annotation_active_label,
        )
        self.sync_annotation_controls(
            annotation_mask=annotation_mask,
            editing_enabled=annotation_editing_enabled,
            opacity=annotation_opacity,
            visible=annotation_visible,
            active_label=annotation_active_label,
            brush_radius=annotation_brush_radius,
            brush_mode=annotation_brush_mode,
        )
        self._initialize_contrast(patch_volume)
        self._sync_projection_controls()
        self._on_graph_projection_state_changed(
            self.slice_viewer.projection_mode(),
            self.slice_viewer.enabled_projection_orientations(),
        )
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
        layout.addWidget(self.overlay_opacity_control_bar)
        layout.addWidget(self._main_splitter, 1)
        apply_window_content_frame(self, central)
        self.setCentralWidget(central)
        self._font_scaler.apply()
        self._apply_initial_window_size()
        self._refresh_patch_history_panel()

    def _setup_menu(self) -> None:
        view_menu = self.menuBar().addMenu("&View")
        self.cursor_overlay_action = QAction("Show &Cursor Overlay", self)
        self.cursor_overlay_action.setCheckable(True)
        self.cursor_overlay_action.setChecked(True)
        self.cursor_overlay_action.toggled.connect(
            self.slice_viewer.set_cursor_overlay_visible
        )
        view_menu.addAction(self.cursor_overlay_action)

        self.segmentation_menu = self.menuBar().addMenu("&Segmentation")
        self.unload_current_segmentation_action = QAction(
            "&Unload Current Segmentation", self
        )
        self.unload_current_segmentation_action.triggered.connect(
            self.unload_current_segmentation_requested.emit
        )
        self.segmentation_menu.addAction(self.unload_current_segmentation_action)

        self.segmentation_menu.addSeparator()

        self.open_segmentation_config_action = QAction(
            "Open &Configuration Panel", self
        )
        self.open_segmentation_config_action.triggered.connect(
            self.open_segmentation_configuration_requested.emit
        )
        self.segmentation_menu.addAction(self.open_segmentation_config_action)

        tools_menu = self.menuBar().addMenu("&Tools")
        self.ruler_action = QAction("Show &Ruler", self)
        self.ruler_action.setCheckable(True)
        self.ruler_action.setChecked(True)
        self.ruler_action.toggled.connect(self.slice_viewer.set_ruler_visible)
        tools_menu.addAction(self.ruler_action)
        tools_menu.addSeparator()
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

        self.projection_mask_combo = QComboBox(panel)
        self.projection_mask_combo.addItem("---", None)
        self.projection_mask_combo.currentIndexChanged.connect(
            self._on_projection_mask_changed
        )

        self.projection_segmentation_checkbox = QCheckBox(panel)
        self.projection_segmentation_checkbox.setChecked(False)
        self.projection_segmentation_checkbox.toggled.connect(
            self._on_projection_segmentation_toggled
        )

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
        form.addRow("Mask:", self.projection_mask_combo)
        form.addRow("MIP the segmentation:", self.projection_segmentation_checkbox)
        form.addRow("Direction:", direction_row)
        return panel

    def _build_save_panel(self, parent: QWidget | None = None) -> QGroupBox:
        panel = QGroupBox("Patch Save", parent)
        layout = QVBoxLayout(panel)
        self.save_views_button = QPushButton("Save MIP/MinIP Image...", panel)
        self.save_views_button.clicked.connect(self._on_save_views_clicked)
        layout.addWidget(self.save_views_button)
        self.export_screenshot_button = QPushButton(
            "Export Viewer Screenshot...",
            panel,
        )
        self.export_screenshot_button.clicked.connect(
            self._on_export_viewer_screenshot_clicked
        )
        layout.addWidget(self.export_screenshot_button)
        resolution_row = QWidget(panel)
        resolution_layout = QHBoxLayout(resolution_row)
        resolution_layout.setContentsMargins(0, 0, 0, 0)
        self.screenshot_resolution_slider = QSlider(
            Qt.Orientation.Horizontal,
            resolution_row,
        )
        self.screenshot_resolution_slider.setRange(1, 200)
        self.screenshot_resolution_slider.setValue(100)
        self.screenshot_resolution_spinbox = QSpinBox(resolution_row)
        self.screenshot_resolution_spinbox.setRange(1, 200)
        self.screenshot_resolution_spinbox.setSuffix("%")
        self.screenshot_resolution_spinbox.setValue(100)
        self.screenshot_resolution_slider.valueChanged.connect(
            self.screenshot_resolution_spinbox.setValue
        )
        self.screenshot_resolution_spinbox.valueChanged.connect(
            self.screenshot_resolution_slider.setValue
        )
        self.screenshot_resolution_spinbox.valueChanged.connect(
            self._update_screenshot_output_dimensions
        )
        resolution_layout.addWidget(self.screenshot_resolution_slider, 1)
        resolution_layout.addWidget(self.screenshot_resolution_spinbox)
        layout.addWidget(resolution_row)
        self.screenshot_dimensions_label = QLabel("Output: —", panel)
        layout.addWidget(self.screenshot_dimensions_label)
        self.save_patch_button = QPushButton("Save Img Patch", panel)
        self.save_patch_button.clicked.connect(self._on_save_patch_clicked)
        layout.addWidget(self.save_patch_button)
        self.save_seg_patch_button = QPushButton("Save Seg Patch", panel)
        self.save_seg_patch_button.clicked.connect(self._on_save_seg_patch_clicked)
        layout.addWidget(self.save_seg_patch_button)
        self._refresh_seg_patch_save_enabled()
        self._update_screenshot_output_dimensions(100)
        return panel

    def _sync_projection_controls(self) -> None:
        self.slice_viewer.set_projection_mode(self.projection_mode_combo.currentText())
        self.slice_viewer.set_projection_segmentation_enabled(
            self.projection_segmentation_checkbox.isChecked()
        )
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

    def _on_projection_mask_changed(self, _index: int) -> None:
        segmentation_id = self.projection_mask_combo.currentData()
        mask_volume = (
            self._projection_mask_layers.get(segmentation_id)
            if isinstance(segmentation_id, str)
            else None
        )
        self.slice_viewer.set_projection_mask(mask_volume)

    def _on_projection_segmentation_toggled(self, enabled: bool) -> None:
        self.slice_viewer.set_projection_segmentation_enabled(enabled)

    def _active_overlay_opacity(self) -> float:
        if self._active_segmentation_kind == "annotation":
            return self._annotation_opacity
        return self._segmentation_opacity

    def _on_overlay_opacity_changed(self, opacity: float) -> None:
        normalized_opacity = min(max(float(opacity), 0.0), 1.0)
        if self._active_segmentation_kind == "annotation":
            self._annotation_opacity = normalized_opacity
            self.slice_viewer.set_annotation_overlay_opacity(normalized_opacity)
            self.annotation_panel.set_opacity(normalized_opacity)
        else:
            self._segmentation_opacity = normalized_opacity
            self.slice_viewer.set_segmentation_overlay_opacity(normalized_opacity)
        self.overlay_opacity_changed.emit(normalized_opacity)

    def _on_projection_direction_toggled(self, orientation: str, enabled: bool) -> None:
        self.slice_viewer.set_projection_enabled(orientation, enabled)

    def graph_status(self) -> dict[str, object]:
        summary = self.graph_state.summary()
        summary.update(
            {
                "session_id": self.graph_session_id,
                "source_image_path": (
                    None
                    if self._source_image_path is None
                    else str(self._source_image_path)
                ),
                "patch_shape": list(self._patch_size),
                "patch_bounds": (
                    None
                    if self._source_patch_bounds is None
                    else {
                        "x_start": self._source_patch_bounds.x_start,
                        "x_end": self._source_patch_bounds.x_end,
                        "y_start": self._source_patch_bounds.y_start,
                        "y_end": self._source_patch_bounds.y_end,
                        "z_start": self._source_patch_bounds.z_start,
                        "z_end": self._source_patch_bounds.z_end,
                    }
                ),
                "projection_mode": self.slice_viewer.projection_mode(),
                "projection_mask_id": self.selected_projection_mask_id(),
                "projection_mask_name": (
                    None
                    if self.selected_projection_mask_id() is None
                    else self.projection_mask_combo.currentText()
                ),
                "enabled_orientations": list(
                    self.slice_viewer.enabled_projection_orientations()
                ),
            }
        )
        voxel_graph = summary["voxel_graph"]
        assert isinstance(voxel_graph, dict)
        voxel_graph["nodes"] = [
            self.graph_node_payload(node)
            for node in sorted(
                self.graph_state.graph.nodes.values(),
                key=lambda node: node.id,
            )
        ]
        voxel_graph["edges"] = [
            {
                "start_node_id": edge.start_node_id,
                "end_node_id": edge.end_node_id,
                "control_patch_voxel": (
                    None
                    if edge not in self.graph_state.graph.curve_control_points
                    else [
                        float(value)
                        for value in self.graph_state.graph.curve_control_points[edge]
                    ]
                ),
            }
            for edge in sorted(self.graph_state.graph.edges)
        ]
        layers: dict[str, object] = {}
        for orientation in ("axial", "coronal", "sagittal"):
            layer = self.slice_viewer.graph_projected_layer(orientation)
            layers[orientation] = {
                "plane_shape": list(layer.plane_shape),
                "num_nodes": len(layer.nodes),
                "num_edges": len(layer.edges),
                "num_curved_edges": len(layer.curve_control_points),
                "nodes": [
                    {
                        "id": node.id,
                        "horizontal_index": _json_number(node.horizontal_index),
                        "vertical_index": _json_number(node.vertical_index),
                    }
                    for node in sorted(layer.nodes.values(), key=lambda node: node.id)
                ],
                "edges": [
                    {
                        "start_node_id": edge.start_node_id,
                        "end_node_id": edge.end_node_id,
                        "control_point": (
                            None
                            if edge not in layer.curve_control_points
                            else [
                                float(layer.curve_control_points[edge][0]),
                                float(layer.curve_control_points[edge][1]),
                            ]
                        ),
                    }
                    for edge in sorted(layer.edges)
                ],
            }
        summary["layers"] = layers
        return summary

    def graph_node_payload(
        self,
        node: GraphNode,
        orientation: Orientation | None = None,
    ) -> dict[str, object]:
        projections: dict[str, list[int | float]] = {}
        for view in ("axial", "coronal", "sagittal"):
            projected = self.slice_viewer.graph_projected_layer(view).nodes[node.id]
            projections[view] = [
                _json_number(projected.horizontal_index),
                _json_number(projected.vertical_index),
            ]
        source_voxel = None
        if self._source_patch_bounds is not None:
            source_voxel = [
                node.x + self._source_patch_bounds.x_start,
                node.y + self._source_patch_bounds.y_start,
                node.z + self._source_patch_bounds.z_start,
            ]
        payload: dict[str, object] = {
            "id": node.id,
            "patch_voxel": list(node.position()),
            "source_voxel": source_voxel,
            "projections": projections,
        }
        if orientation is not None:
            payload["horizontal_index"] = projections[orientation][0]
            payload["vertical_index"] = projections[orientation][1]
        return payload

    def set_graph_editing_enabled(self, enabled: bool) -> bool:
        target_enabled = bool(enabled)
        if not target_enabled:
            changed = self.graph_state.editing_enabled
            self.graph_state.exit_editing()
            self.graph_panel.set_editing_enabled(False)
            self._refresh_graph_panel_tool_state()
            self.slice_viewer.refresh_graph_overlay()
            return changed

        enabled_orientations = self.slice_viewer.enabled_projection_orientations()
        if not enabled_orientations:
            raise ValueError("Enable at least one MIP/MinIP projection first.")
        self.graph_state.visible = True
        self.graph_panel.set_visible_checked(True)
        active_view = self.slice_viewer.active_view()
        if active_view in enabled_orientations:
            self.graph_state.active_orientation = active_view
        elif self.graph_state.active_orientation not in enabled_orientations:
            self.graph_state.active_orientation = enabled_orientations[0]
        changed = not self.graph_state.editing_enabled
        self.graph_state.editing_enabled = True
        self.graph_panel.set_editing_enabled(True)
        self._refresh_graph_panel_tool_state()
        self.slice_viewer.refresh_graph_overlay()
        return changed

    def set_graph_display_options(
        self,
        *,
        visible: bool | None = None,
        opacity: float | None = None,
        node_size: int | None = None,
        edge_thickness: int | None = None,
    ) -> None:
        if visible is not None:
            self.graph_state.visible = bool(visible)
            self.graph_panel.set_visible_checked(self.graph_state.visible)
            if not self.graph_state.visible:
                self.graph_state.cancel_pending_edge()
                self.graph_state.cancel_pending_vector()
                self.graph_state.cancel_active_tool()
        if opacity is not None:
            self.graph_state.set_opacity(opacity)
            self.graph_panel.set_opacity(self.graph_state.opacity)
        if node_size is not None:
            self.graph_state.set_node_size(node_size)
            self.graph_panel.set_node_size(self.graph_state.node_size)
        if edge_thickness is not None:
            self.graph_state.set_edge_thickness(edge_thickness)
            self.graph_panel.set_edge_thickness(self.graph_state.edge_thickness)
        self.slice_viewer.refresh_graph_overlay()
        self._refresh_graph_panel_tool_state()

    def add_graph_node(
        self,
        orientation: Orientation,
        horizontal_index: int,
        vertical_index: int,
    ) -> GraphNode:
        self._validate_graph_edit_operation(orientation)
        voxel = self.slice_viewer.resolve_graph_projection_voxel(
            orientation,
            horizontal_index,
            vertical_index,
        )
        node = self.graph_state.graph.add_node(*voxel)
        self.graph_state.active_orientation = orientation
        self.slice_viewer.refresh_graph_overlay()
        return node

    def add_graph_voxel_node(self, x: int, y: int, z: int) -> GraphNode:
        self._validate_graph_editing()
        node = self.graph_state.graph.add_node(x, y, z)
        self.slice_viewer.refresh_graph_overlay()
        return node

    def delete_graph_node(self, orientation: Orientation, node_id: int) -> GraphNode:
        self._validate_graph_edit_operation(orientation)
        node = self.graph_state.graph.delete_node(node_id)
        self.graph_state.invalidate_node(node.id)
        self.slice_viewer.refresh_graph_overlay()
        self._refresh_graph_panel_tool_state()
        return node

    def begin_graph_edge(self, orientation: Orientation, node_id: int) -> None:
        self._validate_graph_edit_operation(orientation)
        self.graph_state.begin_edge(orientation, node_id)
        self.slice_viewer.refresh_graph_overlay()
        self._refresh_graph_panel_tool_state()

    def begin_graph_vector(self, orientation: Orientation, node_id: int) -> None:
        self._validate_graph_edit_operation(orientation)
        self.graph_state.begin_vector(orientation, node_id)
        self.slice_viewer.refresh_graph_overlay()
        self._refresh_graph_panel_tool_state()

    def add_graph_node_vector(
        self,
        orientation: Orientation,
        source_node_id: int,
        target_node_id: int,
    ) -> GraphVector:
        self._validate_graph_edit_operation(orientation)
        self._validate_projected_vector_length(
            orientation,
            source_node_id,
            target_node_id,
        )
        vector = self.graph_state.add_node_vector(
            orientation,
            source_node_id,
            target_node_id,
        )
        self.slice_viewer.refresh_graph_overlay()
        self._refresh_graph_panel_tool_state()
        return vector

    def add_graph_edge_vector(
        self,
        orientation: Orientation,
        first_node_id: int,
        second_node_id: int,
        kind: Literal["edge_tangent", "edge_normal"],
    ) -> GraphVector:
        self._validate_graph_edit_operation(orientation)
        self._validate_projected_vector_length(
            orientation,
            first_node_id,
            second_node_id,
        )
        vector = self.graph_state.add_edge_vector(
            orientation,
            GraphEdge.between(first_node_id, second_node_id),
            kind,
        )
        self.slice_viewer.refresh_graph_overlay()
        self._refresh_graph_panel_tool_state()
        return vector

    def flip_graph_vector(self, vector_id: int) -> GraphVector:
        vector = self.graph_state.vectors.get(int(vector_id))
        if vector is None:
            raise ValueError(f"Graph vector V{vector_id} does not exist.")
        self._validate_graph_edit_operation(vector.orientation)
        positions, spacing = self._graph_vector_geometry(vector.orientation)
        flipped = self.graph_state.flip_vector(vector.id, positions, spacing)
        self.slice_viewer.refresh_graph_overlay()
        self._refresh_graph_panel_tool_state()
        return flipped

    def delete_graph_vector(self, vector_id: int) -> GraphVector:
        vector = self.graph_state.vectors.get(int(vector_id))
        if vector is None:
            raise ValueError(f"Graph vector V{vector_id} does not exist.")
        self._validate_graph_edit_operation(vector.orientation)
        deleted = self.graph_state.delete_vector(vector.id)
        self.slice_viewer.refresh_graph_overlay()
        self._refresh_graph_panel_tool_state()
        return deleted

    def add_graph_edge(
        self,
        orientation: Orientation,
        first_node_id: int,
        second_node_id: int,
    ) -> GraphEdge:
        self._validate_graph_edit_operation(orientation)
        edge = self.graph_state.graph.add_edge(
            first_node_id,
            second_node_id,
        )
        self.graph_state.cancel_pending_edge()
        self.slice_viewer.refresh_graph_overlay()
        self._refresh_graph_panel_tool_state()
        return edge

    def delete_graph_edge(
        self,
        orientation: Orientation,
        first_node_id: int,
        second_node_id: int,
    ) -> GraphEdge:
        self._validate_graph_edit_operation(orientation)
        edge = self.graph_state.graph.delete_edge(
            first_node_id,
            second_node_id,
        )
        self.graph_state.invalidate_edge(edge)
        if (
            self.graph_state.selected_edge == edge
        ):
            self.graph_state.cancel_active_tool()
        self.slice_viewer.refresh_graph_overlay()
        self._refresh_graph_panel_tool_state()
        return edge

    def split_graph_edge(
        self,
        orientation: Orientation,
        first_node_id: int,
        second_node_id: int,
        horizontal_index: int,
        vertical_index: int,
    ) -> tuple[GraphNode, GraphEdge, GraphEdge]:
        self._validate_graph_edit_operation(orientation)
        original_edge = GraphEdge.between(first_node_id, second_node_id)
        projected_layer = self.slice_viewer.graph_projected_layer(orientation)
        parameter = nearest_projected_edge_parameter(
            projected_layer,
            original_edge,
            (horizontal_index, vertical_index),
        )
        result = self.graph_state.graph.split_edge_at_parameter(
            first_node_id,
            second_node_id,
            parameter,
        )
        self.graph_state.invalidate_edge(original_edge)
        if (
            self.graph_state.selected_edge == original_edge
        ):
            self.graph_state.cancel_active_tool()
        self.graph_state.active_orientation = orientation
        self.slice_viewer.refresh_graph_overlay()
        self._refresh_graph_panel_tool_state()
        return result

    def curve_graph_edge(
        self,
        orientation: Orientation,
        first_node_id: int,
        second_node_id: int,
        control_horizontal: float,
        control_vertical: float,
    ) -> GraphEdge:
        self._validate_graph_edit_operation(orientation)
        edge = GraphEdge.between(first_node_id, second_node_id)
        current_control = self.graph_state.graph.curve_control_point_or_midpoint(edge)
        control_point = self.slice_viewer.graph_control_point_from_projection(
            current_control,
            orientation,
            control_horizontal,
            control_vertical,
        )
        edge = self.graph_state.graph.set_curve_control_point(
            first_node_id,
            second_node_id,
            control_point,
        )
        self.graph_state.invalidate_edge_vectors(edge)
        self.graph_state.active_orientation = orientation
        if self.graph_state.selected_edge == edge:
            self.graph_state.selected_edge_orientation = orientation
        self.slice_viewer.refresh_graph_overlay()
        self._refresh_graph_panel_tool_state()
        return edge

    def straighten_graph_edge(
        self,
        orientation: Orientation,
        first_node_id: int,
        second_node_id: int,
    ) -> GraphEdge:
        self._validate_graph_edit_operation(orientation)
        edge = self.graph_state.graph.straighten_edge(
            first_node_id,
            second_node_id,
        )
        if self.graph_state.selected_edge == edge:
            self.graph_state.selected_edge = None
            self.graph_state.selected_edge_orientation = None
            self.graph_state.curve_drag_active = False
        self.slice_viewer.refresh_graph_overlay()
        self._refresh_graph_panel_tool_state()
        return edge

    def calculate_graph_angle(
        self,
        source_vector_id: int,
        target_vector_id: int,
    ) -> AngleMeasurement:
        source = self.graph_state.vectors.get(int(source_vector_id))
        if source is None:
            raise ValueError(f"Graph vector V{source_vector_id} does not exist.")
        self._validate_graph_edit_operation(source.orientation)
        positions, spacing = self._graph_vector_geometry(source.orientation)
        measurement = self.graph_state.calculate_angle(
            source_vector_id,
            target_vector_id,
            positions,
            spacing,
        )
        self.slice_viewer.refresh_graph_overlay()
        self._refresh_graph_panel_tool_state()
        return measurement

    def delete_graph_angle(self, measurement_id: int) -> AngleMeasurement:
        measurement = self.graph_state.delete_angle(measurement_id)
        self.slice_viewer.refresh_graph_overlay()
        self._refresh_graph_panel_tool_state()
        self.statusBar().showMessage(f"Deleted graph angle A{measurement.id}")
        return measurement

    def clear_graph_angles(self) -> int:
        count = self.graph_state.clear_angles()
        self.slice_viewer.refresh_graph_overlay()
        self._refresh_graph_panel_tool_state()
        self.statusBar().showMessage(f"Cleared {count} graph angle(s)")
        return count

    def clear_graph(self) -> tuple[int, int]:
        node_count, edge_count = self.graph_state.clear_graph()
        self.slice_viewer.refresh_graph_overlay()
        self._refresh_graph_panel_tool_state()
        self.statusBar().showMessage(
            f"Cleared {node_count} graph node(s) and {edge_count} edge(s)"
        )
        return node_count, edge_count

    def _validate_graph_edit_operation(self, orientation: Orientation) -> None:
        self._validate_graph_editing()
        if not self.slice_viewer.projection_enabled(orientation):
            raise ValueError(
                f"The {orientation} viewer is not showing a MIP/MinIP projection."
            )

    def _validate_graph_editing(self) -> None:
        if not self.graph_state.editing_enabled:
            raise ValueError("Graph mode is not active.")
        if not self.graph_state.visible:
            raise ValueError("Graph visibility must be enabled before editing.")
        if not self.slice_viewer.enabled_projection_orientations():
            raise ValueError("Enable at least one MIP/MinIP projection first.")

    def _on_graph_activation_requested(self) -> None:
        try:
            enabled = not self.graph_state.editing_enabled
            self.set_graph_editing_enabled(enabled)
        except ValueError as exc:
            self.statusBar().showMessage(str(exc))
            return
        self.statusBar().showMessage(
            "Graph mode activated" if enabled else "Graph mode exited"
        )

    def _on_graph_visibility_changed(self, visible: bool) -> None:
        self.set_graph_display_options(visible=visible)

    def _on_graph_opacity_changed(self, opacity: float) -> None:
        self.set_graph_display_options(opacity=opacity)

    def _on_graph_node_size_changed(self, node_size: int) -> None:
        self.set_graph_display_options(node_size=node_size)

    def _on_graph_edge_thickness_changed(self, edge_thickness: int) -> None:
        self.set_graph_display_options(edge_thickness=edge_thickness)

    def _on_graph_projection_state_changed(
        self,
        mode: str,
        enabled_orientations: object,
    ) -> None:
        enabled = tuple(
            orientation
            for orientation in ("axial", "coronal", "sagittal")
            if isinstance(enabled_orientations, tuple)
            and orientation in enabled_orientations
        )
        mode_changed = mode != self._graph_projection_mode
        self._graph_projection_mode = mode
        if mode_changed:
            self.graph_state.cancel_pending_edge()
            self.graph_state.cancel_pending_vector()
            self.graph_state.cancel_active_tool()
        self.graph_panel.set_projection_available(bool(enabled))
        if self.graph_state.editing_enabled and not enabled:
            self.set_graph_editing_enabled(False)
            self.statusBar().showMessage(
                "Graph mode exited because all projections were disabled"
            )
            return
        if self.graph_state.active_orientation not in enabled:
            self.graph_state.cancel_pending_edge()
            self.graph_state.active_orientation = enabled[0] if enabled else None
        if self.graph_state.pending_vector_orientation not in enabled:
            self.graph_state.cancel_pending_vector()
        transient_orientation = self.graph_state.selected_edge_orientation
        if self.graph_state.angle_source_vector_id is not None:
            transient_orientation = self.graph_state.vectors[
                self.graph_state.angle_source_vector_id
            ].orientation
        if transient_orientation is not None and transient_orientation not in enabled:
            self.graph_state.cancel_active_tool()
        self.slice_viewer.refresh_graph_overlay()
        self._refresh_graph_panel_tool_state()

    def _on_graph_orientation_interacted(self, orientation: str) -> None:
        if orientation in self.slice_viewer.enabled_projection_orientations():
            self.graph_state.active_orientation = orientation  # type: ignore[assignment]

    def _on_graph_context_requested(
        self,
        orientation: str,
        projection_position: object,
        hit: object,
        global_position: object,
    ) -> None:
        if orientation not in ("axial", "coronal", "sagittal"):
            return
        if (
            not isinstance(projection_position, tuple)
            or len(projection_position) != 2
            or not isinstance(hit, dict)
        ):
            return
        graph_orientation: Orientation = orientation  # type: ignore[assignment]
        self.graph_state.active_orientation = graph_orientation
        menu = QMenu(self)
        hit_kind = hit.get("kind")
        if hit_kind == "node":
            node_id = int(hit["node_id"])
            delete_action = menu.addAction("Delete this node")
            delete_action.triggered.connect(
                lambda _checked=False: self._delete_graph_node_from_ui(
                    graph_orientation,
                    node_id,
                )
            )
            edge_action = menu.addAction("Create an edge from here")
            edge_action.triggered.connect(
                lambda _checked=False: self._begin_graph_edge_from_ui(
                    graph_orientation,
                    node_id,
                )
            )
            vector_action = menu.addAction("Create a vector from this node")
            vector_action.triggered.connect(
                lambda _checked=False: self._begin_graph_vector_from_ui(
                    graph_orientation,
                    node_id,
                )
            )
        elif hit_kind == "vector":
            vector_ids = hit.get("vector_ids")
            edge_start = hit.get("edge_start_node_id")
            edge_end = hit.get("edge_end_node_id")
            valid_vector_ids = (
                [
                    int(vector_id)
                    for vector_id in vector_ids
                    if int(vector_id) in self.graph_state.vectors
                ]
                if isinstance(vector_ids, list)
                else []
            )
            if (
                len(valid_vector_ids) == 1
                and edge_start is None
                and edge_end is None
            ):
                self._populate_graph_vector_context_menu(
                    menu,
                    valid_vector_ids[0],
                )
            else:
                for vector_id in valid_vector_ids:
                    vector_menu = menu.addMenu(f"Vector V{vector_id}")
                    self._populate_graph_vector_context_menu(
                        vector_menu,
                        vector_id,
                    )
            if edge_start is not None and edge_end is not None:
                menu.addSeparator()
                edge_menu = menu.addMenu(
                    f"Edge {int(edge_start)}-{int(edge_end)}"
                )
                self._populate_graph_edge_context_menu(
                    edge_menu,
                    graph_orientation,
                    int(edge_start),
                    int(edge_end),
                    int(projection_position[0]),
                    int(projection_position[1]),
                )
        elif hit_kind == "edge":
            start_node_id = int(hit["start_node_id"])
            end_node_id = int(hit["end_node_id"])
            self._populate_graph_edge_context_menu(
                menu,
                graph_orientation,
                start_node_id,
                end_node_id,
                int(projection_position[0]),
                int(projection_position[1]),
            )
        else:
            horizontal_index = int(projection_position[0])
            vertical_index = int(projection_position[1])
            create_action = menu.addAction("Create node here")
            create_action.triggered.connect(
                lambda _checked=False: self._add_graph_node_from_ui(
                    graph_orientation,
                    horizontal_index,
                    vertical_index,
                )
            )
        if not menu.isEmpty():
            menu.exec(global_position)

    def _populate_graph_vector_context_menu(
        self,
        menu: QMenu,
        vector_id: int,
    ) -> None:
        angle_label = (
            "Select as angle source"
            if self.graph_state.angle_source_vector_id is None
            else "Select as angle target"
        )
        angle_action = menu.addAction(angle_label)
        angle_action.triggered.connect(
            lambda _checked=False: self._select_graph_vector_for_angle_from_ui(
                vector_id
            )
        )
        flip_action = menu.addAction("Flip vector")
        flip_action.triggered.connect(
            lambda _checked=False: self._flip_graph_vector_from_ui(vector_id)
        )
        delete_action = menu.addAction("Delete vector")
        delete_action.triggered.connect(
            lambda _checked=False: self._delete_graph_vector_from_ui(vector_id)
        )

    def _populate_graph_edge_context_menu(
        self,
        menu: QMenu,
        orientation: Orientation,
        start_node_id: int,
        end_node_id: int,
        horizontal_index: int,
        vertical_index: int,
    ) -> None:
        edge = GraphEdge.between(start_node_id, end_node_id)
        create_node_action = menu.addAction("Create a node here")
        create_node_action.triggered.connect(
            lambda _checked=False: self._split_graph_edge_from_ui(
                orientation,
                start_node_id,
                end_node_id,
                horizontal_index,
                vertical_index,
            )
        )
        delete_action = menu.addAction("Delete this edge")
        delete_action.triggered.connect(
            lambda _checked=False: self._delete_graph_edge_from_ui(
                orientation,
                start_node_id,
                end_node_id,
            )
        )
        menu.addSeparator()
        if edge not in self.graph_state.graph.curve_control_points:
            for kind, label in (
                ("edge_normal", "Display the normal vector"),
                ("edge_tangent", "Display the tangent vector"),
            ):
                existing = self.graph_state.vector_for_edge(
                    orientation,
                    edge,
                    kind,  # type: ignore[arg-type]
                )
                action = menu.addAction(
                    f"{label.removeprefix('Display the ')} displayed"
                    if existing is not None
                    else label
                )
                action.setEnabled(existing is None)
                action.triggered.connect(
                    lambda _checked=False, vector_kind=kind: (
                        self._add_graph_edge_vector_from_ui(
                            orientation,
                            start_node_id,
                            end_node_id,
                            vector_kind,  # type: ignore[arg-type]
                        )
                    )
                )
        curve_action = menu.addAction("Curve Edge")
        curve_action.triggered.connect(
            lambda _checked=False: self._select_graph_curve_from_ui(
                orientation,
                start_node_id,
                end_node_id,
            )
        )
        straighten_action = menu.addAction("Straighten Edge")
        straighten_action.setEnabled(edge in self.graph_state.graph.curve_control_points)
        straighten_action.triggered.connect(
            lambda _checked=False: self._straighten_graph_edge_from_ui(
                orientation,
                start_node_id,
                end_node_id,
            )
        )

    def _add_graph_node_from_ui(
        self,
        orientation: Orientation,
        horizontal_index: int,
        vertical_index: int,
    ) -> None:
        try:
            node = self.add_graph_node(
                orientation,
                horizontal_index,
                vertical_index,
            )
        except ValueError as exc:
            self.statusBar().showMessage(str(exc))
            return
        self.statusBar().showMessage(
            f"Created {orientation} graph node {node.id} at {node.position()}"
        )

    def _delete_graph_node_from_ui(
        self,
        orientation: Orientation,
        node_id: int,
    ) -> None:
        try:
            self.delete_graph_node(orientation, node_id)
        except ValueError as exc:
            self.statusBar().showMessage(str(exc))
            return
        self.statusBar().showMessage(f"Deleted {orientation} graph node {node_id}")

    def _begin_graph_edge_from_ui(
        self,
        orientation: Orientation,
        node_id: int,
    ) -> None:
        try:
            self.begin_graph_edge(orientation, node_id)
        except ValueError as exc:
            self.statusBar().showMessage(str(exc))
            return
        self.statusBar().showMessage(
            f"Select another {orientation} graph node to complete the edge"
        )

    def _begin_graph_vector_from_ui(
        self,
        orientation: Orientation,
        node_id: int,
    ) -> None:
        try:
            self.begin_graph_vector(orientation, node_id)
        except ValueError as exc:
            self.statusBar().showMessage(str(exc))
            return
        self.statusBar().showMessage(
            f"Select a target in the {orientation} projection"
        )

    def _on_graph_vector_completion_requested(
        self,
        orientation: str,
        target_node_id: object,
        projection_position: object,
    ) -> None:
        pending_orientation = self.graph_state.pending_vector_orientation
        source_node_id = self.graph_state.pending_vector_source_node_id
        if pending_orientation is None or source_node_id is None:
            return
        if orientation != pending_orientation:
            self.statusBar().showMessage(
                f"Complete the vector in the {pending_orientation} projection."
            )
            return
        if (
            orientation not in ("axial", "coronal", "sagittal")
            or not isinstance(projection_position, tuple)
            or len(projection_position) != 2
        ):
            return
        graph_orientation: Orientation = orientation  # type: ignore[assignment]
        created_node: GraphNode | None = None
        try:
            if target_node_id is None:
                positions, _ = self._graph_vector_geometry(graph_orientation)
                source_projection = positions[source_node_id]
                if float(
                    np.hypot(
                        float(projection_position[0]) - source_projection[0],
                        float(projection_position[1]) - source_projection[1],
                    )
                ) <= 0.0:
                    raise ValueError(
                        "Vector target resolves to the source projection; "
                        "choose another target."
                    )
                voxel = self.slice_viewer.resolve_graph_projection_voxel(
                    graph_orientation,
                    int(projection_position[0]),
                    int(projection_position[1]),
                )
                if self.graph_state.graph.nodes[source_node_id].position() == voxel:
                    raise ValueError(
                        "Vector target resolves to the source voxel; choose another target."
                    )
                created_node = self.graph_state.graph.add_node(*voxel)
                normalized_target_id = created_node.id
            else:
                normalized_target_id = int(target_node_id)
            self._validate_projected_vector_length(
                graph_orientation,
                source_node_id,
                normalized_target_id,
            )
            vector = self.graph_state.add_node_vector(
                graph_orientation,
                source_node_id,
                normalized_target_id,
            )
        except ValueError as exc:
            if created_node is not None:
                self.graph_state.graph.delete_node(created_node.id)
            self.statusBar().showMessage(str(exc))
            return
        self.slice_viewer.refresh_graph_overlay()
        self._refresh_graph_panel_tool_state()
        suffix = (
            f" and target node {created_node.id}"
            if created_node is not None
            else ""
        )
        self.statusBar().showMessage(f"Created vector V{vector.id}{suffix}")

    def _add_graph_edge_vector_from_ui(
        self,
        orientation: Orientation,
        start_node_id: int,
        end_node_id: int,
        kind: Literal["edge_tangent", "edge_normal"],
    ) -> None:
        try:
            vector = self.add_graph_edge_vector(
                orientation,
                start_node_id,
                end_node_id,
                kind,
            )
        except ValueError as exc:
            self.statusBar().showMessage(str(exc))
            return
        self.statusBar().showMessage(f"Displayed graph vector V{vector.id}")

    def _flip_graph_vector_from_ui(self, vector_id: int) -> None:
        try:
            vector = self.flip_graph_vector(vector_id)
        except ValueError as exc:
            self.statusBar().showMessage(str(exc))
            return
        self.statusBar().showMessage(f"Flipped graph vector V{vector.id}")

    def _delete_graph_vector_from_ui(self, vector_id: int) -> None:
        try:
            vector = self.delete_graph_vector(vector_id)
        except ValueError as exc:
            self.statusBar().showMessage(str(exc))
            return
        self.statusBar().showMessage(f"Deleted graph vector V{vector.id}")

    def _select_graph_vector_for_angle_from_ui(self, vector_id: int) -> None:
        if self.graph_state.active_tool != "calculate_angle":
            self.graph_state.activate_angle_tool()
        self._on_graph_angle_vector_selected(
            self.graph_state.vectors[vector_id].orientation,
            vector_id,
        )

    def _on_graph_edge_completion_requested(
        self,
        orientation: str,
        node_id: int,
    ) -> None:
        pending_orientation = self.graph_state.pending_edge_orientation
        pending_node_id = self.graph_state.pending_edge_node_id
        if pending_node_id is None:
            return
        if orientation not in ("axial", "coronal", "sagittal"):
            return
        try:
            edge = self.add_graph_edge(
                orientation,  # type: ignore[arg-type]
                pending_node_id,
                node_id,
            )
        except ValueError as exc:
            self.statusBar().showMessage(str(exc))
            return
        self.statusBar().showMessage(
            "Created graph edge "
            f"{edge.start_node_id}-{edge.end_node_id} from {pending_orientation} "
            f"to {orientation}"
        )

    def _delete_graph_edge_from_ui(
        self,
        orientation: Orientation,
        start_node_id: int,
        end_node_id: int,
    ) -> None:
        try:
            self.delete_graph_edge(orientation, start_node_id, end_node_id)
        except ValueError as exc:
            self.statusBar().showMessage(str(exc))
            return
        self.statusBar().showMessage(
            f"Deleted {orientation} graph edge {start_node_id}-{end_node_id}"
        )

    def _split_graph_edge_from_ui(
        self,
        orientation: Orientation,
        start_node_id: int,
        end_node_id: int,
        horizontal_index: int,
        vertical_index: int,
    ) -> None:
        try:
            node, first_edge, second_edge = self.split_graph_edge(
                orientation,
                start_node_id,
                end_node_id,
                horizontal_index,
                vertical_index,
            )
        except ValueError as exc:
            self.statusBar().showMessage(str(exc))
            return
        self.statusBar().showMessage(
            f"Created {orientation} graph node {node.id} and split edge "
            f"{start_node_id}-{end_node_id} into "
            f"{first_edge.start_node_id}-{first_edge.end_node_id} and "
            f"{second_edge.start_node_id}-{second_edge.end_node_id}"
        )

    def _cancel_pending_graph_edge(self) -> None:
        if self.graph_state.pending_edge_node_id is None:
            return
        self.graph_state.cancel_pending_edge()
        self.slice_viewer.refresh_graph_overlay()
        self._refresh_graph_panel_tool_state()
        self.statusBar().showMessage("Graph edge creation canceled")

    def _cancel_pending_graph_vector(self) -> None:
        if self.graph_state.pending_vector_source_node_id is None:
            return
        self.graph_state.cancel_pending_vector()
        self.slice_viewer.refresh_graph_overlay()
        self._refresh_graph_panel_tool_state()
        self.statusBar().showMessage("Graph vector creation canceled")

    def _cancel_graph_interaction(self) -> None:
        if self.graph_state.pending_edge_node_id is not None:
            self._cancel_pending_graph_edge()
            return
        if self.graph_state.pending_vector_source_node_id is not None:
            self._cancel_pending_graph_vector()
            return
        if self.graph_state.active_tool is None:
            return
        tool = self.graph_state.active_tool
        self.graph_state.cancel_active_tool()
        self.slice_viewer.refresh_graph_overlay()
        self._refresh_graph_panel_tool_state()
        self.statusBar().showMessage(
            "Angle selection canceled" if tool == "calculate_angle" else "Curve tool exited"
        )

    def _on_graph_curve_tool_requested(self, enabled: bool) -> None:
        if not enabled:
            if self.graph_state.active_tool == "curve_edge":
                self.graph_state.cancel_active_tool()
        else:
            if not self.graph_state.editing_enabled:
                self._refresh_graph_panel_tool_state()
                return
            self.graph_state.activate_curve_tool()
            self.statusBar().showMessage("Select an existing graph edge to curve")
        self.slice_viewer.refresh_graph_overlay()
        self._refresh_graph_panel_tool_state()

    def _on_graph_calculate_angle_requested(self, enabled: bool) -> None:
        if not self.graph_state.editing_enabled:
            self._refresh_graph_panel_tool_state()
            return
        if enabled:
            self.graph_state.activate_angle_tool()
            message = "Select source vector"
        elif self.graph_state.active_tool == "calculate_angle":
            self.graph_state.cancel_active_tool()
            message = "Angle tool exited"
        else:
            message = ""
        self.slice_viewer.refresh_graph_overlay()
        self._refresh_graph_panel_tool_state()
        if message:
            self.statusBar().showMessage(message)

    def _on_graph_curve_edge_selected(
        self,
        orientation: str,
        start_node_id: int,
        end_node_id: int,
    ) -> None:
        if orientation not in ("axial", "coronal", "sagittal"):
            return
        try:
            self.graph_state.select_curve_edge(
                orientation,  # type: ignore[arg-type]
                start_node_id,
                end_node_id,
            )
        except ValueError as exc:
            self.statusBar().showMessage(str(exc))
            return
        self.slice_viewer.refresh_graph_overlay()
        self._refresh_graph_panel_tool_state()
        self.statusBar().showMessage("Drag the curve control point")

    def _on_graph_curve_control_changed(
        self,
        orientation: str,
        start_node_id: int,
        end_node_id: int,
        horizontal: float,
        vertical: float,
    ) -> None:
        if orientation not in ("axial", "coronal", "sagittal"):
            return
        try:
            self.curve_graph_edge(
                orientation,  # type: ignore[arg-type]
                start_node_id,
                end_node_id,
                horizontal,
                vertical,
            )
        except ValueError as exc:
            self.statusBar().showMessage(str(exc))
            return
        self.slice_viewer.refresh_graph_overlay()

    def _on_graph_curve_drag_state_changed(self, dragging: bool) -> None:
        self.graph_state.curve_drag_active = bool(dragging)
        self._refresh_graph_panel_tool_state()

    def _on_graph_angle_vector_selected(
        self,
        orientation: str,
        vector_id: int,
    ) -> None:
        if orientation not in ("axial", "coronal", "sagittal"):
            return
        vector = self.graph_state.vectors.get(int(vector_id))
        if vector is None:
            self.statusBar().showMessage(f"Graph vector V{vector_id} does not exist.")
            return
        try:
            positions, spacing = self._graph_vector_geometry(vector.orientation)
            measurement = self.graph_state.select_angle_vector(
                vector.id,
                positions,
                spacing,
            )
        except ValueError as exc:
            self.statusBar().showMessage(str(exc))
            return
        self.slice_viewer.refresh_graph_overlay()
        self._refresh_graph_panel_tool_state()
        if measurement is None:
            self.statusBar().showMessage(
                f"Selected V{vector.id} as source; select target vector"
            )
        else:
            self.statusBar().showMessage(
                f"Calculated A{measurement.id}: "
                f"{measurement.angle_degrees:.1f}°; select next source vector"
            )

    def _select_graph_curve_from_ui(
        self,
        orientation: Orientation,
        start_node_id: int,
        end_node_id: int,
    ) -> None:
        self.graph_state.activate_curve_tool()
        self._on_graph_curve_edge_selected(
            orientation,
            start_node_id,
            end_node_id,
        )

    def _straighten_graph_edge_from_ui(
        self,
        orientation: Orientation,
        start_node_id: int,
        end_node_id: int,
    ) -> None:
        try:
            self.straighten_graph_edge(
                orientation,
                start_node_id,
                end_node_id,
            )
        except ValueError as exc:
            self.statusBar().showMessage(str(exc))
            return
        self.statusBar().showMessage(
            f"Straightened {orientation} graph edge {start_node_id}-{end_node_id}"
        )

    def _on_graph_straighten_requested(self) -> None:
        orientation = self.graph_state.selected_edge_orientation
        edge = self.graph_state.selected_edge
        if orientation is None or edge is None:
            return
        self._straighten_graph_edge_from_ui(
            orientation,
            edge.start_node_id,
            edge.end_node_id,
        )

    def _refresh_graph_panel_tool_state(self) -> None:
        selected_curved = False
        if self.graph_state.selected_edge is not None:
            selected_curved = (
                self.graph_state.selected_edge
                in self.graph_state.graph.curve_control_points
            )
        self.graph_panel.set_tool_state(
            active_tool=self.graph_state.active_tool,
            selected_edge_curved=selected_curved,
            angle_source_vector_id=self.graph_state.angle_source_vector_id,
            angle_source_color=(
                None
                if self.graph_state.angle_source_vector_id is None
                else self.graph_state.vectors[
                    self.graph_state.angle_source_vector_id
                ].color
            ),
            measurements=tuple(
                (
                    measurement.id,
                    measurement.source_vector_id,
                    measurement.target_vector_id,
                    measurement.angle_degrees,
                )
                for measurement in self.graph_state.angle_measurements.values()
            ),
            has_graph_elements=bool(
                self.graph_state.graph.nodes or self.graph_state.graph.edges
            ),
        )

    def _graph_vector_geometry(
        self,
        orientation: Orientation,
    ) -> tuple[dict[int, tuple[float, float]], tuple[float, float]]:
        layer = self.slice_viewer.graph_projected_layer(orientation)
        return (
            {node.id: node.position() for node in layer.nodes.values()},
            self._graph_in_plane_spacing(orientation),
        )

    def _validate_projected_vector_length(
        self,
        orientation: Orientation,
        source_node_id: int,
        target_node_id: int,
    ) -> None:
        positions, _ = self._graph_vector_geometry(orientation)
        try:
            source = positions[int(source_node_id)]
            target = positions[int(target_node_id)]
        except KeyError as exc:
            raise ValueError(f"Graph node {exc.args[0]} does not exist.") from exc
        if float(np.hypot(target[0] - source[0], target[1] - source[1])) <= 0.0:
            raise ValueError(
                f"The selected nodes form a zero-length vector in {orientation}."
            )

    def _graph_in_plane_spacing(
        self,
        orientation: Orientation,
    ) -> tuple[float, float]:
        oriented = build_oriented_volume(
            self._patch_volume.data,
            self._patch_volume.affine,
        )
        unit_scale = spatial_unit_to_mm(self._patch_volume.header.get_xyzt_units()[0])
        spacings = display_voxel_spacing_mm(
            oriented.affine,
            oriented.display_to_source_affine,
            unit_scale,
        )
        horizontal_axis, vertical_axis, _ = plane_axes_for_orientation(orientation)
        return (spacings[horizontal_axis], spacings[vertical_axis])

    def _on_graph_layers_cleared(self, orientations: object) -> None:
        self._refresh_graph_panel_tool_state()
        if isinstance(orientations, tuple) and orientations:
            self.statusBar().showMessage(
                "Cleared graph layers after projection shape changed: "
                + ", ".join(str(value) for value in orientations)
            )

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

    def _on_save_seg_patch_clicked(self) -> None:
        overlay_patch = self._active_overlay_patch_volume()
        if overlay_patch is None:
            self.statusBar().showMessage("No active segmentation patch to save")
            return

        selected_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Segmentation Patch",
            self._default_seg_patch_filename(),
            "NIfTI Files (*.nii.gz *.nii);;All Files (*)",
        )
        if not selected_path:
            self.statusBar().showMessage("Segmentation patch save canceled")
            return

        try:
            saved_path = save_patch_nifti(overlay_patch, selected_path)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Save Segmentation Patch Failed", str(exc))
            self.statusBar().showMessage("Segmentation patch save failed")
            return

        self.statusBar().showMessage(f"Segmentation patch saved: {saved_path}")

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

    def _on_export_viewer_screenshot_clicked(self) -> None:
        selected_path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export Patch Triplanar Viewer",
            self._default_screenshot_filename(),
            "PNG Image (*.png);;JPEG Image (*.jpg *.jpeg);;All Files (*)",
        )
        if not selected_path:
            self.statusBar().showMessage("Viewer screenshot export canceled")
            return
        try:
            export_path, _ = self._resolve_views_export_target(
                selected_path,
                selected_filter,
            )
            saved_path, output_size = self.export_viewer_screenshot(
                export_path,
                self.screenshot_resolution_spinbox.value(),
            )
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Screenshot Export Failed", str(exc))
            self.statusBar().showMessage("Viewer screenshot export failed")
            return
        self.statusBar().showMessage(
            f"Saved viewer screenshot {output_size[0]}×{output_size[1]}: {saved_path}"
        )

    def export_viewer_screenshot(
        self,
        path: str | Path,
        resolution_percent: int = 100,
    ) -> tuple[Path, tuple[int, int]]:
        percentage = int(resolution_percent)
        if not 1 <= percentage <= 200:
            raise ValueError("Screenshot resolution must be between 1 and 200 percent.")
        output_path = Path(path)
        suffix = output_path.suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg"}:
            raise ValueError("Screenshot path must end with .png, .jpg, or .jpeg.")
        parent = output_path.parent
        if not parent.exists():
            raise ValueError(f"Screenshot directory does not exist: {parent}")
        if not parent.is_dir():
            raise ValueError(f"Screenshot parent path is not a directory: {parent}")
        if not os.access(parent, os.W_OK):
            raise ValueError(f"Screenshot directory is not writable: {parent}")

        native_width = max(self.slice_viewer.width(), 1)
        native_height = max(self.slice_viewer.height(), 1)
        output_width = max(1, round(native_width * percentage / 100.0))
        output_height = max(1, round(native_height * percentage / 100.0))
        image = QImage(
            output_width,
            output_height,
            QImage.Format.Format_ARGB32,
        )
        if image.isNull():
            raise ValueError(
                f"Unable to allocate screenshot image {output_width}×{output_height}."
            )
        image.fill(QColor(18, 18, 18))
        painter = QPainter(image)
        if not painter.isActive():
            raise ValueError("Unable to initialize screenshot rendering.")
        try:
            scale = percentage / 100.0
            painter.scale(scale, scale)
            self.slice_viewer.render(painter, QPoint())
        finally:
            painter.end()

        format_name = b"PNG" if suffix == ".png" else b"JPG"
        writer = QImageWriter(str(output_path), format_name)
        if format_name == b"JPG":
            writer.setQuality(95)
        if not writer.write(image):
            error = writer.errorString() or "unknown image writer error"
            raise ValueError(f"Screenshot save failed: {error}")
        return output_path, (output_width, output_height)

    def _update_screenshot_output_dimensions(self, percentage: int) -> None:
        if not hasattr(self, "screenshot_dimensions_label"):
            return
        width = max(1, round(max(self.slice_viewer.width(), 1) * percentage / 100.0))
        height = max(
            1,
            round(max(self.slice_viewer.height(), 1) * percentage / 100.0),
        )
        self.screenshot_dimensions_label.setText(f"Output: {width} × {height} px")

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

    def _default_screenshot_filename(self) -> str:
        stem = Path(self._default_patch_filename()).stem
        if stem.endswith(".nii"):
            stem = stem[:-4]
        return str(Path.home() / f"{stem}_triplanar.png")

    def _default_seg_patch_filename(self) -> str:
        stem = Path(self._default_patch_filename()).stem
        if stem.endswith(".nii"):
            stem = stem[:-4]
        suffix = "annotation" if self._segmentation_patch_volume is None else "seg"
        return str(Path.home() / f"{stem}_{suffix}.nii.gz")

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
                self._draw_export_overlays(
                    painter,
                    projection_planes,
                    title.lower(),
                    x_offset,
                    margin + title_height,
                    scaled_image.width(),
                    scaled_image.height(),
                )
                x_offset += scaled_image.width() + panel_gap
        finally:
            painter.end()

        return canvas

    def _draw_export_overlays(
        self,
        painter: QPainter,
        projection_planes: dict[str, np.ndarray | dict[str, np.ndarray]],
        orientation_title: str,
        x_offset: int,
        y_offset: int,
        target_width: int,
        target_height: int,
    ) -> None:
        segmentation_planes = projection_planes.get("segmentation")
        if isinstance(segmentation_planes, dict):
            segmentation_plane = segmentation_planes.get(orientation_title)
            if segmentation_plane is not None:
                self._draw_segmentation_export_overlay(
                    painter,
                    segmentation_plane,
                    x_offset,
                    y_offset,
                    target_width,
                    target_height,
                )

        annotation_planes = projection_planes.get("annotation")
        if isinstance(annotation_planes, dict) and self._annotation_visible:
            annotation_plane = annotation_planes.get(orientation_title)
            if annotation_plane is not None:
                self._draw_annotation_export_overlay(
                    painter,
                    annotation_plane,
                    x_offset,
                    y_offset,
                    target_width,
                    target_height,
                )

    def _draw_segmentation_export_overlay(
        self,
        painter: QPainter,
        plane: np.ndarray,
        x_offset: int,
        y_offset: int,
        target_width: int,
        target_height: int,
    ) -> None:
        overlay = build_segmentation_overlay_rgba(
            plane,
            opacity=self.slice_viewer.segmentation_overlay_opacity(),
        )
        if not np.any(overlay[..., 3]):
            return
        self._draw_rgba_export_overlay(
            painter, overlay, x_offset, y_offset, target_width, target_height
        )

    def _draw_annotation_export_overlay(
        self,
        painter: QPainter,
        plane: np.ndarray,
        x_offset: int,
        y_offset: int,
        target_width: int,
        target_height: int,
    ) -> None:
        overlay = build_annotation_overlay_rgba(
            plane,
            opacity=self._annotation_opacity,
            active_label=self._annotation_active_label,
        )
        if not np.any(overlay[..., 3]):
            return
        self._draw_rgba_export_overlay(
            painter, overlay, x_offset, y_offset, target_width, target_height
        )

    @staticmethod
    def _draw_rgba_export_overlay(
        painter: QPainter,
        overlay: np.ndarray,
        x_offset: int,
        y_offset: int,
        target_width: int,
        target_height: int,
    ) -> None:
        height, width, _ = overlay.shape
        contiguous = np.ascontiguousarray(overlay)
        overlay_image = QImage(
            contiguous.data,
            width,
            height,
            width * 4,
            QImage.Format.Format_RGBA8888,
        ).copy()
        painter.drawImage(
            x_offset,
            y_offset,
            overlay_image.scaled(
                target_width,
                target_height,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.FastTransformation,
            ),
        )

    def _compute_projection_planes_for_export(
        self,
    ) -> dict[str, np.ndarray | dict[str, np.ndarray]] | None:
        if self._patch_data.ndim != 3:
            return None
        mode = self._current_projection_mode_for_export()
        volume = build_oriented_volume(
            self._patch_volume.data,
            self._patch_volume.affine,
        ).display_data
        selected_mask = self.selected_projection_mask_volume()
        mask_data = (
            None
            if selected_mask is None
            else build_oriented_volume(
                selected_mask.data,
                selected_mask.affine,
            ).display_data
        )
        planes: dict[str, np.ndarray | dict[str, np.ndarray]] = {
            "axial": project_oriented_volume(volume, "axial", mode, mask=mask_data),
            "coronal": project_oriented_volume(
                volume, "coronal", mode, mask=mask_data
            ),
            "sagittal": project_oriented_volume(
                volume, "sagittal", mode, mask=mask_data
            ),
        }
        if (
            self.projection_segmentation_checkbox.isChecked()
            and self._active_segmentation_kind == "file"
            and self._segmentation_patch_volume is not None
        ):
            segmentation_volume = build_oriented_volume(
                self._segmentation_patch_volume.data,
                self._segmentation_patch_volume.affine,
            ).display_data
            planes["segmentation"] = {
                "axial": project_oriented_volume(segmentation_volume, "axial", "MIP"),
                "coronal": project_oriented_volume(segmentation_volume, "coronal", "MIP"),
                "sagittal": project_oriented_volume(segmentation_volume, "sagittal", "MIP"),
            }
        if (
            self.projection_segmentation_checkbox.isChecked()
            and self._active_segmentation_kind == "annotation"
            and self._annotation_patch_mask is not None
        ):
            annotation_volume = build_oriented_volume(
                self._annotation_patch_mask.data,
                self._annotation_patch_mask.affine,
            ).display_data
            planes["annotation"] = {
                "axial": project_oriented_volume(annotation_volume, "axial", "MIP"),
                "coronal": project_oriented_volume(annotation_volume, "coronal", "MIP"),
                "sagittal": project_oriented_volume(annotation_volume, "sagittal", "MIP"),
            }
        return planes

    def _current_projection_mode_for_export(self) -> str:
        mode = self.projection_mode_combo.currentText().strip().upper()
        return "MIP" if mode == "MIP" else "MINIP"

    def _normalize_projection_plane_for_export(self, plane: np.ndarray) -> np.ndarray:
        if self.contrast_state.is_enabled():
            window_min, window_max = self.contrast_state.window()
            return window_slice_to_uint8(plane, window_min, window_max)
        return normalize_slice_to_uint8(plane)

    def source_image_path(self) -> Path | None:
        return self._source_image_path

    def source_patch_bounds(self) -> PatchBounds | None:
        return self._source_patch_bounds

    def update_segmentation_overlay(
        self,
        segmentation_volume: NiftiLoadResult | None,
        opacity: float,
        *,
        active_segmentation_kind: str | None = None,
    ) -> None:
        if active_segmentation_kind not in {None, "file", "annotation"}:
            raise ValueError(
                "Active segmentation kind must be file, annotation, or None."
            )
        if active_segmentation_kind is None and segmentation_volume is not None:
            active_segmentation_kind = "file"
        self._segmentation_opacity = min(max(float(opacity), 0.0), 1.0)
        self._segmentation_patch_volume = segmentation_volume
        self._active_segmentation_kind = active_segmentation_kind
        self.slice_viewer.set_projection_segmentation_source(
            self._active_segmentation_kind
        )
        self.overlay_opacity_control_bar.set_opacity(
            self._active_overlay_opacity()
        )
        self.slice_viewer.set_segmentation_overlay(
            segmentation_volume,
            opacity=self._segmentation_opacity,
        )
        self._refresh_seg_patch_save_enabled()

    def update_projection_mask_layers(
        self,
        layers: Sequence[tuple[str, str, NiftiLoadResult]],
    ) -> None:
        """Refresh file-backed masks while preserving a still-loaded selection."""
        selected_id = self.selected_projection_mask_id()
        self._projection_mask_layers = {
            segmentation_id: volume
            for segmentation_id, _display_name, volume in layers
        }

        was_blocked = self.projection_mask_combo.blockSignals(True)
        self.projection_mask_combo.clear()
        self.projection_mask_combo.addItem("---", None)
        selected_index = 0
        for segmentation_id, display_name, _volume in layers:
            self.projection_mask_combo.addItem(display_name, segmentation_id)
            if segmentation_id == selected_id:
                selected_index = self.projection_mask_combo.count() - 1
        self.projection_mask_combo.setCurrentIndex(selected_index)
        self.projection_mask_combo.blockSignals(was_blocked)
        self._on_projection_mask_changed(selected_index)

    def selected_projection_mask_id(self) -> str | None:
        segmentation_id = self.projection_mask_combo.currentData()
        return segmentation_id if isinstance(segmentation_id, str) else None

    def selected_projection_mask_volume(self) -> NiftiLoadResult | None:
        segmentation_id = self.selected_projection_mask_id()
        if segmentation_id is None:
            return None
        return self._projection_mask_layers.get(segmentation_id)

    def update_segmentation_opacity(self, opacity: float) -> None:
        self._segmentation_opacity = min(max(float(opacity), 0.0), 1.0)
        self.slice_viewer.set_segmentation_overlay_opacity(
            self._segmentation_opacity
        )
        if self._active_segmentation_kind != "annotation":
            self.overlay_opacity_control_bar.set_opacity(
                self._segmentation_opacity
            )

    def update_annotation_overlay(
        self,
        annotation_mask: AnnotationMask | None,
        *,
        opacity: float,
        visible: bool,
        active_label: int,
        editing_enabled: bool = False,
        brush_radius: int | None = None,
        brush_mode: str | None = None,
    ) -> None:
        self._annotation_patch_mask = annotation_mask
        self._annotation_opacity = min(max(float(opacity), 0.0), 1.0)
        self._annotation_visible = bool(visible)
        self._annotation_active_label = max(int(active_label), 0)
        self.slice_viewer.set_annotation_overlay(
            annotation_mask,
            opacity=self._annotation_opacity,
            visible=visible,
            active_label=active_label,
        )
        self.sync_annotation_controls(
            annotation_mask=annotation_mask,
            editing_enabled=editing_enabled,
            opacity=opacity,
            visible=visible,
            active_label=active_label,
            brush_radius=brush_radius,
            brush_mode=brush_mode,
        )
        if self._active_segmentation_kind == "annotation":
            self.overlay_opacity_control_bar.set_opacity(
                self._annotation_opacity
            )
        self._refresh_seg_patch_save_enabled()

    def update_annotation_display_options(
        self,
        *,
        opacity: float,
        visible: bool,
        active_label: int,
        brush_radius: int | None = None,
        brush_mode: str | None = None,
    ) -> None:
        self._annotation_opacity = min(max(float(opacity), 0.0), 1.0)
        self._annotation_visible = bool(visible)
        self._annotation_active_label = max(int(active_label), 0)
        self.slice_viewer.set_annotation_overlay_opacity(self._annotation_opacity)
        self.slice_viewer.set_annotation_overlay_visible(visible)
        self.slice_viewer.set_annotation_active_label(active_label)
        self.annotation_panel.set_visible_checked(visible)
        self.annotation_panel.set_opacity(opacity)
        self.annotation_panel.set_active_label(active_label)
        if self._active_segmentation_kind == "annotation":
            self.overlay_opacity_control_bar.set_opacity(
                self._annotation_opacity
            )
        if brush_radius is not None:
            self.slice_viewer.set_annotation_brush_radius(brush_radius)
            self.annotation_panel.set_brush_radius(brush_radius)
        if brush_mode is not None:
            self.slice_viewer.set_annotation_brush_mode(brush_mode)
            self.annotation_panel.set_brush_mode(brush_mode)

    def sync_annotation_controls(
        self,
        *,
        annotation_mask: AnnotationMask | None,
        editing_enabled: bool,
        opacity: float,
        visible: bool,
        active_label: int,
        brush_radius: int | None,
        brush_mode: str | None,
    ) -> None:
        self.annotation_panel.set_image_loaded(True)
        self.annotation_panel.set_annotation_active(
            annotation_mask is not None,
            editing_enabled=editing_enabled,
            can_undo=self.slice_viewer.annotation_can_undo(),
        )
        self.annotation_panel.set_visible_checked(visible)
        self.annotation_panel.set_opacity(opacity)
        self.annotation_panel.set_active_label(active_label)
        if brush_radius is not None:
            self.slice_viewer.set_annotation_brush_radius(brush_radius)
            self.annotation_panel.set_brush_radius(brush_radius)
        if brush_mode is not None:
            self.slice_viewer.set_annotation_brush_mode(brush_mode)
            self.annotation_panel.set_brush_mode(brush_mode)
        self.slice_viewer.set_annotation_editing_enabled(editing_enabled)

    def annotation_mask(self) -> AnnotationMask | None:
        return self.slice_viewer.annotation_mask()

    def set_segmentation_menu_enabled(
        self,
        *,
        can_unload: bool,
        can_open_configuration: bool,
    ) -> None:
        self.unload_current_segmentation_action.setEnabled(can_unload)
        self.open_segmentation_config_action.setEnabled(can_open_configuration)

    def _refresh_seg_patch_save_enabled(self) -> None:
        if not hasattr(self, "save_seg_patch_button"):
            return
        self.save_seg_patch_button.setEnabled(self._active_overlay_patch_volume() is not None)

    def _active_overlay_patch_volume(self) -> NiftiLoadResult | None:
        if self._segmentation_patch_volume is not None:
            return self._segmentation_patch_volume
        if self._annotation_patch_mask is None:
            return None
        return NiftiLoadResult(
            data=self._annotation_patch_mask.data,
            affine=self._annotation_patch_mask.affine,
            header=self._annotation_patch_mask.header,
            shape=self._annotation_patch_mask.shape,
            dtype=self._annotation_patch_mask.dtype,
        )

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
        parameters: dict[str, int | float | bool | str],
    ) -> np.ndarray:
        utility = patch_utility_from_tool(operation_type)
        return utility.apply(patch_state, parameters)

    def _on_annotation_changed(self, changed_voxels: object) -> None:
        self.annotation_panel.set_undo_available(self.slice_viewer.annotation_can_undo())
        self.annotation_patch_changed.emit(self)

    def _on_annotation_undo_requested(self) -> None:
        changed = self.slice_viewer.undo_annotation()
        self.annotation_panel.set_undo_available(self.slice_viewer.annotation_can_undo())
        if changed <= 0:
            self.statusBar().showMessage("No annotation edit to undo")
            return
        self.statusBar().showMessage(
            f"Undid patch annotation edit: {changed} voxel(s) restored"
        )
        self.annotation_undo_requested_from_patch.emit(self)

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
        self.cursor_panel.set_axis_directions(patch_volume.affine)
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
        if hasattr(self, "screenshot_resolution_spinbox"):
            self._update_screenshot_output_dimensions(
                self.screenshot_resolution_spinbox.value()
            )


def _json_number(value: float) -> int | float:
    rounded = round(float(value))
    if abs(float(value) - rounded) < 1e-9:
        return int(rounded)
    return float(value)
