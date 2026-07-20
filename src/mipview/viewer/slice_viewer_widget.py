from __future__ import annotations

import numpy as np
from PySide6.QtCore import QEvent, QObject, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QImage,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QPixmap,
    QResizeEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import QApplication, QLabel, QSlider, QVBoxLayout, QWidget

from mipview.annotation.annotation_overlay import build_annotation_overlay_rgba
from mipview.graph.curve import point_to_quadratic_bezier_distance
from mipview.graph.geometry import point_to_segment_distance
from mipview.graph.measurement import AngleMeasurement
from mipview.graph.model import GraphEdge, ProjectionGraphLayer
from mipview.graph.spatial import (
    extension_line_plane_endpoints,
    normal_line_plane_endpoints,
)
from mipview.graph.vector import GraphVector, resolve_graph_vector
from mipview.viewer.intensity import normalize_slice_to_uint8, window_slice_to_uint8
from mipview.segmentation.overlay import build_segmentation_overlay_rgba
from mipview.viewer.oriented_volume import OrientedVolume
from mipview.viewer.ruler import display_voxel_spacing_mm, select_ruler_geometry
from mipview.patch.selector import (
    PatchPlaneBounds,
    axis_for_resize_edge,
    resized_axis_size_from_edge,
)
from mipview.viewer.slice_geometry import (
    DisplayRect,
    Orientation,
    compute_display_rect,
    extract_oriented_slice,
    map_cursor_to_plane_indices,
    map_label_position_to_plane_fraction,
    map_plane_indices_to_label_position,
    map_plane_fraction_to_cursor,
    orientation_indicators_for_orientation,
    plane_axes_for_orientation,
    step_cursor_slice,
)


