from __future__ import annotations

import numpy as np
from PySide6.QtCore import QEvent, QObject, QPointF, Qt, Signal
from PySide6.QtGui import QImage, QMouseEvent, QPixmap, QResizeEvent
from PySide6.QtWidgets import QLabel, QSlider, QVBoxLayout, QWidget

from miview.viewer.intensity import normalize_slice_to_uint8


class SliceViewerWidget(QWidget):
    """Minimal single-slice grayscale viewer for 3D volumes."""

    cursor_inspection_changed = Signal(object, object, object, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._volume: np.ndarray | None = None
        self._slice_count: int = 0
        self._current_pixmap: QPixmap | None = None

        self.image_label = QLabel("No volume loaded", self)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(300, 300)
        self.image_label.setStyleSheet("background-color: #1a1a1a; color: #d0d0d0;")
        self.image_label.setMouseTracking(True)
        self.image_label.installEventFilter(self)

        self.slice_label = QLabel("Slice: -", self)
        self.slice_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.slice_slider = QSlider(Qt.Orientation.Horizontal, self)
        self.slice_slider.setEnabled(False)
        self.slice_slider.valueChanged.connect(self._on_slice_changed)

        layout = QVBoxLayout(self)
        layout.addWidget(self.image_label, 1)
        layout.addWidget(self.slice_label)
        layout.addWidget(self.slice_slider)
        layout.setContentsMargins(12, 12, 12, 12)

    def load_volume(self, volume: np.ndarray) -> None:
        if volume.ndim != 3:
            raise ValueError(
                f"Single-slice viewer expects a 3D volume, got {volume.ndim}D."
            )

        self._volume = np.asarray(volume)
        self._slice_count = self._volume.shape[2]
        self.slice_slider.setEnabled(True)
        self.slice_slider.setRange(0, self._slice_count - 1)
        self.slice_slider.setValue(self._slice_count // 2)
        self._render_current_slice()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._update_scaled_pixmap()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.image_label and self._volume is not None:
            if event.type() == QEvent.Type.MouseMove:
                mouse_event = event if isinstance(event, QMouseEvent) else None
                if mouse_event is not None:
                    self._emit_cursor_from_label_position(mouse_event.position())
            elif event.type() == QEvent.Type.MouseButtonPress:
                mouse_event = event if isinstance(event, QMouseEvent) else None
                if mouse_event is not None:
                    self._emit_cursor_from_label_position(mouse_event.position())
            elif event.type() == QEvent.Type.Leave:
                self._emit_fallback_cursor_state()
        return super().eventFilter(watched, event)

    def _on_slice_changed(self, _value: int) -> None:
        self._render_current_slice()

    def _render_current_slice(self) -> None:
        if self._volume is None:
            return

        slice_index = self.slice_slider.value()
        slice_2d = self._volume[:, :, slice_index]
        slice_8bit = normalize_slice_to_uint8(slice_2d)
        contiguous = np.ascontiguousarray(slice_8bit)
        height, width = contiguous.shape
        bytes_per_line = width

        image = QImage(
            contiguous.data, width, height, bytes_per_line, QImage.Format.Format_Grayscale8
        )
        self._current_pixmap = QPixmap.fromImage(image.copy())
        self._update_scaled_pixmap()
        self.slice_label.setText(f"Slice: {slice_index} / {self._slice_count - 1}")
        self._emit_fallback_cursor_state()

    def _update_scaled_pixmap(self) -> None:
        if self._current_pixmap is None:
            return

        scaled = self._current_pixmap.scaled(
            self.image_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.image_label.setPixmap(scaled)

    def _emit_cursor_from_label_position(self, label_position: QPointF) -> None:
        if self._volume is None:
            return

        voxel_coords = self._map_label_position_to_voxel(label_position)
        if voxel_coords is None:
            self._emit_fallback_cursor_state()
            return

        x_index, y_index = voxel_coords
        z_index = self.slice_slider.value()
        intensity = self._volume[y_index, x_index, z_index].item()
        self.cursor_inspection_changed.emit(x_index, y_index, z_index, intensity)

    def _emit_fallback_cursor_state(self) -> None:
        z_index = self.slice_slider.value() if self._volume is not None else None
        self.cursor_inspection_changed.emit(None, None, z_index, None)

    def _map_label_position_to_voxel(self, label_position: QPointF) -> tuple[int, int] | None:
        """
        Map a mouse position on the QLabel to voxel coordinates in the current slice.

        Coordinate mapping is explicit:
        - displayed horizontal pixel (label x) -> volume axis 1 (voxel x)
        - displayed vertical pixel (label y) -> volume axis 0 (voxel y)
        """
        displayed_pixmap = self.image_label.pixmap()
        if displayed_pixmap is None or self._volume is None:
            return None

        pixmap_width = displayed_pixmap.width()
        pixmap_height = displayed_pixmap.height()
        if pixmap_width <= 0 or pixmap_height <= 0:
            return None

        label_width = self.image_label.width()
        label_height = self.image_label.height()
        x_offset = (label_width - pixmap_width) / 2.0
        y_offset = (label_height - pixmap_height) / 2.0

        pixmap_x = label_position.x() - x_offset
        pixmap_y = label_position.y() - y_offset
        if pixmap_x < 0 or pixmap_y < 0 or pixmap_x >= pixmap_width or pixmap_y >= pixmap_height:
            return None

        voxel_width = self._volume.shape[1]
        voxel_height = self._volume.shape[0]
        voxel_x = int((pixmap_x / pixmap_width) * voxel_width)
        voxel_y = int((pixmap_y / pixmap_height) * voxel_height)

        if (
            voxel_x < 0
            or voxel_x >= voxel_width
            or voxel_y < 0
            or voxel_y >= voxel_height
        ):
            return None
        return voxel_x, voxel_y
