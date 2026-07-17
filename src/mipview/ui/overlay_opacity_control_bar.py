from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSlider, QWidget


class OverlayOpacityControlBar(QWidget):
    """Compact control for the active segmentation or annotation overlay."""

    opacity_changed = Signal(float)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        opacity: float = 0.5,
    ) -> None:
        super().__init__(parent)
        self.opacity_label = QLabel("Overlay Opacity:", self)
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal, self)
        self.opacity_slider.setRange(0, 100)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 6)
        layout.setSpacing(8)
        layout.addWidget(self.opacity_label)
        layout.addWidget(self.opacity_slider, 1)

        self.opacity_slider.valueChanged.connect(
            lambda value: self.opacity_changed.emit(value / 100.0)
        )
        self.set_opacity(opacity)

    def set_opacity(self, opacity: float) -> None:
        slider_value = int(round(min(max(float(opacity), 0.0), 1.0) * 100.0))
        was_blocked = self.opacity_slider.blockSignals(True)
        self.opacity_slider.setValue(slider_value)
        self.opacity_slider.blockSignals(was_blocked)
