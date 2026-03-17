from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QSlider,
    QVBoxLayout,
    QWidget,
)


class SegmentationConfigWindow(QMainWindow):
    active_segmentation_changed = Signal(str)
    opacity_changed = Signal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Segmentation Configuration")
        self.resize(420, 360)

        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.image_label = QLabel("Image: none", container)
        self.segmentations_label = QLabel("Loaded Segmentations", container)
        self.segmentation_list = QListWidget(container)
        self.segmentation_list.currentItemChanged.connect(
            self._on_current_segmentation_changed
        )

        self.opacity_label = QLabel("Overlay Opacity", container)
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal, container)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setValue(50)
        self.opacity_slider.valueChanged.connect(self._on_opacity_slider_changed)

        layout.addWidget(self.image_label)
        layout.addWidget(self.segmentations_label)
        layout.addWidget(self.segmentation_list, 1)
        layout.addWidget(self.opacity_label)
        layout.addWidget(self.opacity_slider)

        self.setCentralWidget(container)

    def set_current_image_name(self, image_name: str | None) -> None:
        if image_name is None:
            self.image_label.setText("Image: none")
            return
        self.image_label.setText(f"Image: {image_name}")

    def set_segmentations(
        self, segmentations: Sequence[tuple[str, str, str]], active_segmentation_id: str | None
    ) -> None:
        was_blocked = self.segmentation_list.blockSignals(True)
        self.segmentation_list.clear()
        selected_row = -1
        for row, (segmentation_id, display_name, full_path) in enumerate(segmentations):
            item = QListWidgetItem(display_name)
            item.setData(Qt.ItemDataRole.UserRole, segmentation_id)
            item.setToolTip(full_path)
            self.segmentation_list.addItem(item)
            if segmentation_id == active_segmentation_id:
                selected_row = row
        if selected_row >= 0:
            self.segmentation_list.setCurrentRow(selected_row)
        self.segmentation_list.blockSignals(was_blocked)

    def set_opacity(self, opacity: float) -> None:
        slider_value = int(round(min(max(opacity, 0.0), 1.0) * 100.0))
        was_blocked = self.opacity_slider.blockSignals(True)
        self.opacity_slider.setValue(slider_value)
        self.opacity_slider.blockSignals(was_blocked)

    def _on_current_segmentation_changed(
        self,
        current: QListWidgetItem | None,
        _previous: QListWidgetItem | None,
    ) -> None:
        if current is None:
            return
        segmentation_id = current.data(Qt.ItemDataRole.UserRole)
        if isinstance(segmentation_id, str):
            self.active_segmentation_changed.emit(segmentation_id)

    def _on_opacity_slider_changed(self, value: int) -> None:
        self.opacity_changed.emit(value / 100.0)