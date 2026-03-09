from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap, QResizeEvent
from PySide6.QtWidgets import QLabel, QSlider, QVBoxLayout, QWidget

from miview.viewer.intensity import normalize_slice_to_uint8


class SliceViewerWidget(QWidget):
    """Minimal single-slice grayscale viewer for 3D volumes."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._volume: np.ndarray | None = None
        self._slice_count: int = 0
        self._current_pixmap: QPixmap | None = None

        self.image_label = QLabel("No volume loaded", self)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(300, 300)
        self.image_label.setStyleSheet("background-color: #1a1a1a; color: #d0d0d0;")

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

    def _update_scaled_pixmap(self) -> None:
        if self._current_pixmap is None:
            return

        scaled = self._current_pixmap.scaled(
            self.image_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.image_label.setPixmap(scaled)
