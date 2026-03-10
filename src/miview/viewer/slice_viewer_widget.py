from __future__ import annotations

import numpy as np
from PySide6.QtCore import QEvent, QObject, QPointF, QRect, Qt, Signal
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

from miview.viewer.intensity import normalize_slice_to_uint8
from miview.viewer.oriented_volume import OrientedVolume
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
    zoom_factor_requested = Signal(float)
    viewport_resized = Signal()

    ZOOM_DRAG_SENSITIVITY = 0.01

    def __init__(
        self, orientation: Orientation, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.orientation = orientation
        self._display_volume: OrientedVolume | None = None
        self._source_cursor_position: tuple[int, int, int] | None = None
        self._current_pixmap: QPixmap | None = None
        self._base_scale = 1.0
        self._zoom_factor = 1.0
        self._pan_offset = (0.0, 0.0)
        self._cursor_overlay_visible = True
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
        self.image_label.setText("Set cursor to view slices")
        self.image_label.setPixmap(QPixmap())
        self.slice_label.setText("Slice: -")

    def unload_volume(self) -> None:
        self._display_volume = None
        self._source_cursor_position = None
        self._current_pixmap = None
        self._pan_offset = (0.0, 0.0)
        self._interaction_mode = None
        self._last_drag_position = None
        self.image_label.setText("No volume loaded")
        self.image_label.setPixmap(QPixmap())
        self.slice_label.setText("Slice: -")

    def set_cursor_position(self, cursor_position: tuple[int, int, int]) -> None:
        if self._display_volume is None:
            return

        self._source_cursor_position = cursor_position
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
        return super().eventFilter(watched, event)

    def _render_current_slice(self) -> None:
        if self._display_volume is None or self._source_cursor_position is None:
            return

        display_cursor = self._display_volume.source_to_display(self._source_cursor_position)
        slice_2d = extract_oriented_slice(
            self._display_volume.display_data, self.orientation, display_cursor
        )
        slice_8bit = normalize_slice_to_uint8(slice_2d)
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

        _, _, fixed_axis = plane_axes_for_orientation(self.orientation)
        slice_index = display_cursor[fixed_axis]
        max_index = self._display_volume.display_shape[fixed_axis] - 1
        self.slice_label.setText(f"Slice: {slice_index} / {max_index}")

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
            self._source_cursor_position is None
            or self._display_volume is None
            or not self._cursor_overlay_visible
        ):
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
            self._interaction_mode = "left_cursor"
            self._emit_cursor_from_label_position(mouse_event.position())
        elif mouse_event.button() == Qt.MouseButton.MiddleButton:
            self._interaction_mode = "middle_pan"
        elif mouse_event.button() == Qt.MouseButton.RightButton:
            self._interaction_mode = "right_zoom"

    def _handle_mouse_move(self, mouse_event: QMouseEvent) -> None:
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
        if release_button == Qt.MouseButton.LeftButton and self._interaction_mode == "left_cursor":
            self._interaction_mode = None
        elif release_button == Qt.MouseButton.MiddleButton and self._interaction_mode == "middle_pan":
            self._interaction_mode = None
        elif release_button == Qt.MouseButton.RightButton and self._interaction_mode == "right_zoom":
            self._interaction_mode = None
        self._last_drag_position = None

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
