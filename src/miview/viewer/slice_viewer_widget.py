from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QEvent, QObject, QPointF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPen, QPixmap, QResizeEvent
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from miview.viewer.intensity import normalize_slice_to_uint8
from miview.viewer.slice_geometry import (
    Orientation,
    clamp_cursor_to_volume,
    extract_oriented_slice,
    map_cursor_to_plane_indices,
    map_plane_fraction_to_cursor,
    plane_axes_for_orientation,
)


@dataclass(frozen=True)
class _DisplayedPixmapGeometry:
    width: int
    height: int
    x_offset: float
    y_offset: float


class SliceViewerWidget(QWidget):
    """Single 2D slice view for one anatomical orientation."""

    cursor_position_selected = Signal(int, int, int)

    def __init__(
        self, orientation: Orientation, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.orientation = orientation
        self._volume: np.ndarray | None = None
        self._cursor_position: tuple[int, int, int] | None = None
        self._current_pixmap: QPixmap | None = None
        self._cursor_overlay_visible = True
        self._left_button_drag_active = False

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

    def load_volume(self, volume: np.ndarray) -> None:
        if volume.ndim != 3:
            raise ValueError(f"Slice viewer expects a 3D volume, got {volume.ndim}D.")

        self._volume = np.asarray(volume)
        self._cursor_position = None
        self._current_pixmap = None
        self.image_label.setText("Set cursor to view slices")
        self.image_label.setPixmap(QPixmap())
        self.slice_label.setText("Slice: -")

    def set_cursor_position(self, cursor_position: tuple[int, int, int]) -> None:
        if self._volume is None:
            return

        self._cursor_position = clamp_cursor_to_volume(cursor_position, self._volume.shape)
        self._render_current_slice()

    def set_cursor_overlay_visible(self, visible: bool) -> None:
        self._cursor_overlay_visible = visible
        self._update_scaled_pixmap()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._update_scaled_pixmap()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.image_label and self._volume is not None:
            if event.type() == QEvent.Type.MouseButtonPress:
                mouse_event = event if isinstance(event, QMouseEvent) else None
                if mouse_event is not None and mouse_event.button() == Qt.MouseButton.LeftButton:
                    self._left_button_drag_active = True
                    self._emit_cursor_from_label_position(mouse_event.position())
            elif event.type() == QEvent.Type.MouseMove:
                mouse_event = event if isinstance(event, QMouseEvent) else None
                if (
                    mouse_event is not None
                    and self._left_button_drag_active
                    and mouse_event.buttons() & Qt.MouseButton.LeftButton
                ):
                    self._emit_cursor_from_label_position(mouse_event.position())
            elif event.type() == QEvent.Type.MouseButtonRelease:
                mouse_event = event if isinstance(event, QMouseEvent) else None
                if mouse_event is not None and mouse_event.button() == Qt.MouseButton.LeftButton:
                    self._left_button_drag_active = False
            elif event.type() == QEvent.Type.Leave:
                self._left_button_drag_active = False
        return super().eventFilter(watched, event)

    def _render_current_slice(self) -> None:
        if self._volume is None or self._cursor_position is None:
            return

        slice_2d = extract_oriented_slice(
            self._volume, self.orientation, self._cursor_position
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
        slice_index = self._cursor_position[fixed_axis]
        max_index = self._volume.shape[fixed_axis] - 1
        self.slice_label.setText(f"Slice: {slice_index} / {max_index}")

    def _update_scaled_pixmap(self) -> None:
        if self._current_pixmap is None:
            return

        scaled = self._current_pixmap.scaled(
            self.image_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        if (
            self._cursor_position is None
            or self._volume is None
            or not self._cursor_overlay_visible
        ):
            self.image_label.setPixmap(scaled)
            return

        annotated = scaled.copy()
        painter = QPainter(annotated)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        pen = QPen(QColor("#ffb000"))
        pen.setWidth(1)
        painter.setPen(pen)

        crosshair_x, crosshair_y = self._crosshair_pixel_position(annotated)
        painter.drawLine(crosshair_x, 0, crosshair_x, annotated.height() - 1)
        painter.drawLine(0, crosshair_y, annotated.width() - 1, crosshair_y)
        painter.end()

        self.image_label.setPixmap(annotated)

    def _emit_cursor_from_label_position(self, label_position: QPointF) -> None:
        if self._volume is None or self._cursor_position is None:
            return

        pixmap_geometry = self._displayed_pixmap_geometry()
        if pixmap_geometry is None:
            return

        pixmap_x = label_position.x() - pixmap_geometry.x_offset
        pixmap_y = label_position.y() - pixmap_geometry.y_offset
        if (
            pixmap_x < 0
            or pixmap_y < 0
            or pixmap_x >= pixmap_geometry.width
            or pixmap_y >= pixmap_geometry.height
        ):
            return

        horizontal_fraction = pixmap_x / pixmap_geometry.width
        vertical_fraction = pixmap_y / pixmap_geometry.height
        cursor = map_plane_fraction_to_cursor(
            self.orientation,
            self._volume.shape,
            self._cursor_position,
            horizontal_fraction,
            vertical_fraction,
        )
        self.cursor_position_selected.emit(*cursor)

    def _crosshair_pixel_position(self, pixmap: QPixmap) -> tuple[int, int]:
        assert self._volume is not None
        assert self._cursor_position is not None

        horizontal_index, vertical_index = map_cursor_to_plane_indices(
            self.orientation, self._cursor_position
        )
        horizontal_axis, vertical_axis, _ = plane_axes_for_orientation(self.orientation)
        logical_sizes = (self._volume.shape[1], self._volume.shape[0], self._volume.shape[2])

        crosshair_x = _index_to_pixel(horizontal_index, logical_sizes[horizontal_axis], pixmap.width())
        crosshair_y = _index_to_pixel(vertical_index, logical_sizes[vertical_axis], pixmap.height())
        return crosshair_x, crosshair_y

    def _displayed_pixmap_geometry(self) -> _DisplayedPixmapGeometry | None:
        displayed_pixmap = self.image_label.pixmap()
        if displayed_pixmap is None:
            return None

        pixmap_width = displayed_pixmap.width()
        pixmap_height = displayed_pixmap.height()
        if pixmap_width <= 0 or pixmap_height <= 0:
            return None

        return _DisplayedPixmapGeometry(
            width=pixmap_width,
            height=pixmap_height,
            x_offset=(self.image_label.width() - pixmap_width) / 2.0,
            y_offset=(self.image_label.height() - pixmap_height) / 2.0,
        )


def _index_to_pixel(index: int, axis_size: int, display_size: int) -> int:
    if axis_size <= 1 or display_size <= 1:
        return 0
    centered_fraction = (index + 0.5) / axis_size
    return min(int(centered_fraction * display_size), display_size - 1)
