from __future__ import annotations

from dataclasses import replace
import logging
import os
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import QGridLayout, QWidget

from mipview.annotation.annotation_mask import AnnotationMask
from mipview.annotation.brush import erase_disk, paint_disk
from mipview.annotation.undo import AnnotationUndoStack
from mipview.graph.state import ProjectionGraphState
from mipview.graph.model import ProjectionGraphLayer, VoxelPoint
from mipview.graph.spatial import (
    resolve_projection_voxel,
    update_control_point_from_projection,
)
from mipview.ui.drop_loading import first_supported_local_nifti_path
from mipview.state.cursor_state import CursorState
from mipview.state.zoom_state import ZoomState
from mipview.io.nifti_io import NiftiLoadResult
from mipview.patch.selector import (
    DEFAULT_PATCH_SIZE,
    PatchBounds,
    PatchSelector,
    orientation_slice_intersects_bounds,
    project_bounds_to_orientation,
    source_bounds_to_display_bounds,
)
from mipview.viewer.oriented_volume import OrientedVolume, build_oriented_volume
from mipview.viewer.ruler import spatial_unit_to_mm
from mipview.viewer.slice_geometry import (
    Orientation,
    center_cursor_for_volume,
    compute_shared_base_scale,
    plane_axes_for_orientation,
    plane_shape_for_orientation,
    project_oriented_volume,
)
from mipview.viewer.slice_viewer_widget import SliceViewerWidget

LOGGER = logging.getLogger(__name__)