class SliceViewerWidget(QWidget):
    """Single 2D slice view for one anatomical orientation."""

    cursor_position_selected = Signal(int, int, int)
    patch_center_position_selected = Signal(int, int, int)
    annotation_voxel_selected = Signal(str, int, int, int)
    zoom_factor_requested = Signal(float)
    patch_axis_size_requested = Signal(int, int)
    viewport_resized = Signal()
    graph_context_requested = Signal(str, object, object, object)
    graph_edge_completion_requested = Signal(str, int)
    graph_edge_cancel_requested = Signal()
    graph_vector_completion_requested = Signal(str, object, object)
    graph_orientation_interacted = Signal(str)
    graph_curve_edge_selected = Signal(str, int, int)
    graph_curve_control_changed = Signal(str, int, int, float, float)
    graph_curve_drag_state_changed = Signal(bool)
    graph_curve_exit_requested = Signal()
    graph_angle_vector_selected = Signal(str, int)
    graph_element_selected = Signal(str, object)

    ZOOM_DRAG_SENSITIVITY = 0.01
    PATCH_HANDLE_RADIUS = 3.0
    PATCH_HANDLE_HIT_RADIUS = 9.0
    NEAREST_NEIGHBOR_ZOOM_THRESHOLD = 8.0
    RULER_COLOR = QColor("#39ff14")
    RULER_MARGIN = 8.0
    RULER_TICK_HEIGHT = 6.0

    def __init__(
        self, orientation: Orientation, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.orientation = orientation
        self._display_volume: OrientedVolume | None = None
        self._spatial_unit_to_mm = 1.0
        self._source_cursor_position: tuple[int, int, int] | None = None
        self._contrast_window: tuple[float, float] | None = None
        self._current_pixmap: QPixmap | None = None
        self._base_scale = 1.0
        self._zoom_factor = 1.0
        self._pan_offset = (0.0, 0.0)
        self._cursor_overlay_visible = True
        self._ruler_visible = True
        self._patch_overlay_visible = False
        self._patch_overlay_opacity = 0.5
        self._patch_plane_bounds: PatchPlaneBounds | None = None
        self._patch_size_source = (1, 1, 1)
        self._patch_center_source: tuple[int, int, int] | None = None
        self._segmentation_display_data: np.ndarray | None = None
        self._segmentation_overlay_opacity = 0.5
        self._annotation_display_data: np.ndarray | None = None
        self._annotation_overlay_opacity = 0.5
        self._annotation_overlay_visible = True
        self._annotation_active_label = 1
        self._annotation_editing_enabled = False
        self._annotation_brush_radius = 1
        self._annotation_brush_mode = "paint"
        self._brush_cursor_cache: dict[int, QCursor] = {}
        self._projection_slice_2d: np.ndarray | None = None
        self._projection_segmentation_slice_2d: np.ndarray | None = None
        self._projection_annotation_slice_2d: np.ndarray | None = None
        self._projection_label: str | None = None
        self._graph_layer: ProjectionGraphLayer | None = None
        self._graph_editing_enabled = False
        self._graph_visible = True
        self._graph_opacity = 1.0
        self._graph_node_size = 4
        self._graph_edge_thickness = 2
        self._graph_pending_node_id: int | None = None
        self._graph_preview_label_position: QPointF | None = None
        self._graph_active_tool: str | None = None
        self._graph_selected_node_id: int | None = None
        self._graph_selected_edge: GraphEdge | None = None
        self._graph_curve_handle_visible = False
        self._graph_vectors: tuple[GraphVector, ...] = ()
        self._graph_measurements: tuple[AngleMeasurement, ...] = ()
        self._graph_selected_vector_id: int | None = None
        self._graph_angle_source_vector_id: int | None = None
        self._graph_pending_vector_orientation: Orientation | None = None
        self._graph_pending_vector_source_node_id: int | None = None
        self._graph_normal_line_edge: GraphEdge | None = None
        self._graph_normal_line_thickness = 1
        self._graph_extension_line_edge: GraphEdge | None = None
        self._graph_extension_line_thickness = 1
        self._active_patch_resize_handle: str | None = None
        self._interaction_mode: str | None = None
        self._last_drag_position: QPointF | None = None
        self._right_press_position: QPointF | None = None

        self.title_label = QLabel(self.orientation.title(), self)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setProperty("exclude_responsive_scaling", True)
        self._fixed_title_font = QFont(self.title_label.font())
        self.title_label.setFont(self._fixed_title_font)
        self._fixed_orientation_indicator_font = QFont(self._fixed_title_font)

        self.image_label = QLabel("No volume loaded", self)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(220, 220)
        self.image_label.setStyleSheet("background-color: #1a1a1a; color: #d0d0d0;")
        self.image_label.setMouseTracking(True)
        self.image_label.installEventFilter(self)

        self.slice_label = QLabel("Slice: -", self)
        self.slice_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.slice_slider = QSlider(Qt.Orientation.Horizontal, self)
        self.slice_slider.setEnabled(False)
        self.slice_slider.setRange(0, 0)
        self.slice_slider.setSingleStep(1)
        self.slice_slider.setPageStep(1)
        self.slice_slider.valueChanged.connect(self._on_slice_slider_value_changed)

        layout = QVBoxLayout(self)
        layout.addWidget(self.title_label)
        layout.addWidget(self.image_label, 1)
        layout.addWidget(self.slice_slider)
        layout.addWidget(self.slice_label)
        layout.setContentsMargins(8, 8, 8, 8)

    def load_volume(
        self,
        display_volume: OrientedVolume,
        spatial_unit_to_mm: float = 1.0,
    ) -> None:
        self._display_volume = display_volume
        self._spatial_unit_to_mm = float(spatial_unit_to_mm)
        self._source_cursor_position = None
        self._current_pixmap = None
        self._pan_offset = (0.0, 0.0)
        self._interaction_mode = None
        self._last_drag_position = None
        self._projection_slice_2d = None
        self._projection_segmentation_slice_2d = None
        self._projection_annotation_slice_2d = None
        self._projection_label = None
        self._configure_slice_slider()
        self.image_label.setText("Set cursor to view slices")
        self.image_label.setPixmap(QPixmap())
        self.slice_label.setText("Slice: -")

    def unload_volume(self) -> None:
        self._display_volume = None
        self._source_cursor_position = None
        self._contrast_window = None
        self._current_pixmap = None
        self._segmentation_display_data = None
        self._annotation_display_data = None
        self._annotation_editing_enabled = False
        self._brush_cursor_cache.clear()
        self._pan_offset = (0.0, 0.0)
        self._interaction_mode = None
        self._last_drag_position = None
        self._projection_slice_2d = None
        self._projection_segmentation_slice_2d = None
        self._projection_annotation_slice_2d = None
        self._projection_label = None
        self.slice_slider.setEnabled(False)
        self.slice_slider.setRange(0, 0)
        self.slice_slider.setValue(0)
        self.image_label.setText("No volume loaded")
        self.image_label.setPixmap(QPixmap())
        self.slice_label.setText("Slice: -")

    def set_cursor_position(self, cursor_position: tuple[int, int, int]) -> None:
        if self._display_volume is None:
            return

        self._source_cursor_position = cursor_position
        self._render_current_slice()

    def set_contrast_window(self, window_min: float, window_max: float) -> None:
        self._contrast_window = (window_min, window_max)
        if self._display_volume is not None and self._source_cursor_position is not None:
            self._render_current_slice()

    def set_base_scale(self, base_scale: float) -> None:
        self._base_scale = base_scale
        self._update_scaled_pixmap()

    def set_zoom_factor(self, zoom_factor: float) -> None:
        self._zoom_factor = zoom_factor
        self._update_scaled_pixmap()

    def set_cursor_overlay_visible(self, visible: bool) -> None:
        self._cursor_overlay_visible = visible
        self._update_scaled_pixmap()

    def set_ruler_visible(self, visible: bool) -> None:
        self._ruler_visible = bool(visible)
        self._update_scaled_pixmap()

    def set_graph_overlay(
        self,
        layer: ProjectionGraphLayer | None,
        *,
        editing_enabled: bool,
        visible: bool,
        opacity: float,
        node_size: int,
        edge_thickness: int,
        pending_node_id: int | None,
        active_tool: str | None,
        selected_edge: GraphEdge | None,
        curve_handle_visible: bool,
        vectors: tuple[GraphVector, ...],
        measurements: tuple[AngleMeasurement, ...],
        selected_vector_id: int | None,
        angle_source_vector_id: int | None,
        pending_vector_orientation: Orientation | None,
        pending_vector_source_node_id: int | None,
        selected_node_id: int | None = None,
        normal_line_edge: GraphEdge | None = None,
        normal_line_thickness: int = 1,
        extension_line_edge: GraphEdge | None = None,
        extension_line_thickness: int = 1,
    ) -> None:
        self._graph_layer = layer
        self._graph_editing_enabled = bool(editing_enabled)
        self._graph_visible = bool(visible)
        self._graph_opacity = min(max(float(opacity), 0.0), 1.0)
        self._graph_node_size = min(max(int(node_size), 1), 10)
        self._graph_edge_thickness = min(max(int(edge_thickness), 1), 10)
        self._graph_pending_node_id = (
            None if pending_node_id is None else int(pending_node_id)
        )
        self._graph_active_tool = active_tool
        self._graph_selected_node_id = selected_node_id
        self._graph_selected_edge = selected_edge
        self._graph_curve_handle_visible = bool(curve_handle_visible)
        self._graph_vectors = tuple(vectors)
        self._graph_measurements = tuple(measurements)
        self._graph_selected_vector_id = selected_vector_id
        self._graph_angle_source_vector_id = angle_source_vector_id
        self._graph_pending_vector_orientation = pending_vector_orientation
        self._graph_pending_vector_source_node_id = pending_vector_source_node_id
        self._graph_normal_line_edge = normal_line_edge
        self._graph_normal_line_thickness = max(int(normal_line_thickness), 1)
        self._graph_extension_line_edge = extension_line_edge
        self._graph_extension_line_thickness = max(
            int(extension_line_thickness),
            1,
        )
        if (
            self._graph_pending_node_id is None
            and self._graph_pending_vector_source_node_id is None
        ):
            self._graph_preview_label_position = None
        self._update_scaled_pixmap()

    def set_patch_overlay(
        self,
        visible: bool,
        plane_bounds: PatchPlaneBounds | None,
        opacity: float,
        patch_size_source: tuple[int, int, int],
        patch_center_source: tuple[int, int, int] | None,
    ) -> None:
        self._patch_overlay_visible = visible
        self._patch_plane_bounds = plane_bounds
        self._patch_overlay_opacity = min(max(opacity, 0.0), 1.0)
        self._patch_size_source = patch_size_source
        self._patch_center_source = patch_center_source
        self._update_scaled_pixmap()

    def set_segmentation_overlay(
        self, segmentation_display_data: np.ndarray | None, opacity: float
    ) -> None:
        self._segmentation_display_data = (
            np.asarray(segmentation_display_data)
            if segmentation_display_data is not None
            else None
        )
        self._segmentation_overlay_opacity = min(max(opacity, 0.0), 1.0)
        if self._display_volume is not None and self._source_cursor_position is not None:
            self._render_current_slice()
        else:
            self._update_scaled_pixmap()

    def set_annotation_overlay(
        self,
        annotation_display_data: np.ndarray | None,
        *,
        opacity: float,
        visible: bool,
        active_label: int,
    ) -> None:
        self._annotation_display_data = (
            np.asarray(annotation_display_data)
            if annotation_display_data is not None
            else None
        )
        self._annotation_overlay_opacity = min(max(float(opacity), 0.0), 1.0)
        self._annotation_overlay_visible = bool(visible)
        self._annotation_active_label = max(int(active_label), 0)
        if self._display_volume is not None and self._source_cursor_position is not None:
            self._render_current_slice()
        else:
            self._update_scaled_pixmap()

    def set_annotation_editing_enabled(self, enabled: bool) -> None:
        self._annotation_editing_enabled = bool(enabled)
        self._refresh_hover_cursor_from_global_pos()

    def set_annotation_brush_radius(self, radius: int) -> None:
        self._annotation_brush_radius = max(int(radius), 0)
        self._refresh_hover_cursor_from_global_pos()

    def set_annotation_brush_mode(self, mode: str) -> None:
        if mode not in {"paint", "cursor", "erase"}:
            return
        self._annotation_brush_mode = mode
        self._refresh_hover_cursor_from_global_pos()

    def set_projection_slice(
        self,
        slice_2d: np.ndarray | None,
        label: str | None = None,
        segmentation_slice_2d: np.ndarray | None = None,
        annotation_slice_2d: np.ndarray | None = None,
    ) -> None:
        if slice_2d is None:
            self._projection_slice_2d = None
            self._projection_segmentation_slice_2d = None
            self._projection_annotation_slice_2d = None
            self._projection_label = None
            self._graph_preview_label_position = None
        else:
            projection = np.asarray(slice_2d)
            if projection.ndim != 2:
                raise ValueError("Projection slice must be a 2D array.")
            self._projection_slice_2d = projection
            if segmentation_slice_2d is None:
                self._projection_segmentation_slice_2d = None
            else:
                segmentation_projection = np.asarray(segmentation_slice_2d)
                if segmentation_projection.ndim != 2:
                    raise ValueError("Segmentation projection slice must be a 2D array.")
                if segmentation_projection.shape != projection.shape:
                    raise ValueError(
                        "Segmentation projection slice must match projection slice shape."
                    )
                self._projection_segmentation_slice_2d = segmentation_projection
            if annotation_slice_2d is None:
                self._projection_annotation_slice_2d = None
            else:
                annotation_projection = np.asarray(annotation_slice_2d)
                if annotation_projection.ndim != 2:
                    raise ValueError("Annotation projection slice must be a 2D array.")
                if annotation_projection.shape != projection.shape:
                    raise ValueError(
                        "Annotation projection slice must match projection slice shape."
                    )
                self._projection_annotation_slice_2d = annotation_projection
            self._projection_label = label
        if self._display_volume is not None and self._source_cursor_position is not None:
            self._render_current_slice()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._update_scaled_pixmap()
        self.viewport_resized.emit()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.image_label and self._display_volume is not None:
            if event.type() == QEvent.Type.MouseButtonPress:
                mouse_event = event if isinstance(event, QMouseEvent) else None
                if mouse_event is not None:
                    self._handle_mouse_press(mouse_event)
            elif event.type() == QEvent.Type.MouseMove:
                mouse_event = event if isinstance(event, QMouseEvent) else None
                if mouse_event is not None:
                    self._handle_mouse_move(mouse_event)
            elif event.type() == QEvent.Type.MouseButtonRelease:
                mouse_event = event if isinstance(event, QMouseEvent) else None
                if mouse_event is not None:
                    self._handle_mouse_release(mouse_event)
            elif event.type() == QEvent.Type.Wheel:
                wheel_event = event if isinstance(event, QWheelEvent) else None
                if wheel_event is not None:
                    self._handle_mouse_wheel(wheel_event)
                    return True
            elif event.type() == QEvent.Type.Leave:
                if self._interaction_mode == "left_graph_curve_drag":
                    self.graph_curve_drag_state_changed.emit(False)
                self._interaction_mode = None
                self._last_drag_position = None
                self._right_press_position = None
                self._active_patch_resize_handle = None
                if self._graph_preview_label_position is not None:
                    self._graph_preview_label_position = None
                    self._update_scaled_pixmap()
                self.image_label.setCursor(Qt.CursorShape.ArrowCursor)
        return super().eventFilter(watched, event)

    def _render_current_slice(self) -> None:
        if self._display_volume is None or self._source_cursor_position is None:
            return

        display_cursor = self._display_volume.source_to_display(
            self._source_cursor_position
        )
        slice_8bit = self.current_display_plane_uint8()
        if slice_8bit is None:
            return
        contiguous = np.ascontiguousarray(slice_8bit)
        height, width = contiguous.shape
        image = QImage(
            contiguous.data,
            width,
            height,
            width,
            QImage.Format.Format_Grayscale8,
        )

        self._current_pixmap = QPixmap.fromImage(image.copy())
        self.image_label.setText("")
        self._update_scaled_pixmap()

        if self._projection_slice_2d is not None:
            projection_text = self._projection_label or "Projection"
            self.slice_label.setText(f"Slice: {projection_text}")
        else:
            _, _, fixed_axis = plane_axes_for_orientation(self.orientation)
            slice_index = display_cursor[fixed_axis] + 1
            total_slices = self._display_volume.display_shape[fixed_axis]
            self.slice_label.setText(f"Slice: {slice_index} / {total_slices}")
        self._sync_slice_slider(display_cursor)

    def current_display_plane_uint8(self) -> np.ndarray | None:
        """Return the currently displayed base plane as grayscale uint8.

        This excludes cursor/patch overlays and segmentation overlays.
        """
        if self._display_volume is None or self._source_cursor_position is None:
            return None

        display_cursor = self._display_volume.source_to_display(
            self._source_cursor_position
        )
        if self._projection_slice_2d is not None:
            slice_2d = self._projection_slice_2d
        else:
            slice_2d = extract_oriented_slice(
                self._display_volume.display_data,
                self.orientation,
                display_cursor,
            )
        if self._contrast_window is None:
            return normalize_slice_to_uint8(slice_2d)
        return window_slice_to_uint8(
            slice_2d,
            self._contrast_window[0],
            self._contrast_window[1],
        )

    def _configure_slice_slider(self) -> None:
        if self._display_volume is None:
            self.slice_slider.setEnabled(False)
            self.slice_slider.setRange(0, 0)
            self.slice_slider.setValue(0)
            return

        _, _, fixed_axis = plane_axes_for_orientation(self.orientation)
        total_slices = self._display_volume.display_shape[fixed_axis]
        self.slice_slider.setEnabled(total_slices > 1)
        self.slice_slider.setRange(0, max(total_slices - 1, 0))

    def _sync_slice_slider(self, display_cursor: tuple[int, int, int]) -> None:
        if self._display_volume is None:
            return
        _, _, fixed_axis = plane_axes_for_orientation(self.orientation)
        target_index = int(display_cursor[fixed_axis])
        if self.slice_slider.value() == target_index:
            return
        was_blocked = self.slice_slider.blockSignals(True)
        self.slice_slider.setValue(target_index)
        self.slice_slider.blockSignals(was_blocked)

    def _on_slice_slider_value_changed(self, value: int) -> None:
        if self._display_volume is None or self._source_cursor_position is None:
            return

        display_cursor = self._display_volume.source_to_display(self._source_cursor_position)
        _, _, fixed_axis = plane_axes_for_orientation(self.orientation)
        clamped_value = max(
            0,
            min(value, self._display_volume.display_shape[fixed_axis] - 1),
        )
        if display_cursor[fixed_axis] == clamped_value:
            return

        next_display_cursor = list(display_cursor)
        next_display_cursor[fixed_axis] = clamped_value
        source_cursor = self._display_volume.display_to_source(
            (
                int(next_display_cursor[0]),
                int(next_display_cursor[1]),
                int(next_display_cursor[2]),
            )
        )
        self.cursor_position_selected.emit(*source_cursor)

    def _update_scaled_pixmap(self) -> None:
        if self._current_pixmap is None:
            return

        display_rect = self._display_rect()
        if display_rect is None:
            return

        canvas = QPixmap(self.image_label.size())
        canvas.fill(QColor("#1a1a1a"))
        painter = QPainter(canvas)
        painter.setRenderHint(
            QPainter.RenderHint.SmoothPixmapTransform,
            self._zoom_factor < self.NEAREST_NEIGHBOR_ZOOM_THRESHOLD,
        )
        painter.drawPixmap(
            int(display_rect.left),
            int(display_rect.top),
            int(display_rect.width),
            int(display_rect.height),
            self._current_pixmap,
        )
        self._draw_segmentation_overlay(painter, display_rect)
        self._draw_annotation_overlay(painter, display_rect)
        self._draw_orientation_indicators(painter)

        if (
            self._patch_overlay_visible
            and self._patch_plane_bounds is not None
            and self._display_volume is not None
            and self._source_cursor_position is not None
        ):
            self._draw_patch_overlay(painter, display_rect)

        if (
            self._source_cursor_position is not None
            and self._display_volume is not None
            and self._cursor_overlay_visible
        ):
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            pen = QPen(QColor("#ffb000"))
            pen.setWidth(1)
            painter.setPen(pen)

            crosshair_x, crosshair_y = self._crosshair_pixel_position(display_rect)
            painter.drawLine(crosshair_x, 0, crosshair_x, canvas.height() - 1)
            painter.drawLine(0, crosshair_y, canvas.width() - 1, crosshair_y)

        self._draw_graph_overlay(painter, display_rect)
        self._draw_ruler(painter, display_rect)
        painter.end()

        self.image_label.setPixmap(canvas)

    def _draw_graph_overlay(
        self,
        painter: QPainter,
        display_rect: DisplayRect,
    ) -> None:
        if not self._graph_overlay_available():
            return
        assert self._graph_layer is not None

        node_positions = self._graph_node_screen_positions(display_rect)
        alpha = int(round(self._graph_opacity * 255.0))
        edge_color = QColor(57, 255, 20, alpha)
        node_color = QColor(255, 0, 0, alpha)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._draw_graph_construction_lines(painter, display_rect, alpha)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for edge in self._graph_layer.edges:
            start = node_positions.get(edge.start_node_id)
            end = node_positions.get(edge.end_node_id)
            if start is not None and end is not None:
                edge_pen = QPen(
                    QColor(255, 255, 255, alpha)
                    if edge == self._graph_selected_edge
                    else edge_color,
                    self._graph_edge_thickness,
                )
                edge_pen.setCosmetic(True)
                painter.setPen(edge_pen)
                control = self._graph_layer.curve_control_points.get(edge)
                if control is None:
                    painter.drawLine(start, end)
                else:
                    control_position = self._graph_projection_point_to_screen(
                        control,
                        display_rect,
                    )
                    path = QPainterPath(start)
                    path.quadTo(control_position, end)
                    painter.drawPath(path)

        vector_segments = self._graph_vector_screen_segments(display_rect)
        self._draw_graph_measurements(
            painter,
            display_rect,
            vector_segments,
            alpha,
        )
        self._draw_graph_vectors(painter, vector_segments, alpha)

        painter.setPen(Qt.PenStyle.NoPen)
        radius = float(self._graph_node_size)
        for node_id, position in node_positions.items():
            painter.setBrush(
                QColor(255, 255, 255, alpha)
                if node_id == self._graph_selected_node_id
                else node_color
            )
            painter.drawEllipse(position, radius, radius)

        if (
            self._graph_active_tool == "curve_edge"
            and self._graph_selected_edge is not None
        ):
            control = self._graph_layer.curve_control_points.get(
                self._graph_selected_edge
            )
            if control is not None:
                control_position = self._graph_projection_point_to_screen(
                    control,
                    display_rect,
                )
                handle_pen = QPen(QColor(255, 255, 255, 255), 2)
                handle_pen.setCosmetic(True)
                painter.setPen(handle_pen)
                painter.setBrush(QColor(0, 220, 255, 255))
                painter.drawEllipse(control_position, 6.0, 6.0)

        pending_preview_node_id = self._graph_pending_node_id
        preview_color = QColor(57, 255, 20, 255)
        if (
            self._graph_pending_vector_orientation == self.orientation
            and self._graph_pending_vector_source_node_id is not None
        ):
            pending_preview_node_id = self._graph_pending_vector_source_node_id
            preview_color = QColor(255, 255, 255, 255)
        if (
            pending_preview_node_id is not None
            and self._graph_preview_label_position is not None
        ):
            start = node_positions.get(pending_preview_node_id)
            if start is not None:
                preview_pen = QPen(preview_color, self._graph_edge_thickness)
                preview_pen.setCosmetic(True)
                preview_pen.setStyle(Qt.PenStyle.DashLine)
                painter.setPen(preview_pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawLine(start, self._graph_preview_label_position)
        painter.restore()

    def _draw_graph_construction_lines(
        self,
        painter: QPainter,
        display_rect: DisplayRect,
        alpha: int,
    ) -> None:
        if self._graph_layer is None:
            return
        for edge, endpoint_resolver, color, thickness in (
            (
                self._graph_extension_line_edge,
                extension_line_plane_endpoints,
                QColor(0, 191, 255, alpha),
                self._graph_extension_line_thickness,
            ),
            (
                self._graph_normal_line_edge,
                normal_line_plane_endpoints,
                QColor(255, 255, 0, alpha),
                self._graph_normal_line_thickness,
            ),
        ):
            if edge is None:
                continue
            try:
                first, second = endpoint_resolver(self._graph_layer, edge)
            except ValueError:
                continue
            pen = QPen(color, thickness)
            pen.setCosmetic(True)
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawLine(
                self._graph_projection_point_to_screen(first, display_rect),
                self._graph_projection_point_to_screen(second, display_rect),
            )

    def _graph_vector_screen_segments(
        self,
        display_rect: DisplayRect,
    ) -> dict[int, tuple[QPointF, QPointF]]:
        if self._graph_layer is None:
            return {}
        node_positions = {
            node.id: node.position() for node in self._graph_layer.nodes.values()
        }
        spacing = self._graph_in_plane_spacing()
        segments: dict[int, tuple[QPointF, QPointF]] = {}
        for vector in self._graph_vectors:
            try:
                resolved = resolve_graph_vector(vector, node_positions, spacing)
            except ValueError:
                continue
            start = self._graph_projection_point_to_screen(
                resolved.anchor,
                display_rect,
            )
            if resolved.endpoint is not None:
                end = self._graph_projection_point_to_screen(
                    resolved.endpoint,
                    display_rect,
                )
            else:
                direction_end = self._graph_projection_point_to_screen(
                    (
                        resolved.anchor[0] + resolved.plane_direction[0],
                        resolved.anchor[1] + resolved.plane_direction[1],
                    ),
                    display_rect,
                )
                delta_x = direction_end.x() - start.x()
                delta_y = direction_end.y() - start.y()
                length = float(np.hypot(delta_x, delta_y))
                if length <= 0.0:
                    continue
                end = QPointF(
                    start.x() + ((delta_x / length) * 48.0),
                    start.y() + ((delta_y / length) * 48.0),
                )
            segments[vector.id] = (start, end)
        return segments

    def _draw_graph_vectors(
        self,
        painter: QPainter,
        vector_segments: dict[int, tuple[QPointF, QPointF]],
        alpha: int,
    ) -> None:
        for vector in self._graph_vectors:
            segment = vector_segments.get(vector.id)
            if segment is None:
                continue
            start, end = segment
            delta_x = end.x() - start.x()
            delta_y = end.y() - start.y()
            length = float(np.hypot(delta_x, delta_y))
            if length <= 0.0:
                continue

            selected = vector.id == self._graph_selected_vector_id
            angle_source = vector.id == self._graph_angle_source_vector_id
            if angle_source and not selected:
                selection_pen = QPen(
                    QColor(255, 255, 255, alpha),
                    max(self._graph_edge_thickness, 2) + 5,
                )
                selection_pen.setCosmetic(True)
                painter.setPen(selection_pen)
                painter.drawLine(start, end)
            halo_pen = QPen(
                QColor(10, 10, 10, alpha),
                max(self._graph_edge_thickness, 2) + 3,
            )
            halo_pen.setCosmetic(True)
            painter.setPen(halo_pen)
            painter.drawLine(start, end)

            arrow_color = QColor("#ffffff") if selected else QColor(vector.color)
            arrow_color.setAlpha(alpha)
            arrow_pen = QPen(arrow_color, max(self._graph_edge_thickness, 2))
            arrow_pen.setCosmetic(True)
            painter.setPen(arrow_pen)
            painter.setBrush(arrow_color)
            painter.drawLine(start, end)
            unit_x = delta_x / length
            unit_y = delta_y / length
            head_length = min(10.0, max(length * 0.3, 5.0))
            head_width = head_length * 0.55
            base_x = end.x() - (unit_x * head_length)
            base_y = end.y() - (unit_y * head_length)
            perpendicular_x = -unit_y
            perpendicular_y = unit_x
            painter.drawPolygon(
                QPolygonF(
                    [
                        end,
                        QPointF(
                            base_x + (perpendicular_x * head_width),
                            base_y + (perpendicular_y * head_width),
                        ),
                        QPointF(
                            base_x - (perpendicular_x * head_width),
                            base_y - (perpendicular_y * head_width),
                        ),
                    ]
                )
            )

    def _draw_graph_measurements(
        self,
        painter: QPainter,
        display_rect: DisplayRect,
        vector_segments: dict[int, tuple[QPointF, QPointF]],
        alpha: int,
    ) -> None:
        if not self._graph_measurements:
            return
        vectors_by_id = {vector.id: vector for vector in self._graph_vectors}
        extension_ids = {
            vector_id
            for measurement in self._graph_measurements
            for vector_id in (
                measurement.source_vector_id,
                measurement.target_vector_id,
            )
        }
        painter.save()
        painter.setClipRect(
            QRectF(
                display_rect.left,
                display_rect.top,
                display_rect.width,
                display_rect.height,
            )
        )
        for vector_id in sorted(extension_ids):
            vector = vectors_by_id.get(vector_id)
            segment = vector_segments.get(vector_id)
            if vector is None or segment is None:
                continue
            start, end = segment
            delta_x = end.x() - start.x()
            delta_y = end.y() - start.y()
            length = float(np.hypot(delta_x, delta_y))
            if length <= 0.0:
                continue
            unit_x = delta_x / length
            unit_y = delta_y / length
            color = QColor(vector.color)
            color.setAlpha(max(1, int(alpha * 0.58)))
            pen = QPen(color, 1)
            pen.setCosmetic(True)
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawLine(
                QPointF(start.x() - unit_x * 10000.0, start.y() - unit_y * 10000.0),
                QPointF(start.x() + unit_x * 10000.0, start.y() + unit_y * 10000.0),
            )
        painter.restore()

        for measurement in self._graph_measurements:
            source = vector_segments.get(measurement.source_vector_id)
            target = vector_segments.get(measurement.target_vector_id)
            if source is None or target is None:
                continue
            intersection = _infinite_line_intersection(source, target)
            label_position: QPointF
            if intersection is not None and _point_in_display_rect(
                intersection,
                display_rect,
            ):
                self._draw_angle_arc(painter, intersection, source, target, alpha)
                label_position = QPointF(intersection.x() + 22.0, intersection.y() - 8.0)
            else:
                label_position = QPointF(
                    (source[1].x() + target[1].x()) / 2.0,
                    (source[1].y() + target[1].y()) / 2.0,
                )
            label_position = _clamp_angle_label_position(
                label_position,
                display_rect,
            )
            self._draw_angle_label(
                painter,
                label_position,
                f"A{measurement.id}: {measurement.angle_degrees:.1f}°",
                alpha,
            )

    @staticmethod
    def _draw_angle_arc(
        painter: QPainter,
        center: QPointF,
        source: tuple[QPointF, QPointF],
        target: tuple[QPointF, QPointF],
        alpha: int,
    ) -> None:
        source_angle = float(
            np.degrees(
                np.arctan2(
                    -(source[1].y() - source[0].y()),
                    source[1].x() - source[0].x(),
                )
            )
        )
        target_angle = float(
            np.degrees(
                np.arctan2(
                    -(target[1].y() - target[0].y()),
                    target[1].x() - target[0].x(),
                )
            )
        )
        span = ((target_angle - source_angle + 180.0) % 360.0) - 180.0
        pen = QPen(QColor(255, 255, 255, alpha), 2)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        radius = 18.0
        painter.drawArc(
            QRectF(
                center.x() - radius,
                center.y() - radius,
                radius * 2.0,
                radius * 2.0,
            ),
            int(round(source_angle * 16.0)),
            int(round(span * 16.0)),
        )

    @staticmethod
    def _draw_angle_label(
        painter: QPainter,
        position: QPointF,
        text: str,
        alpha: int,
    ) -> None:
        for offset_x, offset_y in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            painter.setPen(QColor(0, 0, 0, alpha))
            painter.drawText(position + QPointF(offset_x, offset_y), text)
        painter.setPen(QColor(255, 255, 255, alpha))
        painter.drawText(position, text)

    def _graph_in_plane_spacing(self) -> tuple[float, float]:
        if self._display_volume is None:
            return (1.0, 1.0)
        spacings = display_voxel_spacing_mm(
            self._display_volume.affine,
            self._display_volume.display_to_source_affine,
            self._spatial_unit_to_mm,
        )
        horizontal_axis, vertical_axis, _ = plane_axes_for_orientation(self.orientation)
        return (spacings[horizontal_axis], spacings[vertical_axis])

    def _graph_overlay_available(self) -> bool:
        if (
            not self._graph_visible
            or self._graph_opacity <= 0.0
            or self._graph_layer is None
            or self._projection_slice_2d is None
            or self._graph_layer.plane_shape is None
        ):
            return False
        projection_shape = (
            int(self._projection_slice_2d.shape[1]),
            int(self._projection_slice_2d.shape[0]),
        )
        return self._graph_layer.plane_shape == projection_shape

    def _graph_interaction_available(self) -> bool:
        return self._graph_editing_enabled and self._graph_overlay_available()

    def _graph_node_screen_positions(
        self,
        display_rect: DisplayRect,
    ) -> dict[int, QPointF]:
        if self._graph_layer is None or self._graph_layer.plane_shape is None:
            return {}
        return {
            node.id: QPointF(
                *map_plane_indices_to_label_position(
                    node.position(),
                    self._graph_layer.plane_shape,
                    display_rect,
                )
            )
            for node in self._graph_layer.nodes.values()
        }

    def _graph_projection_point_to_screen(
        self,
        point: tuple[float, float],
        display_rect: DisplayRect,
    ) -> QPointF:
        assert self._graph_layer is not None
        assert self._graph_layer.plane_shape is not None
        width, height = self._graph_layer.plane_shape
        return QPointF(
            display_rect.left + (((float(point[0]) + 0.5) / width) * display_rect.width),
            display_rect.top + (((float(point[1]) + 0.5) / height) * display_rect.height),
        )

    def _graph_curve_handle_hit(self, label_position: QPointF) -> bool:
        if (
            self._graph_active_tool != "curve_edge"
            or self._graph_layer is None
            or self._graph_selected_edge is None
        ):
            return False
        control = self._graph_layer.curve_control_points.get(self._graph_selected_edge)
        display_rect = self._display_rect()
        if control is None or display_rect is None:
            return False
        position = self._graph_projection_point_to_screen(control, display_rect)
        return float(
            np.hypot(label_position.x() - position.x(), label_position.y() - position.y())
        ) <= 9.0

    def _clamped_graph_control_from_label_position(
        self,
        label_position: QPointF,
    ) -> tuple[float, float] | None:
        if self._graph_layer is None or self._graph_layer.plane_shape is None:
            return None
        display_rect = self._display_rect()
        if display_rect is None or display_rect.width <= 0.0 or display_rect.height <= 0.0:
            return None
        width, height = self._graph_layer.plane_shape
        horizontal = (
            ((label_position.x() - display_rect.left) / display_rect.width) * width
        ) - 0.5
        vertical = (
            ((label_position.y() - display_rect.top) / display_rect.height) * height
        ) - 0.5
        return (
            min(max(horizontal, 0.0), float(width - 1)),
            min(max(vertical, 0.0), float(height - 1)),
        )

    def _graph_hit_at_label_position(self, label_position: QPointF) -> dict[str, object]:
        if not self._graph_interaction_available() or self._graph_layer is None:
            return {"kind": "empty"}
        display_rect = self._display_rect()
        if display_rect is None:
            return {"kind": "empty"}
        node_positions = self._graph_node_screen_positions(display_rect)
        node_tolerance = max(float(self._graph_node_size + 4), 6.0)
        node_hits = [
            (
                float(np.hypot(label_position.x() - point.x(), label_position.y() - point.y())),
                self._graph_layer.node_hit_priorities.get(node_id, 1),
                node_id,
            )
            for node_id, point in node_positions.items()
        ]
        node_hits = [hit for hit in node_hits if hit[0] <= node_tolerance]
        if node_hits:
            _, _, node_id = min(node_hits)
            return {"kind": "node", "node_id": node_id}

        vector_tolerance = max((self._graph_edge_thickness / 2.0) + 6.0, 8.0)
        vector_hits: list[tuple[float, int]] = []
        for vector_id, (start, end) in self._graph_vector_screen_segments(
            display_rect
        ).items():
            distance = point_to_segment_distance(
                (label_position.x(), label_position.y()),
                (start.x(), start.y()),
                (end.x(), end.y()),
            )
            if distance <= vector_tolerance:
                vector_hits.append((distance, vector_id))

        edge_tolerance = max((self._graph_edge_thickness / 2.0) + 4.0, 6.0)
        edge_hits: list[tuple[float, GraphEdge]] = []
        for edge in self._graph_layer.edges:
            start = node_positions.get(edge.start_node_id)
            end = node_positions.get(edge.end_node_id)
            if start is None or end is None:
                continue
            control = self._graph_layer.curve_control_points.get(edge)
            if control is None:
                distance = point_to_segment_distance(
                    (label_position.x(), label_position.y()),
                    (start.x(), start.y()),
                    (end.x(), end.y()),
                )
            else:
                control_position = self._graph_projection_point_to_screen(
                    control,
                    display_rect,
                )
                distance = point_to_quadratic_bezier_distance(
                    (label_position.x(), label_position.y()),
                    (start.x(), start.y()),
                    (control_position.x(), control_position.y()),
                    (end.x(), end.y()),
                )
            if distance <= edge_tolerance:
                edge_hits.append((distance, edge))
        edge_hit: GraphEdge | None = None
        if edge_hits:
            _, edge_hit = min(
                edge_hits,
                key=lambda hit: (
                    hit[0],
                    hit[1].start_node_id,
                    hit[1].end_node_id,
                ),
            )
        if vector_hits:
            result: dict[str, object] = {
                "kind": "vector",
                "vector_ids": [
                    vector_id for _, vector_id in sorted(vector_hits)
                ],
            }
            if edge_hit is not None:
                result["edge_start_node_id"] = edge_hit.start_node_id
                result["edge_end_node_id"] = edge_hit.end_node_id
            return result
        if edge_hit is not None:
            return {
                "kind": "edge",
                "start_node_id": edge_hit.start_node_id,
                "end_node_id": edge_hit.end_node_id,
            }
        return {"kind": "empty"}

    def _projection_position_from_label_position(
        self,
        label_position: QPointF,
    ) -> tuple[int, int] | None:
        if self._projection_slice_2d is None:
            return None
        display_rect = self._display_rect()
        if display_rect is None:
            return None
        plane_fraction = map_label_position_to_plane_fraction(
            (label_position.x(), label_position.y()),
            display_rect,
        )
        if plane_fraction is None:
            return None
        width = int(self._projection_slice_2d.shape[1])
        height = int(self._projection_slice_2d.shape[0])
        horizontal = min(int(plane_fraction[0] * width), width - 1)
        vertical = min(int(plane_fraction[1] * height), height - 1)
        return (horizontal, vertical)

    def _draw_ruler(self, painter: QPainter, display_rect: DisplayRect) -> None:
        if not self._ruler_visible or self._display_volume is None:
            return

        horizontal_axis, _, _ = plane_axes_for_orientation(self.orientation)
        horizontal_voxels = self._display_volume.display_shape[horizontal_axis]
        if horizontal_voxels <= 0:
            return

        voxel_spacings = display_voxel_spacing_mm(
            self._display_volume.affine,
            self._display_volume.display_to_source_affine,
            self._spatial_unit_to_mm,
        )
        horizontal_spacing_mm = voxel_spacings[horizontal_axis]
        if not np.isfinite(horizontal_spacing_mm) or horizontal_spacing_mm <= 0.0:
            return

        pixels_per_voxel = display_rect.width / float(horizontal_voxels)
        ruler = select_ruler_geometry(
            pixels_per_voxel / horizontal_spacing_mm,
            self.image_label.width(),
        )
        if ruler is None:
            return

        start_x = self.RULER_MARGIN
        end_x = start_x + ruler.pixel_length
        baseline_y = self.image_label.height() - self.RULER_MARGIN
        tick_top = baseline_y - self.RULER_TICK_HEIGHT

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        ruler_pen = QPen(self.RULER_COLOR, 2)
        painter.setPen(ruler_pen)
        painter.drawLine(QPointF(start_x, baseline_y), QPointF(end_x, baseline_y))
        painter.drawLine(QPointF(start_x, tick_top), QPointF(start_x, baseline_y))
        painter.drawLine(QPointF(end_x, tick_top), QPointF(end_x, baseline_y))

        label_font = QFont(self._fixed_orientation_indicator_font)
        label_font.setBold(True)
        painter.setFont(label_font)
        label_height = painter.fontMetrics().height()
        painter.drawText(
            QRectF(
                start_x,
                tick_top - label_height - 2.0,
                max(
                    ruler.pixel_length,
                    float(
                        painter.fontMetrics().horizontalAdvance(ruler.scale.label)
                    ),
                ),
                float(label_height),
            ),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            ruler.scale.label,
        )
        painter.restore()

    def _draw_segmentation_overlay(
        self, painter: QPainter, display_rect: DisplayRect
    ) -> None:
        if (
            self._segmentation_display_data is None
            or self._display_volume is None
            or self._source_cursor_position is None
        ):
            return

        if self._projection_slice_2d is not None:
            if self._projection_segmentation_slice_2d is None:
                return
            segmentation_slice = self._projection_segmentation_slice_2d
        else:
            display_cursor = self._display_volume.source_to_display(self._source_cursor_position)
            segmentation_slice = extract_oriented_slice(
                self._segmentation_display_data,
                self.orientation,
                display_cursor,
            )
        overlay = build_segmentation_overlay_rgba(
            segmentation_slice,
            opacity=self._segmentation_overlay_opacity,
        )
        if not np.any(overlay[..., 3]):
            return

        height, width = overlay.shape[:2]
        overlay_contiguous = np.ascontiguousarray(overlay)
        overlay_image = QImage(
            overlay_contiguous.data,
            width,
            height,
            width * 4,
            QImage.Format.Format_RGBA8888,
        )
        painter.drawImage(
            QRectF(
                display_rect.left,
                display_rect.top,
                display_rect.width,
                display_rect.height,
            ),
            overlay_image.copy(),
        )

    def _draw_annotation_overlay(
        self, painter: QPainter, display_rect: DisplayRect
    ) -> None:
        if (
            not self._annotation_overlay_visible
            or self._annotation_display_data is None
            or self._display_volume is None
            or self._source_cursor_position is None
        ):
            return

        if self._projection_slice_2d is not None:
            if self._projection_annotation_slice_2d is None:
                return
            annotation_slice = self._projection_annotation_slice_2d
        else:
            display_cursor = self._display_volume.source_to_display(
                self._source_cursor_position
            )
            annotation_slice = extract_oriented_slice(
                self._annotation_display_data,
                self.orientation,
                display_cursor,
            )
        overlay = build_annotation_overlay_rgba(
            annotation_slice,
            opacity=self._annotation_overlay_opacity,
            active_label=self._annotation_active_label,
        )
        if not np.any(overlay[..., 3]):
            return

        height, width, _ = overlay.shape
        overlay_contiguous = np.ascontiguousarray(overlay)
        overlay_image = QImage(
            overlay_contiguous.data,
            width,
            height,
            width * 4,
            QImage.Format.Format_RGBA8888,
        )
        painter.drawImage(
            QRectF(
                display_rect.left,
                display_rect.top,
                display_rect.width,
                display_rect.height,
            ),
            overlay_image.copy(),
        )

    def _handle_mouse_press(self, mouse_event: QMouseEvent) -> None:
        self._last_drag_position = mouse_event.position()
        if mouse_event.button() == Qt.MouseButton.LeftButton:
            if (
                self._graph_interaction_available()
                and self._graph_active_tool == "curve_edge"
            ):
                self.graph_orientation_interacted.emit(self.orientation)
                if self._graph_curve_handle_hit(mouse_event.position()):
                    self._interaction_mode = "left_graph_curve_drag"
                    self.graph_curve_drag_state_changed.emit(True)
                    self._emit_graph_curve_control(mouse_event.position())
                    return
                if self._graph_curve_handle_visible:
                    self._interaction_mode = "left_graph_curve_select"
                    self.graph_curve_exit_requested.emit()
                    return
                hit = self._graph_hit_at_label_position(mouse_event.position())
                self._interaction_mode = "left_graph_curve_select"
                if hit.get("kind") == "edge":
                    self.graph_curve_edge_selected.emit(
                        self.orientation,
                        int(hit["start_node_id"]),
                        int(hit["end_node_id"]),
                    )
                return
            if (
                self._graph_interaction_available()
                and self._graph_active_tool == "calculate_angle"
            ):
                self._interaction_mode = "left_graph_angle"
                self.graph_orientation_interacted.emit(self.orientation)
                hit = self._graph_hit_at_label_position(mouse_event.position())
                vector_ids = hit.get("vector_ids")
                if isinstance(vector_ids, list) and vector_ids:
                    self.graph_angle_vector_selected.emit(
                        self.orientation,
                        int(vector_ids[0]),
                    )
                return
            if (
                self._graph_interaction_available()
                and self._graph_pending_vector_source_node_id is not None
            ):
                self._interaction_mode = "left_graph_vector"
                hit = self._graph_hit_at_label_position(mouse_event.position())
                projection_position = self._projection_position_from_label_position(
                    mouse_event.position()
                )
                if projection_position is not None:
                    self.graph_vector_completion_requested.emit(
                        self.orientation,
                        hit.get("node_id") if hit.get("kind") == "node" else None,
                        projection_position,
                    )
                return
            if (
                self._graph_interaction_available()
                and self._graph_pending_node_id is not None
            ):
                self._interaction_mode = "left_graph_edge"
                hit = self._graph_hit_at_label_position(mouse_event.position())
                if hit.get("kind") == "node":
                    self.graph_orientation_interacted.emit(self.orientation)
                    self.graph_edge_completion_requested.emit(
                        self.orientation,
                        int(hit["node_id"]),
                    )
                else:
                    self.graph_edge_cancel_requested.emit()
                return
            if self._graph_interaction_available():
                hit = self._graph_hit_at_label_position(mouse_event.position())
                self.graph_element_selected.emit(self.orientation, hit)
                if hit.get("kind") != "empty":
                    self._interaction_mode = "left_graph_select"
                    return
            if self._start_patch_resize_if_hit(mouse_event.position()):
                self._interaction_mode = "left_patch_resize"
                return
            if self._start_patch_drag_if_hit(mouse_event.position()):
                self._interaction_mode = "left_patch_drag"
                return
            self._interaction_mode = "left_cursor"
            self._emit_cursor_and_annotation_from_label_position(mouse_event.position())
        elif mouse_event.button() == Qt.MouseButton.MiddleButton:
            self._interaction_mode = "middle_pan"
        elif mouse_event.button() == Qt.MouseButton.RightButton:
            if self._graph_interaction_available():
                self._interaction_mode = "right_graph_pending"
                self._right_press_position = mouse_event.position()
            else:
                self._interaction_mode = "right_zoom"

    def _handle_mouse_move(self, mouse_event: QMouseEvent) -> None:
        if (
            self._graph_interaction_available()
            and (
                self._graph_pending_node_id is not None
                or (
                    self._graph_pending_vector_source_node_id is not None
                    and self._graph_pending_vector_orientation == self.orientation
                )
            )
            and not mouse_event.buttons()
        ):
            preview_position = (
                mouse_event.position()
                if self._projection_position_from_label_position(mouse_event.position())
                is not None
                else None
            )
            if preview_position != self._graph_preview_label_position:
                self._graph_preview_label_position = preview_position
                self._update_scaled_pixmap()

        if (
            self._interaction_mode is None
            and not mouse_event.buttons()
            and self._display_volume is not None
        ):
            self._update_hover_cursor(mouse_event.position())

        if self._interaction_mode == "left_patch_resize":
            if mouse_event.buttons() & Qt.MouseButton.LeftButton:
                self._update_patch_resize(mouse_event.position())
            return
        if self._interaction_mode == "left_patch_drag":
            if mouse_event.buttons() & Qt.MouseButton.LeftButton:
                self._emit_patch_center_from_label_position(mouse_event.position())
            return

        if self._interaction_mode in ("left_graph_edge", "left_graph_vector"):
            return

        if self._interaction_mode == "left_graph_curve_drag":
            if mouse_event.buttons() & Qt.MouseButton.LeftButton:
                self._emit_graph_curve_control(mouse_event.position())
            return

        if self._interaction_mode in ("left_graph_curve_select", "left_graph_angle"):
            return

        if self._interaction_mode == "right_graph_pending":
            if (
                mouse_event.buttons() & Qt.MouseButton.RightButton
                and self._right_press_position is not None
            ):
                movement = mouse_event.position() - self._right_press_position
                if float(np.hypot(movement.x(), movement.y())) >= float(
                    QApplication.startDragDistance()
                ):
                    self._interaction_mode = "right_zoom"
                    self._last_drag_position = mouse_event.position()
                    self._right_press_position = None
            return

        if self._interaction_mode == "left_cursor":
            if mouse_event.buttons() & Qt.MouseButton.LeftButton:
                self._emit_cursor_and_annotation_from_label_position(
                    mouse_event.position()
                )
            return

        if self._last_drag_position is None:
            return

        if self._interaction_mode == "middle_pan":
            if mouse_event.buttons() & Qt.MouseButton.MiddleButton:
                self._pan_by(mouse_event.position())
        elif self._interaction_mode == "right_zoom":
            if mouse_event.buttons() & Qt.MouseButton.RightButton:
                self._zoom_by(mouse_event.position())

    def _handle_mouse_release(self, mouse_event: QMouseEvent) -> None:
        release_button = mouse_event.button()
        if release_button == Qt.MouseButton.LeftButton and self._interaction_mode in (
            "left_cursor",
            "left_patch_resize",
            "left_patch_drag",
            "left_graph_edge",
            "left_graph_vector",
            "left_graph_curve_drag",
            "left_graph_curve_select",
            "left_graph_angle",
            "left_graph_select",
        ):
            if self._interaction_mode == "left_graph_curve_drag":
                self.graph_curve_drag_state_changed.emit(False)
            self._interaction_mode = None
        elif release_button == Qt.MouseButton.MiddleButton and self._interaction_mode == "middle_pan":
            self._interaction_mode = None
        elif release_button == Qt.MouseButton.RightButton and self._interaction_mode == "right_zoom":
            self._interaction_mode = None
        elif (
            release_button == Qt.MouseButton.RightButton
            and self._interaction_mode == "right_graph_pending"
        ):
            projection_position = self._projection_position_from_label_position(
                mouse_event.position()
            )
            if projection_position is not None:
                self.graph_orientation_interacted.emit(self.orientation)
                self.graph_context_requested.emit(
                    self.orientation,
                    projection_position,
                    self._graph_hit_at_label_position(mouse_event.position()),
                    self.image_label.mapToGlobal(mouse_event.position().toPoint()),
                )
            self._interaction_mode = None
        self._last_drag_position = None
        self._right_press_position = None
        self._active_patch_resize_handle = None
        self._update_hover_cursor(mouse_event.position())

    def _emit_graph_curve_control(self, label_position: QPointF) -> None:
        if self._graph_selected_edge is None:
            return
        control = self._clamped_graph_control_from_label_position(label_position)
        if control is None:
            return
        self.graph_curve_control_changed.emit(
            self.orientation,
            self._graph_selected_edge.start_node_id,
            self._graph_selected_edge.end_node_id,
            control[0],
            control[1],
        )

    def _handle_mouse_wheel(self, wheel_event: QWheelEvent) -> None:
        if self._display_volume is None or self._source_cursor_position is None:
            return

        delta_y = wheel_event.angleDelta().y()
        if delta_y == 0:
            return

        # Wheel-up browses previous slice; wheel-down browses next slice.
        step = -1 if delta_y > 0 else 1
        display_cursor = self._display_volume.source_to_display(self._source_cursor_position)
        next_display_cursor = step_cursor_slice(
            self.orientation,
            self._display_volume.display_shape,
            display_cursor,
            step,
        )
        source_cursor = self._display_volume.display_to_source(next_display_cursor)
        self.cursor_position_selected.emit(*source_cursor)

    def _pan_by(self, current_position: QPointF) -> None:
        assert self._last_drag_position is not None
        delta = current_position - self._last_drag_position
        pan_x, pan_y = self._pan_offset
        self._pan_offset = (pan_x + delta.x(), pan_y + delta.y())
        self._last_drag_position = current_position
        self._update_scaled_pixmap()

    def _zoom_by(self, current_position: QPointF) -> None:
        assert self._last_drag_position is not None
        delta_x = current_position.x() - self._last_drag_position.x()
        zoom_multiplier = 1.0 + (delta_x * self.ZOOM_DRAG_SENSITIVITY)
        requested_zoom = self._zoom_factor * max(zoom_multiplier, 0.1)
        self._last_drag_position = current_position
        self.zoom_factor_requested.emit(requested_zoom)

    def _emit_cursor_and_annotation_from_label_position(
        self, label_position: QPointF
    ) -> None:
        source_cursor = self._source_cursor_from_label_position(label_position)
        if source_cursor is None:
            return
        self.cursor_position_selected.emit(*source_cursor)
        if (
            self._annotation_editing_enabled
            and self._annotation_brush_mode in {"paint", "erase"}
            and not (
                self._graph_editing_enabled
                and self._projection_slice_2d is not None
            )
        ):
            self.annotation_voxel_selected.emit(self.orientation, *source_cursor)

    def _source_cursor_from_label_position(
        self, label_position: QPointF
    ) -> tuple[int, int, int] | None:
        if self._display_volume is None or self._source_cursor_position is None:
            return None

        display_rect = self._display_rect()
        if display_rect is None:
            return None

        plane_fraction = map_label_position_to_plane_fraction(
            (label_position.x(), label_position.y()),
            display_rect,
        )
        if plane_fraction is None:
            return None

        cursor = map_plane_fraction_to_cursor(
            self.orientation,
            self._display_volume.display_shape,
            self._display_volume.source_to_display(self._source_cursor_position),
            plane_fraction[0],
            plane_fraction[1],
        )
        return self._display_volume.display_to_source(cursor)

    def _crosshair_pixel_position(self, display_rect: DisplayRect) -> tuple[int, int]:
        assert self._display_volume is not None
        assert self._source_cursor_position is not None

        display_cursor = self._display_volume.source_to_display(self._source_cursor_position)
        horizontal_index, vertical_index = map_cursor_to_plane_indices(
            self.orientation, display_cursor, self._display_volume.display_shape
        )
        horizontal_axis, vertical_axis, _ = plane_axes_for_orientation(self.orientation)
        logical_sizes = (
            self._display_volume.display_shape[0],
            self._display_volume.display_shape[1],
            self._display_volume.display_shape[2],
        )
        return map_plane_indices_to_label_position(
            (horizontal_index, vertical_index),
            (logical_sizes[horizontal_axis], logical_sizes[vertical_axis]),
            display_rect,
        )

    def _display_rect(self) -> DisplayRect | None:
        if self._current_pixmap is None:
            return None
        return compute_display_rect(
            (self._current_pixmap.width(), self._current_pixmap.height()),
            (self.image_label.width(), self.image_label.height()),
            self._base_scale,
            self._zoom_factor,
            self._pan_offset,
        )

    def viewport_size(self) -> tuple[int, int]:
        return (self.image_label.width(), self.image_label.height())

    def recenter_on_patch_overlay(self) -> bool:
        """Pan view so the current patch center aligns with viewport center."""
        if self._display_volume is None or self._patch_center_source is None:
            return False

        display_rect = self._display_rect()
        if display_rect is None:
            return False

        display_patch_center = self._display_volume.source_to_display(self._patch_center_source)
        horizontal_index, vertical_index = map_cursor_to_plane_indices(
            self.orientation,
            display_patch_center,
            self._display_volume.display_shape,
        )
        horizontal_axis, vertical_axis, _ = plane_axes_for_orientation(self.orientation)
        patch_center_x, patch_center_y = map_plane_indices_to_label_position(
            (horizontal_index, vertical_index),
            (
                self._display_volume.display_shape[horizontal_axis],
                self._display_volume.display_shape[vertical_axis],
            ),
            display_rect,
        )

        viewport_center = QPointF(
            self.image_label.width() / 2.0,
            self.image_label.height() / 2.0,
        )
        delta_x = viewport_center.x() - float(patch_center_x)
        delta_y = viewport_center.y() - float(patch_center_y)
        pan_x, pan_y = self._pan_offset
        self._pan_offset = (pan_x + delta_x, pan_y + delta_y)
        self._update_scaled_pixmap()
        return True

    def _draw_patch_overlay(self, painter: QPainter, display_rect: DisplayRect) -> None:
        assert self._patch_plane_bounds is not None
        assert self._display_volume is not None

        horizontal_axis, vertical_axis, _ = plane_axes_for_orientation(self.orientation)
        plane_shape = (
            self._display_volume.display_shape[horizontal_axis],
            self._display_volume.display_shape[vertical_axis],
        )

        left = _edge_index_to_display_coordinate(
            self._patch_plane_bounds.horizontal_start,
            plane_shape[0],
            display_rect.left,
            display_rect.width,
        )
        right = _edge_index_to_display_coordinate(
            self._patch_plane_bounds.horizontal_end,
            plane_shape[0],
            display_rect.left,
            display_rect.width,
        )
        top = _edge_index_to_display_coordinate(
            self._patch_plane_bounds.vertical_start,
            plane_shape[1],
            display_rect.top,
            display_rect.height,
        )
        bottom = _edge_index_to_display_coordinate(
            self._patch_plane_bounds.vertical_end,
            plane_shape[1],
            display_rect.top,
            display_rect.height,
        )

        fill_color = QColor(0, 102, 255, int(round(self._patch_overlay_opacity * 255)))
        border_color = QColor(0, 102, 255)
        painter.setPen(QPen(border_color, 2))
        painter.setBrush(fill_color)
        overlay_rect = QRectF(
            left,
            top,
            max(right - left, 1.0),
            max(bottom - top, 1.0),
        )
        painter.drawRect(overlay_rect)

        painter.setPen(QPen(QColor("#ffffff"), 1))
        painter.setBrush(QColor("#ffffff"))
        for handle_center in self._resize_handle_positions(overlay_rect).values():
            painter.drawEllipse(
                handle_center,
                self.PATCH_HANDLE_RADIUS,
                self.PATCH_HANDLE_RADIUS,
            )

    def _draw_orientation_indicators(self, painter: QPainter) -> None:
        indicators = orientation_indicators_for_orientation(self.orientation)
        indicator_font = QFont(self._fixed_orientation_indicator_font)
        indicator_font.setBold(True)
        painter.setFont(indicator_font)
        painter.setPen(QPen(QColor("#ffd400")))

        margin = 8
        rect = QRect(0, 0, self.image_label.width(), self.image_label.height())

        painter.drawText(
            rect.adjusted(margin, 0, 0, 0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            indicators.left,
        )
        painter.drawText(
            rect.adjusted(0, 0, -margin, 0),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            indicators.right,
        )
        painter.drawText(
            rect.adjusted(0, margin, 0, 0),
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter,
            indicators.top,
        )
        painter.drawText(
            rect.adjusted(0, 0, 0, -margin),
            Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
            indicators.bottom,
        )

    def _start_patch_resize_if_hit(self, label_position: QPointF) -> bool:
        if not self._patch_overlay_visible or self._patch_plane_bounds is None:
            return False

        display_rect = self._display_rect()
        if display_rect is None:
            return False

        overlay_rect = self._overlay_display_rect(display_rect)
        if overlay_rect is None:
            return False

        handle_name = self._resize_handle_at_position(label_position, overlay_rect)
        if handle_name is not None:
            self._active_patch_resize_handle = handle_name
            return True
        return False

    def _update_patch_resize(self, label_position: QPointF) -> None:
        if (
            self._display_volume is None
            or self._source_cursor_position is None
            or self._active_patch_resize_handle is None
        ):
            return

        display_rect = self._display_rect()
        if display_rect is None:
            return

        plane_fraction = map_label_position_to_plane_fraction(
            (label_position.x(), label_position.y()),
            display_rect,
        )
        if plane_fraction is None:
            return

        display_cursor = self._display_volume.source_to_display(self._source_cursor_position)
        display_resized_cursor = map_plane_fraction_to_cursor(
            self.orientation,
            self._display_volume.display_shape,
            display_cursor,
            plane_fraction[0],
            plane_fraction[1],
        )
        source_resized_cursor = self._display_volume.display_to_source(display_resized_cursor)

        resize_edges = self._resize_edges_for_handle(self._active_patch_resize_handle)
        patch_center = self._patch_center_source or self._source_cursor_position
        for edge in resize_edges:
            axis = axis_for_resize_edge(self.orientation, edge)
            if axis is None:
                continue

            current_size = self._patch_size_source[axis]
            new_size = resized_axis_size_from_edge(
                patch_center[axis],
                source_resized_cursor[axis],
                edge,
                current_size,
            )
            if new_size != current_size:
                self.patch_axis_size_requested.emit(axis, new_size)

    def _start_patch_drag_if_hit(self, label_position: QPointF) -> bool:
        if not self._patch_overlay_visible:
            return False

        display_rect = self._display_rect()
        if display_rect is None:
            return False

        overlay_rect = self._overlay_display_rect(display_rect)
        if overlay_rect is None:
            return False

        return overlay_rect.contains(label_position)

    def _overlay_display_rect(self, display_rect: DisplayRect) -> QRectF | None:
        if self._patch_plane_bounds is None or self._display_volume is None:
            return None

        horizontal_axis, vertical_axis, _ = plane_axes_for_orientation(self.orientation)
        plane_shape = (
            self._display_volume.display_shape[horizontal_axis],
            self._display_volume.display_shape[vertical_axis],
        )
        left = _edge_index_to_display_coordinate(
            self._patch_plane_bounds.horizontal_start,
            plane_shape[0],
            display_rect.left,
            display_rect.width,
        )
        right = _edge_index_to_display_coordinate(
            self._patch_plane_bounds.horizontal_end,
            plane_shape[0],
            display_rect.left,
            display_rect.width,
        )
        top = _edge_index_to_display_coordinate(
            self._patch_plane_bounds.vertical_start,
            plane_shape[1],
            display_rect.top,
            display_rect.height,
        )
        bottom = _edge_index_to_display_coordinate(
            self._patch_plane_bounds.vertical_end,
            plane_shape[1],
            display_rect.top,
            display_rect.height,
        )
        return QRectF(
            left,
            top,
            max(right - left, 1.0),
            max(bottom - top, 1.0),
        )

    def _emit_patch_center_from_label_position(self, label_position: QPointF) -> None:
        if (
            self._display_volume is None
            or self._patch_center_source is None
        ):
            return

        display_rect = self._display_rect()
        if display_rect is None:
            return

        plane_fraction = map_label_position_to_plane_fraction(
            (label_position.x(), label_position.y()),
            display_rect,
        )
        if plane_fraction is None:
            return

        display_center = self._display_volume.source_to_display(
            self._patch_center_source
        )
        display_center = map_plane_fraction_to_cursor(
            self.orientation,
            self._display_volume.display_shape,
            display_center,
            plane_fraction[0],
            plane_fraction[1],
        )
        source_center = self._display_volume.display_to_source(display_center)
        self.patch_center_position_selected.emit(*source_center)

    def _resize_handle_positions(self, overlay_rect: QRectF) -> dict[str, QPointF]:
        left = overlay_rect.left()
        right = overlay_rect.right()
        top = overlay_rect.top()
        bottom = overlay_rect.bottom()
        mid_x = (left + right) / 2.0
        mid_y = (top + bottom) / 2.0

        return {
            "top_left": QPointF(left, top),
            "top_mid": QPointF(mid_x, top),
            "top_right": QPointF(right, top),
            "right_mid": QPointF(right, mid_y),
            "bottom_right": QPointF(right, bottom),
            "bottom_mid": QPointF(mid_x, bottom),
            "bottom_left": QPointF(left, bottom),
            "left_mid": QPointF(left, mid_y),
        }

    def _resize_handle_at_position(
        self, label_position: QPointF, overlay_rect: QRectF
    ) -> str | None:
        for handle_name, center in self._resize_handle_positions(overlay_rect).items():
            dx = label_position.x() - center.x()
            dy = label_position.y() - center.y()
            if float(np.hypot(dx, dy)) <= self.PATCH_HANDLE_HIT_RADIUS:
                return handle_name
        return None

    def _resize_edges_for_handle(self, handle_name: str) -> tuple[str, ...]:
        if handle_name == "top_left":
            return ("left", "top")
        if handle_name == "top_right":
            return ("right", "top")
        if handle_name == "bottom_left":
            return ("left", "bottom")
        if handle_name == "bottom_right":
            return ("right", "bottom")
        if handle_name == "top_mid":
            return ("top",)
        if handle_name == "bottom_mid":
            return ("bottom",)
        if handle_name == "left_mid":
            return ("left",)
        if handle_name == "right_mid":
            return ("right",)
        return ()

    def _update_hover_cursor(self, label_position: QPointF) -> None:
        display_rect = self._display_rect()
        if display_rect is None:
            self.image_label.setCursor(Qt.CursorShape.ArrowCursor)
            return

        if self._patch_overlay_visible and self._patch_plane_bounds is not None:
            overlay_rect = self._overlay_display_rect(display_rect)
            if overlay_rect is not None:
                handle_name = self._resize_handle_at_position(
                    label_position,
                    overlay_rect,
                )
                if handle_name is not None:
                    if handle_name in ("top_left", "bottom_right"):
                        self.image_label.setCursor(Qt.CursorShape.SizeFDiagCursor)
                    elif handle_name in ("top_right", "bottom_left"):
                        self.image_label.setCursor(Qt.CursorShape.SizeBDiagCursor)
                    elif handle_name in ("left_mid", "right_mid"):
                        self.image_label.setCursor(Qt.CursorShape.SizeHorCursor)
                    else:
                        self.image_label.setCursor(Qt.CursorShape.SizeVerCursor)
                    return

                if overlay_rect.contains(label_position):
                    self.image_label.setCursor(Qt.CursorShape.SizeAllCursor)
                    return

        if self._should_show_brush_cursor(label_position, display_rect):
            self.image_label.setCursor(self._brush_cursor(display_rect))
            return

        self.image_label.setCursor(Qt.CursorShape.ArrowCursor)

    def _refresh_hover_cursor_from_global_pos(self) -> None:
        if self._display_volume is None:
            return
        label_position = self.image_label.mapFromGlobal(QCursor.pos())
        if self.image_label.rect().contains(label_position):
            self._update_hover_cursor(QPointF(label_position))

    def _should_show_brush_cursor(
        self, label_position: QPointF, display_rect: DisplayRect
    ) -> bool:
        if (
            not self._annotation_editing_enabled
            or self._annotation_brush_mode not in {"paint", "erase"}
            or self._display_volume is None
        ):
            return False
        return (
            map_label_position_to_plane_fraction(
                (label_position.x(), label_position.y()),
                display_rect,
            )
            is not None
        )

    def _brush_cursor(self, display_rect: DisplayRect) -> QCursor:
        size = self._brush_cursor_size(display_rect)
        cached = self._brush_cursor_cache.get(size)
        if cached is not None:
            return cached

        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        pen = QPen(QColor("#ffffff"), 2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        inset = 1
        side_length = max(size - 2 * inset - 1, 1)
        painter.drawRect(inset, inset, side_length, side_length)
        painter.end()

        cursor = QCursor(pixmap, size // 2, size // 2)
        self._brush_cursor_cache[size] = cursor
        return cursor

    def _brush_cursor_size(self, display_rect: DisplayRect) -> int:
        if self._display_volume is None:
            return 9
        horizontal_axis, vertical_axis, _ = plane_axes_for_orientation(self.orientation)
        horizontal_voxels = max(self._display_volume.display_shape[horizontal_axis], 1)
        vertical_voxels = max(self._display_volume.display_shape[vertical_axis], 1)
        pixel_per_voxel = max(
            display_rect.width / horizontal_voxels,
            display_rect.height / vertical_voxels,
        )
        footprint_voxels = (self._annotation_brush_radius * 2) + 1
        return min(max(int(round(pixel_per_voxel * footprint_voxels)), 7), 127)


def _edge_index_to_display_coordinate(
    edge_index: int, axis_size: int, rect_origin: float, rect_size: float
) -> float:
    if axis_size <= 0:
        return rect_origin
    clamped = min(max(edge_index, 0), axis_size)
    return rect_origin + (clamped / axis_size) * rect_size


def _infinite_line_intersection(
    first: tuple[QPointF, QPointF],
    second: tuple[QPointF, QPointF],
) -> QPointF | None:
    first_dx = first[1].x() - first[0].x()
    first_dy = first[1].y() - first[0].y()
    second_dx = second[1].x() - second[0].x()
    second_dy = second[1].y() - second[0].y()
    determinant = (first_dx * second_dy) - (first_dy * second_dx)
    if abs(determinant) <= 1e-9:
        return None
    offset_x = second[0].x() - first[0].x()
    offset_y = second[0].y() - first[0].y()
    parameter = ((offset_x * second_dy) - (offset_y * second_dx)) / determinant
    return QPointF(
        first[0].x() + parameter * first_dx,
        first[0].y() + parameter * first_dy,
    )


def _point_in_display_rect(point: QPointF, display_rect: DisplayRect) -> bool:
    return (
        display_rect.left <= point.x() <= display_rect.left + display_rect.width
        and display_rect.top <= point.y() <= display_rect.top + display_rect.height
    )


def _clamp_angle_label_position(
    point: QPointF,
    display_rect: DisplayRect,
) -> QPointF:
    return QPointF(
        min(
            max(point.x(), display_rect.left + 4.0),
            display_rect.left + display_rect.width - 105.0,
        ),
        min(
            max(point.y(), display_rect.top + 14.0),
            display_rect.top + display_rect.height - 4.0,
        ),
    )
