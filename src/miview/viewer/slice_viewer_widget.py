from __future__ import annotations

import numpy as np
from PySide6.QtCore import QEvent, QObject, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QImage,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QResizeEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from miview.viewer.intensity import normalize_slice_to_uint8, window_slice_to_uint8
from miview.viewer.oriented_volume import OrientedVolume
from miview.patch.selector import (
    PatchPlaneBounds,
    axis_for_resize_edge,
    resized_axis_size_from_edge,
)
from miview.viewer.slice_geometry import (
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
    zoom_factor_requested = Signal(float)
    patch_axis_size_requested = Signal(int, int)
    viewport_resized = Signal()

    ZOOM_DRAG_SENSITIVITY = 0.01
    PATCH_HANDLE_RADIUS = 3.0
    PATCH_HANDLE_HIT_RADIUS = 9.0

    def __init__(
        self, orientation: Orientation, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.orientation = orientation
        self._display_volume: OrientedVolume | None = None
        self._source_cursor_position: tuple[int, int, int] | None = None
        self._contrast_window: tuple[float, float] | None = None
        self._current_pixmap: QPixmap | None = None
        self._base_scale = 1.0
        self._zoom_factor = 1.0
        self._pan_offset = (0.0, 0.0)
        self._cursor_overlay_visible = True
        self._patch_overlay_visible = False
        self._patch_overlay_opacity = 0.5
        self._patch_plane_bounds: PatchPlaneBounds | None = None
        self._patch_size_source = (1, 1, 1)
        self._patch_center_source: tuple[int, int, int] | None = None
        self._projection_slice_2d: np.ndarray | None = None
        self._projection_label: str | None = None
        self._active_patch_resize_handle: str | None = None
        self._interaction_mode: str | None = None
        self._last_drag_position: QPointF | None = None

        self.title_label = QLabel(self.orientation.title(), self)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.image_label = QLabel("No volume loaded", self)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(220, 220)
        self.image_label.setStyleSheet("background-color: #1a1a1a; color: #d0d0d0;")
        self.image_label.setMouseTracking(True)
        self.image_label.installEventFilter(self)

        self.slice_label = QLabel("Slice: -", self)
        self.slice_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout = QVBoxLayout(self)
        layout.addWidget(self.title_label)
        layout.addWidget(self.image_label, 1)
        layout.addWidget(self.slice_label)
        layout.setContentsMargins(8, 8, 8, 8)

    def load_volume(self, display_volume: OrientedVolume) -> None:
        self._display_volume = display_volume
        self._source_cursor_position = None
        self._current_pixmap = None
        self._pan_offset = (0.0, 0.0)
        self._interaction_mode = None
        self._last_drag_position = None
        self._projection_slice_2d = None
        self._projection_label = None
        self.image_label.setText("Set cursor to view slices")
        self.image_label.setPixmap(QPixmap())
        self.slice_label.setText("Slice: -")

    def unload_volume(self) -> None:
        self._display_volume = None
        self._source_cursor_position = None
        self._contrast_window = None
        self._current_pixmap = None
        self._pan_offset = (0.0, 0.0)
        self._interaction_mode = None
        self._last_drag_position = None
        self._projection_slice_2d = None
        self._projection_label = None
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

    def set_projection_slice(
        self, slice_2d: np.ndarray | None, label: str | None = None
    ) -> None:
        if slice_2d is None:
            self._projection_slice_2d = None
            self._projection_label = None
        else:
            projection = np.asarray(slice_2d)
            if projection.ndim != 2:
                raise ValueError("Projection slice must be a 2D array.")
            self._projection_slice_2d = projection
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
                self._interaction_mode = None
                self._last_drag_position = None
                self._active_patch_resize_handle = None
                self.image_label.setCursor(Qt.CursorShape.ArrowCursor)
        return super().eventFilter(watched, event)

    def _render_current_slice(self) -> None:
        if self._display_volume is None or self._source_cursor_position is None:
            return

        display_cursor = self._display_volume.source_to_display(self._source_cursor_position)
        if self._projection_slice_2d is not None:
            slice_2d = self._projection_slice_2d
        else:
            slice_2d = extract_oriented_slice(
                self._display_volume.display_data, self.orientation, display_cursor
            )
        if self._contrast_window is None:
            slice_8bit = normalize_slice_to_uint8(slice_2d)
        else:
            slice_8bit = window_slice_to_uint8(
                slice_2d, self._contrast_window[0], self._contrast_window[1]
            )
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

    def _update_scaled_pixmap(self) -> None:
        if self._current_pixmap is None:
            return

        display_rect = self._display_rect()
        if display_rect is None:
            return

        canvas = QPixmap(self.image_label.size())
        canvas.fill(QColor("#1a1a1a"))
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawPixmap(
            int(display_rect.left),
            int(display_rect.top),
            int(display_rect.width),
            int(display_rect.height),
            self._current_pixmap,
        )
        self._draw_orientation_indicators(painter)

        if (
            self._patch_overlay_visible
            and self._patch_plane_bounds is not None
            and self._display_volume is not None
            and self._source_cursor_position is not None
        ):
            self._draw_patch_overlay(painter, display_rect)

        if self._source_cursor_position is None or self._display_volume is None or not self._cursor_overlay_visible:
            painter.end()
            self.image_label.setPixmap(canvas)
            return

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        pen = QPen(QColor("#ffb000"))
        pen.setWidth(1)
        painter.setPen(pen)

        crosshair_x, crosshair_y = self._crosshair_pixel_position(display_rect)
        painter.drawLine(crosshair_x, 0, crosshair_x, canvas.height() - 1)
        painter.drawLine(0, crosshair_y, canvas.width() - 1, crosshair_y)
        painter.end()

        self.image_label.setPixmap(canvas)

    def _handle_mouse_press(self, mouse_event: QMouseEvent) -> None:
        self._last_drag_position = mouse_event.position()
        if mouse_event.button() == Qt.MouseButton.LeftButton:
            if self._start_patch_resize_if_hit(mouse_event.position()):
                self._interaction_mode = "left_patch_resize"
                return
            if self._start_patch_drag_if_hit(mouse_event.position()):
                self._interaction_mode = "left_patch_drag"
                return
            self._interaction_mode = "left_cursor"
            self._emit_cursor_from_label_position(mouse_event.position())
        elif mouse_event.button() == Qt.MouseButton.MiddleButton:
            self._interaction_mode = "middle_pan"
        elif mouse_event.button() == Qt.MouseButton.RightButton:
            self._interaction_mode = "right_zoom"

    def _handle_mouse_move(self, mouse_event: QMouseEvent) -> None:
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

        if self._interaction_mode == "left_cursor":
            if mouse_event.buttons() & Qt.MouseButton.LeftButton:
                self._emit_cursor_from_label_position(mouse_event.position())
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
        ):
            self._interaction_mode = None
        elif release_button == Qt.MouseButton.MiddleButton and self._interaction_mode == "middle_pan":
            self._interaction_mode = None
        elif release_button == Qt.MouseButton.RightButton and self._interaction_mode == "right_zoom":
            self._interaction_mode = None
        self._last_drag_position = None
        self._active_patch_resize_handle = None
        self._update_hover_cursor(mouse_event.position())

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

    def _emit_cursor_from_label_position(self, label_position: QPointF) -> None:
        if self._display_volume is None or self._source_cursor_position is None:
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

        cursor = map_plane_fraction_to_cursor(
            self.orientation,
            self._display_volume.display_shape,
            self._display_volume.source_to_display(self._source_cursor_position),
            plane_fraction[0],
            plane_fraction[1],
        )
        source_cursor = self._display_volume.display_to_source(cursor)
        self.cursor_position_selected.emit(*source_cursor)

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
        indicator_font = QFont(self.slice_label.font())
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

        if self.orientation == "axial":
            return {
                "top_left": QPointF(left, top),
                "top_right": QPointF(right, top),
                "bottom_left": QPointF(left, bottom),
                "bottom_right": QPointF(right, bottom),
            }
        return {
            "top_mid": QPointF(mid_x, top),
            "bottom_mid": QPointF(mid_x, bottom),
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
        return ()

    def _update_hover_cursor(self, label_position: QPointF) -> None:
        display_rect = self._display_rect()
        if (
            not self._patch_overlay_visible
            or display_rect is None
            or self._patch_plane_bounds is None
        ):
            self.image_label.setCursor(Qt.CursorShape.ArrowCursor)
            return

        overlay_rect = self._overlay_display_rect(display_rect)
        if overlay_rect is None:
            self.image_label.setCursor(Qt.CursorShape.ArrowCursor)
            return

        handle_name = self._resize_handle_at_position(label_position, overlay_rect)
        if handle_name is not None:
            if handle_name in ("top_left", "bottom_right"):
                self.image_label.setCursor(Qt.CursorShape.SizeFDiagCursor)
            elif handle_name in ("top_right", "bottom_left"):
                self.image_label.setCursor(Qt.CursorShape.SizeBDiagCursor)
            else:
                self.image_label.setCursor(Qt.CursorShape.SizeVerCursor)
            return

        if overlay_rect.contains(label_position):
            self.image_label.setCursor(Qt.CursorShape.SizeAllCursor)
            return

        self.image_label.setCursor(Qt.CursorShape.ArrowCursor)


def _edge_index_to_display_coordinate(
    edge_index: int, axis_size: int, rect_origin: float, rect_size: float
) -> float:
    if axis_size <= 0:
        return rect_origin
    clamped = min(max(edge_index, 0), axis_size)
    return rect_origin + (clamped / axis_size) * rect_size