class TriPlanarViewerWidget(QWidget):
    """Minimal tri-planar viewer with a shared logical cursor."""

    cursor_inspection_changed = Signal(object, object, object, object)
    patch_selection_changed = Signal(object)
    annotation_changed = Signal(object)
    annotation_undo_availability_changed = Signal(bool)
    nifti_file_dropped = Signal(object)
    projection_state_changed = Signal(str, object)
    graph_context_requested = Signal(str, object, object, object)
    graph_edge_completion_requested = Signal(str, int)
    graph_edge_cancel_requested = Signal()
    graph_vector_completion_requested = Signal(str, object, object)
    graph_orientation_interacted = Signal(str)
    graph_layers_cleared = Signal(object)
    graph_curve_edge_selected = Signal(str, int, int)
    graph_curve_control_changed = Signal(str, int, int, float, float)
    graph_curve_drag_state_changed = Signal(bool)
    graph_curve_exit_requested = Signal()
    graph_angle_vector_selected = Signal(str, int)
    graph_element_selected = Signal(str, object)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        maximum_zoom: float = ZoomState.MAX_ZOOM,
    ) -> None:
        super().__init__(parent)
        self._display_volume: OrientedVolume | None = None
        self._segmentation_display_volume: OrientedVolume | None = None
        self._projection_mask_display_volume: OrientedVolume | None = None
        self._segmentation_opacity: float = 0.5
        self._annotation_mask: AnnotationMask | None = None
        self._annotation_display_volume: OrientedVolume | None = None
        self._annotation_opacity: float = 0.5
        self._annotation_visible: bool = True
        self._annotation_active_label: int = 1
        self._annotation_editing_enabled: bool = False
        self._annotation_brush_radius: int = 1
        self._annotation_brush_mode: str = "paint"
        self._annotation_undo_stack = AnnotationUndoStack()
        self._projection_graph_state: ProjectionGraphState | None = None
        self._contrast_window: tuple[float, float] | None = None
        patch_debug_value = os.getenv("MIPVIEW_PATCH_DEBUG")
        if patch_debug_value is None:
            patch_debug_value = os.getenv("MIVIEW_PATCH_DEBUG", "")
        self._patch_debug_enabled = patch_debug_value.lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        self.cursor_state = CursorState(self)
        self.zoom_state = ZoomState(self, maximum_zoom=maximum_zoom)
        self.patch_selector = PatchSelector(DEFAULT_PATCH_SIZE)
        self._projection_mode = "MIP"
        self._projection_segmentation_enabled = True
        self._projection_segmentation_source: str | None = "all"
        self._active_view: Orientation | None = None
        self._drop_loading_enabled = False
        self._projection_enabled: dict[str, bool] = {
            "axial": False,
            "sagittal": False,
            "coronal": False,
        }
        self.setAcceptDrops(False)

        self.axial_view = SliceViewerWidget("axial", self)
        self.coronal_view = SliceViewerWidget("coronal", self)
        self.sagittal_view = SliceViewerWidget("sagittal", self)
        self._views = (
            self.axial_view,
            self.coronal_view,
            self.sagittal_view,
        )
        self._drop_event_sources = (
            self,
            self.axial_view,
            self.axial_view.image_label,
            self.coronal_view,
            self.coronal_view.image_label,
            self.sagittal_view,
            self.sagittal_view.image_label,
        )

        for view in self._views:
            view.cursor_position_selected.connect(self._on_cursor_selected)
            view.patch_center_position_selected.connect(self._on_patch_center_selected)
            view.annotation_voxel_selected.connect(self._on_annotation_voxel_selected)
            view.zoom_factor_requested.connect(self.zoom_state.set_zoom_factor)
            view.patch_axis_size_requested.connect(self._on_patch_axis_size_requested)
            view.viewport_resized.connect(self._update_shared_base_scale)
            view.graph_context_requested.connect(self.graph_context_requested.emit)
            view.graph_edge_completion_requested.connect(
                self.graph_edge_completion_requested.emit
            )
            view.graph_edge_cancel_requested.connect(
                self.graph_edge_cancel_requested.emit
            )
            view.graph_vector_completion_requested.connect(
                self.graph_vector_completion_requested.emit
            )
            view.graph_orientation_interacted.connect(
                self._on_graph_orientation_interacted
            )
            view.graph_curve_edge_selected.connect(
                self.graph_curve_edge_selected.emit
            )
            view.graph_curve_control_changed.connect(
                self.graph_curve_control_changed.emit
            )
            view.graph_curve_drag_state_changed.connect(
                self.graph_curve_drag_state_changed.emit
            )
            view.graph_curve_exit_requested.connect(
                self.graph_curve_exit_requested.emit
            )
            view.graph_angle_vector_selected.connect(
                self.graph_angle_vector_selected.emit
            )
            view.graph_element_selected.connect(self.graph_element_selected.emit)
        for widget in self._drop_event_sources:
            widget.installEventFilter(self)
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
        unit_scale_to_mm = spatial_unit_to_mm(volume.header.get_xyzt_units()[0])
        # Reset cursor state before reloading the views so the initial cursor
        # is always re-emitted into the freshly cleared slice widgets.
        self.cursor_state.clear()
        self.cursor_state.set_volume_shape(self._display_volume.source_shape)
        self.patch_selector.set_volume_shape(self._display_volume.source_shape)
        self._sync_graph_plane_shapes()
        for view in self._views:
            view.load_volume(self._display_volume, unit_scale_to_mm)
            if self._contrast_window is not None:
                view.set_contrast_window(
                    self._contrast_window[0], self._contrast_window[1]
                )
        self._apply_segmentation_overlay_to_views()
        self._sync_annotation_overlay_for_loaded_volume()

        self._update_shared_base_scale()
        self.zoom_state.set_zoom_factor(1.0)
        initial_center = center_cursor_for_volume(self._display_volume.source_shape)
        self.patch_selector.set_center(initial_center)
        self.cursor_state.set_cursor_position(initial_center)
        self._update_projection_overrides()

    def replace_volume(
        self,
        volume: NiftiLoadResult,
        *,
        cursor_position: tuple[int, int, int] | None = None,
        patch_center: tuple[int, int, int] | None = None,
        patch_size_xyz: tuple[int, int, int] | None = None,
        patch_selection_enabled: bool | None = None,
    ) -> None:
        """Replace source volume while restoring viewer interaction state."""
        self.load_volume(volume)

        if patch_selection_enabled is not None:
            self.set_patch_selection_enabled(patch_selection_enabled)

        if cursor_position is not None and self._display_volume is not None:
            self.cursor_state.set_cursor_position(
                _clamp_voxel(cursor_position, self._display_volume.source_shape)
            )

        if patch_size_xyz is not None:
            self.set_patch_size_xyz(patch_size_xyz)

        if patch_center is not None and self._display_volume is not None:
            self.patch_selector.set_center(
                _clamp_voxel(patch_center, self._display_volume.source_shape)
            )
            self._update_patch_overlays()

    def unload_volume(self) -> None:
        self._display_volume = None
        self._segmentation_display_volume = None
        self._projection_mask_display_volume = None
        self._annotation_mask = None
        self._annotation_display_volume = None
        self._annotation_editing_enabled = False
        self._active_view = None
        self.cursor_state.clear()
        self.zoom_state.set_zoom_factor(1.0)
        self.patch_selector.clear()
        for view in self._views:
            view.unload_volume()
            view.set_segmentation_overlay(None, self._segmentation_opacity)
            view.set_annotation_overlay(
                None,
                opacity=self._annotation_opacity,
                visible=self._annotation_visible,
                active_label=self._annotation_active_label,
            )
            view.set_annotation_editing_enabled(False)
            view.set_patch_overlay(
                False,
                None,
                self.patch_selector.opacity(),
                self.patch_selector.size_xyz(),
                None,
            )
            view.set_projection_slice(None)
        self.patch_selection_changed.emit(None)

    def current_cursor_position(self) -> tuple[int, int, int] | None:
        return self.cursor_state.cursor_position()

    def active_view(self) -> Orientation | None:
        return self._active_view

    def current_slice_indices(self) -> dict[str, int] | None:
        cursor = self.cursor_state.cursor_position()
        if cursor is None:
            return None
        x, y, z = cursor
        return {
            "axial": int(z),
            "coronal": int(y),
            "sagittal": int(x),
        }

    def set_cursor_overlay_visible(self, visible: bool) -> None:
        for view in self._views:
            view.set_cursor_overlay_visible(visible)

    def set_ruler_visible(self, visible: bool) -> None:
        for view in self._views:
            view.set_ruler_visible(visible)

    def set_patch_selection_enabled(self, enabled: bool) -> None:
        if enabled and self.cursor_state.cursor_position() is not None:
            for axis, default_size in enumerate(DEFAULT_PATCH_SIZE):
                self.patch_selector.set_size_axis(axis, default_size)
            self.patch_selector.set_center(self.cursor_state.cursor_position())
        self.patch_selector.set_enabled(enabled)
        self._update_patch_overlays()

    def patch_selection_enabled(self) -> bool:
        return self.patch_selector.enabled()

    def set_patch_overlay_opacity(self, opacity: float) -> None:
        self.patch_selector.set_opacity(opacity)
        self._update_patch_overlays()

    def patch_overlay_opacity(self) -> float:
        return self.patch_selector.opacity()

    def patch_size_xyz(self) -> tuple[int, int, int]:
        return self.patch_selector.size_xyz()

    def set_patch_size_xyz(self, size_xyz: tuple[int, int, int]) -> None:
        changed = False
        for axis, axis_size in enumerate(size_xyz):
            if self.patch_selector.set_size_axis(axis, axis_size):
                changed = True
        if changed:
            self._update_patch_overlays()

    def current_patch_bounds(self) -> PatchBounds | None:
        return self.patch_selector.current_bounds()

    def current_patch_center(self) -> tuple[int, int, int] | None:
        return self.patch_selector.center()

    def recenter_views_on_patch_box(self) -> None:
        target_cursor = self.patch_selector.center()
        if target_cursor is None:
            bounds = self.patch_selector.current_bounds()
            if bounds is not None:
                target_cursor = (
                    (bounds.x_start + bounds.x_end - 1) // 2,
                    (bounds.y_start + bounds.y_end - 1) // 2,
                    (bounds.z_start + bounds.z_end - 1) // 2,
                )
        if target_cursor is not None:
            self.cursor_state.set_cursor_position(target_cursor)

        for view in self._views:
            view.recenter_on_patch_overlay()

    def set_contrast_window(self, window_min: float, window_max: float) -> None:
        if window_max < window_min:
            window_min, window_max = window_max, window_min
        self._contrast_window = (window_min, window_max)
        for view in self._views:
            view.set_contrast_window(window_min, window_max)

    def set_projection_mode(self, mode: str) -> None:
        normalized_mode = mode.strip().upper()
        if normalized_mode not in {"MIP", "MINIP"}:
            return
        if self._projection_mode == normalized_mode:
            return
        self._projection_mode = normalized_mode
        self._update_projection_overrides()
        self.projection_state_changed.emit(
            self._projection_mode,
            self.enabled_projection_orientations(),
        )

    def set_projection_enabled(self, orientation: Orientation, enabled: bool) -> None:
        if orientation not in self._projection_enabled:
            return
        if self._projection_enabled[orientation] == enabled:
            return
        self._projection_enabled[orientation] = enabled
        self._update_projection_overrides()
        self.projection_state_changed.emit(
            self._projection_mode,
            self.enabled_projection_orientations(),
        )

    def projection_mode(self) -> str:
        return self._projection_mode

    def set_projection_segmentation_enabled(self, enabled: bool) -> None:
        normalized = bool(enabled)
        if self._projection_segmentation_enabled == normalized:
            return
        self._projection_segmentation_enabled = normalized
        self._update_projection_overrides()

    def set_projection_segmentation_source(self, source: str | None) -> None:
        if source not in {None, "file", "annotation", "all"}:
            raise ValueError(
                "Projection segmentation source must be file, annotation, all, or None."
            )
        if self._projection_segmentation_source == source:
            return
        self._projection_segmentation_source = source
        self._update_projection_overrides()

    def projection_enabled(self, orientation: Orientation) -> bool:
        return bool(self._projection_enabled.get(orientation, False))

    def enabled_projection_orientations(self) -> tuple[Orientation, ...]:
        return tuple(
            view.orientation
            for view in self._views
            if self._projection_enabled.get(view.orientation, False)
        )

    def active_view(self) -> Orientation | None:
        return self._active_view

    def set_projection_graph_state(
        self,
        graph_state: ProjectionGraphState | None,
    ) -> None:
        self._projection_graph_state = graph_state
        self._sync_graph_plane_shapes()
        self.refresh_graph_overlay()

    def refresh_graph_overlay(self) -> None:
        graph_state = self._projection_graph_state
        for view in self._views:
            if graph_state is None or self._display_volume is None:
                view.set_graph_overlay(
                    None,
                    editing_enabled=False,
                    visible=False,
                    opacity=0.0,
                    node_size=1,
                    edge_thickness=1,
                    pending_node_id=None,
                    active_tool=None,
                    selected_node_id=None,
                    selected_edge=None,
                    curve_handle_visible=False,
                    vectors=(),
                    measurements=(),
                    selected_vector_id=None,
                    angle_source_vector_id=None,
                    pending_vector_orientation=None,
                    pending_vector_source_node_id=None,
                    normal_line_edge=None,
                    extension_line_edge=None,
                )
                continue
            layer = graph_state.projected_layer(
                view.orientation,
                self._display_volume,
            )
            layer = replace(
                layer,
                node_hit_priorities=self._graph_node_hit_priorities(layer),
            )
            view.set_graph_overlay(
                layer,
                editing_enabled=(
                    graph_state.editing_enabled
                    and self.projection_enabled(view.orientation)
                ),
                visible=graph_state.visible,
                opacity=graph_state.opacity,
                node_size=graph_state.node_size,
                edge_thickness=graph_state.edge_thickness,
                pending_node_id=graph_state.pending_edge_node_id,
                active_tool=graph_state.active_tool,
                selected_node_id=graph_state.selected_node_id,
                selected_edge=graph_state.selected_edge,
                curve_handle_visible=(
                    graph_state.active_tool == "curve_edge"
                    and graph_state.selected_edge is not None
                ),
                vectors=tuple(
                    vector
                    for vector in graph_state.vectors.values()
                    if vector.orientation == view.orientation
                ),
                measurements=tuple(
                    measurement
                    for measurement in graph_state.angle_measurements.values()
                    if graph_state.vectors[measurement.source_vector_id].orientation
                    == view.orientation
                ),
                selected_vector_id=graph_state.selected_vector_id,
                angle_source_vector_id=graph_state.angle_source_vector_id,
                pending_vector_orientation=graph_state.pending_vector_orientation,
                pending_vector_source_node_id=(
                    graph_state.pending_vector_source_node_id
                ),
                normal_line_edge=(
                    graph_state.normal_line_edge
                    if graph_state.normal_line_orientation == view.orientation
                    else None
                ),
                normal_line_thickness=graph_state.normal_line_thickness,
                extension_line_edge=(
                    graph_state.extension_line_edge
                    if graph_state.extension_line_orientation == view.orientation
                    else None
                ),
                extension_line_thickness=graph_state.extension_line_thickness,
            )

    def graph_projected_layer(
        self,
        orientation: Orientation,
    ) -> ProjectionGraphLayer:
        if self._projection_graph_state is None or self._display_volume is None:
            raise ValueError("Graph projection geometry is not available.")
        return self._projection_graph_state.projected_layer(
            orientation,
            self._display_volume,
        )

    def resolve_graph_projection_voxel(
        self,
        orientation: Orientation,
        horizontal_index: int,
        vertical_index: int,
    ) -> tuple[int, int, int]:
        if self._display_volume is None:
            raise ValueError("Graph projection geometry is not available.")
        source_cursor = self.cursor_state.cursor_position()
        preferred_display = (
            None
            if source_cursor is None
            else self._display_volume.source_to_display(source_cursor)
        )
        return resolve_projection_voxel(
            self._display_volume,
            orientation,
            self._projection_mode,
            horizontal_index,
            vertical_index,
            mask_display_data=(
                None
                if self._projection_mask_display_volume is None
                else self._projection_mask_display_volume.display_data
            ),
            preferred_display_voxel=preferred_display,
        )

    def graph_control_point_from_projection(
        self,
        source_control_point: VoxelPoint,
        orientation: Orientation,
        horizontal: float,
        vertical: float,
    ) -> VoxelPoint:
        if self._display_volume is None:
            raise ValueError("Graph projection geometry is not available.")
        return update_control_point_from_projection(
            source_control_point,
            self._display_volume,
            orientation,
            horizontal,
            vertical,
        )

    def set_drop_loading_enabled(self, enabled: bool) -> None:
        self._drop_loading_enabled = enabled
        for widget in self._drop_event_sources:
            widget.setAcceptDrops(enabled)

    def set_segmentation_overlay(
        self, segmentation_volume: NiftiLoadResult | None, opacity: float | None = None
    ) -> None:
        if opacity is not None:
            self._segmentation_opacity = min(max(opacity, 0.0), 1.0)
        if segmentation_volume is None:
            self._segmentation_display_volume = None
            self._apply_segmentation_overlay_to_views()
            return

        if segmentation_volume.data.ndim != 3:
            raise ValueError(
                f"Segmentation overlay expects a 3D volume, got {segmentation_volume.data.ndim}D."
            )
        if self._display_volume is not None and segmentation_volume.shape != self._display_volume.source_shape:
            raise ValueError(
                "Segmentation shape does not match the loaded image shape."
            )

        self._segmentation_display_volume = build_oriented_volume(
            segmentation_volume.data,
            segmentation_volume.affine,
        )
        self._apply_segmentation_overlay_to_views()

    def set_segmentation_overlay_opacity(self, opacity: float) -> None:
        self._segmentation_opacity = min(max(opacity, 0.0), 1.0)
        self._apply_segmentation_overlay_to_views()

    def segmentation_overlay_opacity(self) -> float:
        return self._segmentation_opacity

    def set_projection_mask(self, mask_volume: NiftiLoadResult | None) -> None:
        """Restrict MIP/MinIP calculations to non-zero voxels in ``mask_volume``."""
        if mask_volume is None:
            self._projection_mask_display_volume = None
            self._update_projection_overrides()
            return

        if mask_volume.data.ndim != 3:
            raise ValueError(
                f"Projection mask expects a 3D volume, got {mask_volume.data.ndim}D."
            )
        if (
            self._display_volume is not None
            and mask_volume.shape != self._display_volume.source_shape
        ):
            raise ValueError("Projection mask shape does not match the loaded image shape.")

        self._projection_mask_display_volume = build_oriented_volume(
            mask_volume.data,
            mask_volume.affine,
        )
        self._update_projection_overrides()

    def set_annotation_overlay(
        self,
        annotation_mask: AnnotationMask | None,
        *,
        opacity: float | None = None,
        visible: bool | None = None,
        active_label: int | None = None,
        undo_stack: AnnotationUndoStack | None = None,
    ) -> None:
        if opacity is not None:
            self._annotation_opacity = min(max(float(opacity), 0.0), 1.0)
        if visible is not None:
            self._annotation_visible = bool(visible)
        if active_label is not None:
            self._annotation_active_label = max(int(active_label), 0)
        if undo_stack is not None:
            self._annotation_undo_stack = undo_stack

        self._annotation_mask = annotation_mask
        if annotation_mask is None:
            self._annotation_display_volume = None
            self._annotation_editing_enabled = False
            self._annotation_undo_stack.clear()
            self._apply_annotation_overlay_to_views()
            self.annotation_undo_availability_changed.emit(False)
            return

        if annotation_mask.data.ndim != 3:
            raise ValueError(
                f"Annotation overlay expects a 3D mask, got {annotation_mask.data.ndim}D."
            )
        if (
            self._display_volume is not None
            and annotation_mask.shape != self._display_volume.source_shape
        ):
            raise ValueError("Annotation mask shape does not match the loaded image shape.")

        self._annotation_display_volume = build_oriented_volume(
            annotation_mask.data,
            annotation_mask.affine,
        )
        self._annotation_undo_stack.clear()
        self._apply_annotation_overlay_to_views()
        self.annotation_undo_availability_changed.emit(False)

    def annotation_mask(self) -> AnnotationMask | None:
        return self._annotation_mask

    def refresh_annotation_overlay(self) -> None:
        if self._annotation_mask is not None:
            self._annotation_display_volume = build_oriented_volume(
                self._annotation_mask.data,
                self._annotation_mask.affine,
            )
        self._apply_annotation_overlay_to_views()

    def set_annotation_overlay_opacity(self, opacity: float) -> None:
        self._annotation_opacity = min(max(float(opacity), 0.0), 1.0)
        self._apply_annotation_overlay_to_views()

    def set_annotation_overlay_visible(self, visible: bool) -> None:
        self._annotation_visible = bool(visible)
        self._apply_annotation_overlay_to_views()

    def set_annotation_active_label(self, label: int) -> None:
        self._annotation_active_label = max(int(label), 0)
        self._apply_annotation_overlay_to_views()

    def set_annotation_editing_enabled(self, enabled: bool) -> None:
        self._annotation_editing_enabled = (
            bool(enabled) and self._annotation_mask is not None
        )
        for view in self._views:
            view.set_annotation_editing_enabled(self._annotation_editing_enabled)

    def set_annotation_brush_radius(self, radius: int) -> None:
        self._annotation_brush_radius = max(int(radius), 0)
        for view in self._views:
            view.set_annotation_brush_radius(self._annotation_brush_radius)

    def set_annotation_brush_mode(self, mode: str) -> None:
        if mode not in {"paint", "cursor", "erase"}:
            return
        self._annotation_brush_mode = mode
        for view in self._views:
            view.set_annotation_brush_mode(mode)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._accept_drop_event(event):
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if self._accept_drop_event(event):
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        dropped_path = self._dropped_nifti_path(event)
        if dropped_path is None:
            event.ignore()
            return
        event.acceptProposedAction()
        self.nifti_file_dropped.emit(dropped_path)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched in self._drop_event_sources and self._handle_drop_event(event):
            return True
        return super().eventFilter(watched, event)

    def _on_cursor_selected(self, x: int, y: int, z: int) -> None:
        self._set_active_view_from_sender()
        self.cursor_state.set_cursor_position((x, y, z))

    def _on_cursor_changed(self, x: int, y: int, z: int) -> None:
        if self._display_volume is None:
            return

        cursor_position = (x, y, z)
        for view in self._views:
            view.set_cursor_position(cursor_position)

        intensity = self._display_volume.source_data[x, y, z].item()
        self.cursor_inspection_changed.emit(x, y, z, intensity)
        self._update_patch_overlays()

    def _on_patch_center_selected(self, x: int, y: int, z: int) -> None:
        self._set_active_view_from_sender()
        self.patch_selector.set_center((x, y, z))
        self._update_patch_overlays()

    def _on_annotation_voxel_selected(
        self, orientation: str, x: int, y: int, z: int
    ) -> None:
        if orientation in ("axial", "coronal", "sagittal"):
            self._active_view = orientation  # type: ignore[assignment]
        if (
            self._annotation_mask is None
            or not self._annotation_editing_enabled
            or self._annotation_brush_mode == "cursor"
        ):
            return

        undo_snapshot = self._annotation_undo_stack.snapshot_disk(
            self._annotation_mask,
            orientation,  # type: ignore[arg-type]
            (x, y, z),
            self._annotation_brush_radius,
        )
        if self._annotation_brush_mode == "erase":
            changed = erase_disk(
                self._annotation_mask,
                orientation,  # type: ignore[arg-type]
                (x, y, z),
                self._annotation_brush_radius,
            )
        else:
            changed = paint_disk(
                self._annotation_mask,
                orientation,  # type: ignore[arg-type]
                (x, y, z),
                self._annotation_brush_radius,
                self._annotation_active_label,
            )
        if changed <= 0:
            return
        self._annotation_undo_stack.commit_snapshot(
            undo_snapshot,
            self._annotation_mask,
        )
        self.refresh_annotation_overlay()
        self.annotation_undo_availability_changed.emit(
            self._annotation_undo_stack.can_undo()
        )
        self.annotation_changed.emit(changed)

    def _set_active_view_from_sender(self) -> None:
        sender = self.sender()
        orientation = getattr(sender, "orientation", None)
        if orientation in ("axial", "coronal", "sagittal"):
            self._active_view = orientation

    def undo_annotation(self) -> int:
        if self._annotation_mask is None:
            return 0
        changed = self._annotation_undo_stack.undo(self._annotation_mask)
        if changed <= 0:
            self.annotation_undo_availability_changed.emit(False)
            return 0
        self.refresh_annotation_overlay()
        self.annotation_undo_availability_changed.emit(
            self._annotation_undo_stack.can_undo()
        )
        return changed

    def annotation_can_undo(self) -> bool:
        if self._annotation_mask is None:
            return False
        return self._annotation_undo_stack.can_undo()

    def _on_zoom_changed(self, zoom_factor: float) -> None:
        for view in self._views:
            view.set_zoom_factor(zoom_factor)

    def _on_graph_orientation_interacted(self, orientation: str) -> None:
        if orientation in ("axial", "coronal", "sagittal"):
            self._active_view = orientation  # type: ignore[assignment]
            self.graph_orientation_interacted.emit(orientation)

    def _sync_graph_plane_shapes(self) -> None:
        if self._display_volume is None or self._projection_graph_state is None:
            return
        if self._projection_graph_state.set_volume_geometry(
            self._display_volume.source_shape,
            self._display_volume.source_to_display_affine,
        ):
            self.graph_layers_cleared.emit(("axial", "coronal", "sagittal"))

    def _graph_node_hit_priorities(
        self,
        layer: ProjectionGraphLayer,
    ) -> dict[int, int]:
        if self._projection_graph_state is None:
            return {}
        priorities: dict[int, int] = {}
        for node_id, projected_node in layer.nodes.items():
            try:
                extremum_voxel = self.resolve_graph_projection_voxel(
                    layer.orientation,
                    int(round(projected_node.horizontal_index)),
                    int(round(projected_node.vertical_index)),
                )
            except ValueError:
                priorities[node_id] = 1
                continue
            priorities[node_id] = int(
                self._projection_graph_state.graph.nodes[node_id].position()
                != extremum_voxel
            )
        return priorities

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

    def _on_patch_axis_size_requested(self, axis: int, new_size: int) -> None:
        if not self.patch_selector.enabled():
            return
        if self.patch_selector.set_size_axis(axis, new_size):
            self._update_patch_overlays()

    def _update_patch_overlays(self) -> None:
        bounds = self.patch_selector.current_bounds()
        enabled = self.patch_selector.enabled()
        opacity = self.patch_selector.opacity()
        size_xyz = self.patch_selector.size_xyz()

        if self._display_volume is None or bounds is None:
            for view in self._views:
                view.set_patch_overlay(False, None, opacity, size_xyz, None)
            self.patch_selection_changed.emit(None)
            return

        display_bounds = source_bounds_to_display_bounds(bounds, self._display_volume)
        source_cursor = self.cursor_state.cursor_position()
        source_patch_center = self.patch_selector.center()
        if source_cursor is None or source_patch_center is None:
            for view in self._views:
                view.set_patch_overlay(False, None, opacity, size_xyz, None)
            self.patch_selection_changed.emit(None)
            return
        display_cursor = self._display_volume.source_to_display(source_cursor)
        for view in self._views:
            visible_in_view = (
                enabled
                and orientation_slice_intersects_bounds(
                    display_bounds, view.orientation, display_cursor
                )
            )
            plane_bounds = (
                project_bounds_to_orientation(
                    display_bounds,
                    view.orientation,
                    self._display_volume.display_shape,
                )
                if visible_in_view
                else None
            )
            view.set_patch_overlay(
                visible_in_view,
                plane_bounds,
                opacity,
                size_xyz,
                source_patch_center,
            )

        if self._patch_debug_enabled and enabled:
            LOGGER.warning(
                "Patch debug: center=(%d, %d, %d) bounds=(%d:%d, %d:%d, %d:%d)",
                source_patch_center[0],
                source_patch_center[1],
                source_patch_center[2],
                bounds.x_start,
                bounds.x_end,
                bounds.y_start,
                bounds.y_end,
                bounds.z_start,
                bounds.z_end,
            )
            for view in self._views:
                visible_in_view = orientation_slice_intersects_bounds(
                    display_bounds, view.orientation, display_cursor
                )
                if not visible_in_view:
                    _, _, fixed_axis = plane_axes_for_orientation(view.orientation)
                    LOGGER.warning(
                        "Patch debug [%s]: hidden at slice index=%d",
                        view.orientation,
                        display_cursor[fixed_axis],
                    )
                    continue
                plane_bounds = project_bounds_to_orientation(
                    display_bounds,
                    view.orientation,
                    self._display_volume.display_shape,
                )
                LOGGER.warning(
                    "Patch debug [%s]: rect h=(%d:%d) v=(%d:%d)",
                    view.orientation,
                    plane_bounds.horizontal_start,
                    plane_bounds.horizontal_end,
                    plane_bounds.vertical_start,
                    plane_bounds.vertical_end,
                )

        self.patch_selection_changed.emit(bounds if enabled else None)

    def _update_projection_overrides(self) -> None:
        if self._display_volume is None:
            for view in self._views:
                view.set_projection_slice(
                    None,
                    segmentation_slice_2d=None,
                    annotation_slice_2d=None,
                )
            return

        volume = self._display_volume.display_data
        for view in self._views:
            if not self._projection_enabled.get(view.orientation, False):
                view.set_projection_slice(
                    None,
                    segmentation_slice_2d=None,
                    annotation_slice_2d=None,
                )
                continue
            projection_slice = project_oriented_volume(
                volume,
                view.orientation,
                self._projection_mode,
                mask=(
                    None
                    if self._projection_mask_display_volume is None
                    else self._projection_mask_display_volume.display_data
                ),
            )
            segmentation_projection_slice = None
            if (
                self._projection_segmentation_enabled
                and self._projection_segmentation_source in {"file", "all"}
                and self._segmentation_display_volume is not None
            ):
                segmentation_projection_slice = project_oriented_volume(
                    self._segmentation_display_volume.display_data,
                    view.orientation,
                    (
                        self._projection_mode
                        if self._projection_segmentation_source == "all"
                        else "MIP"
                    ),
                )
            annotation_projection_slice = None
            if (
                self._projection_segmentation_enabled
                and self._projection_segmentation_source in {"annotation", "all"}
                and self._annotation_display_volume is not None
            ):
                annotation_projection_slice = project_oriented_volume(
                    self._annotation_display_volume.display_data,
                    view.orientation,
                    "MIP",
                )
            view.set_projection_slice(
                projection_slice,
                f"{self._projection_mode} ({view.orientation.title()})",
                segmentation_slice_2d=segmentation_projection_slice,
                annotation_slice_2d=annotation_projection_slice,
            )
        self.refresh_graph_overlay()

    def _apply_segmentation_overlay_to_views(self) -> None:
        if self._segmentation_display_volume is None:
            for view in self._views:
                view.set_segmentation_overlay(None, self._segmentation_opacity)
            self._update_projection_overrides()
            return

        for view in self._views:
            view.set_segmentation_overlay(
                self._segmentation_display_volume.display_data,
                self._segmentation_opacity,
            )
        self._update_projection_overrides()

    def _apply_annotation_overlay_to_views(self) -> None:
        annotation_data = (
            None
            if self._annotation_display_volume is None
            else self._annotation_display_volume.display_data
        )
        for view in self._views:
            view.set_annotation_overlay(
                annotation_data,
                opacity=self._annotation_opacity,
                visible=self._annotation_visible,
                active_label=self._annotation_active_label,
            )
            view.set_annotation_editing_enabled(self._annotation_editing_enabled)
            view.set_annotation_brush_radius(self._annotation_brush_radius)
            view.set_annotation_brush_mode(self._annotation_brush_mode)
        self._update_projection_overrides()

    def _sync_annotation_overlay_for_loaded_volume(self) -> None:
        if self._display_volume is None or self._annotation_mask is None:
            self._apply_annotation_overlay_to_views()
            return

        if self._annotation_mask.shape != self._display_volume.source_shape:
            self._annotation_mask = None
            self._annotation_display_volume = None
        else:
            self._annotation_display_volume = build_oriented_volume(
                self._annotation_mask.data,
                self._annotation_mask.affine,
            )
        self._apply_annotation_overlay_to_views()

    def _accept_drop_event(self, event: QDragEnterEvent | QDragMoveEvent) -> bool:
        if self._dropped_nifti_path(event) is None:
            event.ignore()
            return False
        event.acceptProposedAction()
        return True

    def _handle_drop_event(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.DragEnter:
            drag_enter_event = event if isinstance(event, QDragEnterEvent) else None
            return (
                drag_enter_event is not None
                and self._accept_drop_event(drag_enter_event)
            )
        if event.type() == QEvent.Type.DragMove:
            drag_move_event = event if isinstance(event, QDragMoveEvent) else None
            return (
                drag_move_event is not None
                and self._accept_drop_event(drag_move_event)
            )
        if event.type() != QEvent.Type.Drop:
            return False
        drop_event = event if isinstance(event, QDropEvent) else None
        if drop_event is None:
            return False
        dropped_path = self._dropped_nifti_path(drop_event)
        if dropped_path is None:
            return False
        drop_event.acceptProposedAction()
        self.nifti_file_dropped.emit(dropped_path)
        return True

    def _dropped_nifti_path(
        self, event: QDragEnterEvent | QDragMoveEvent | QDropEvent
    ) -> Path | None:
        if not self._drop_loading_enabled:
            return None
        mime_data = event.mimeData()
        if mime_data is None or not mime_data.hasUrls():
            return None
        return first_supported_local_nifti_path(mime_data.urls())


def _clamp_voxel(
    voxel: tuple[int, int, int],
    shape: tuple[int, int, int],
) -> tuple[int, int, int]:
    return tuple(
        int(min(max(voxel[axis], 0), shape[axis] - 1)) for axis in range(3)
    )
