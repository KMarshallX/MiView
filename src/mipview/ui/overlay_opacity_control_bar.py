from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QSlider, QWidget


class OverlayOpacityControlBar(QWidget):
    """Compact control for the active segmentation or annotation overlay."""

    opacity_changed = Signal(float)
    segmentation_changed = Signal(object)

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
        self.segmentation_combo = QComboBox(self)
        self.segmentation_combo.setMinimumContentsLength(8)
        self.segmentation_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 6)
        layout.setSpacing(8)
        layout.addWidget(self.opacity_label)
        layout.addWidget(self.opacity_slider, 1)
        layout.addWidget(self.segmentation_combo)

        self.opacity_slider.valueChanged.connect(
            lambda value: self.opacity_changed.emit(value / 100.0)
        )
        self.segmentation_combo.currentIndexChanged.connect(
            lambda _index: self.segmentation_changed.emit(
                self.segmentation_combo.currentData()
            )
        )
        self.set_opacity(opacity)
        self.set_segmentations((), None)

    def set_opacity(self, opacity: float) -> None:
        slider_value = int(round(min(max(float(opacity), 0.0), 1.0) * 100.0))
        was_blocked = self.opacity_slider.blockSignals(True)
        self.opacity_slider.setValue(slider_value)
        self.opacity_slider.blockSignals(was_blocked)

    def set_segmentations(
        self,
        segmentations: Sequence[tuple[str, str]],
        active_segmentation_id: str | None,
    ) -> None:
        """Replace selectable overlays while preserving a synchronized selection."""
        was_blocked = self.segmentation_combo.blockSignals(True)
        self.segmentation_combo.clear()
        self.segmentation_combo.addItem("---", None)
        selected_index = 0
        for segmentation_id, display_name in segmentations:
            self.segmentation_combo.addItem(display_name, segmentation_id)
            if segmentation_id == active_segmentation_id:
                selected_index = self.segmentation_combo.count() - 1
        self.segmentation_combo.setCurrentIndex(selected_index)
        self.segmentation_combo.setEnabled(bool(segmentations))
        self.segmentation_combo.blockSignals(was_blocked)
