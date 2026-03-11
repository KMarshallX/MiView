from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class CursorInspectionPanel(QWidget):
    """Right-side panel for cursor/voxel readouts."""

    patch_opacity_changed = Signal(float)
    patch_size_changed = Signal(int, int, int)
    select_patch_requested = Signal()
    find_patch_box_requested = Signal()

    PANEL_WIDTH = 220

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(self.PANEL_WIDTH)

        group = QGroupBox("Cursor Inspection", self)
        form = QFormLayout(group)

        self.x_value = QLabel("-", group)
        self.y_value = QLabel("-", group)
        self.z_value = QLabel("-", group)
        self.intensity_value = QLabel("-", group)

        form.addRow("X:", self.x_value)
        form.addRow("Y:", self.y_value)
        form.addRow("Z:", self.z_value)
        form.addRow("Intensity:", self.intensity_value)

        self.patch_group = QGroupBox("Patch Selection", self)
        patch_form = QFormLayout(self.patch_group)
        self.patch_opacity_slider = QSlider(Qt.Orientation.Horizontal, self.patch_group)
        self.patch_opacity_slider.setRange(0, 100)
        self.patch_opacity_slider.setValue(50)
        self.patch_opacity_slider.valueChanged.connect(self._on_opacity_slider_changed)

        self.patch_width_spinbox = QSpinBox(self.patch_group)
        self.patch_width_spinbox.setRange(1, 9999)
        self.patch_width_spinbox.setValue(1)
        self.patch_width_spinbox.setSuffix(" vox")
        self.patch_width_spinbox.valueChanged.connect(self._on_patch_size_changed)

        self.patch_height_spinbox = QSpinBox(self.patch_group)
        self.patch_height_spinbox.setRange(1, 9999)
        self.patch_height_spinbox.setValue(1)
        self.patch_height_spinbox.setSuffix(" vox")
        self.patch_height_spinbox.valueChanged.connect(self._on_patch_size_changed)

        self.patch_depth_spinbox = QSpinBox(self.patch_group)
        self.patch_depth_spinbox.setRange(1, 9999)
        self.patch_depth_spinbox.setValue(1)
        self.patch_depth_spinbox.setSuffix(" vox")
        self.patch_depth_spinbox.valueChanged.connect(self._on_patch_size_changed)

        self.select_patch_button = QPushButton("Select Patch", self.patch_group)
        self.select_patch_button.clicked.connect(self.select_patch_requested.emit)
        self.find_patch_box_button = QPushButton("Find Patch Box", self.patch_group)
        self.find_patch_box_button.clicked.connect(self.find_patch_box_requested.emit)
        patch_form.addRow("Opacity:", self.patch_opacity_slider)
        patch_form.addRow("Width (LR / X):", self.patch_width_spinbox)
        patch_form.addRow("Height (AP / Y):", self.patch_height_spinbox)
        patch_form.addRow("Depth (SI / Z):", self.patch_depth_spinbox)
        patch_form.addRow(self.select_patch_button)
        patch_form.addRow(self.find_patch_box_button)

        layout = QVBoxLayout(self)
        layout.addWidget(group)
        layout.addWidget(self.patch_group)
        layout.addStretch(1)
        layout.setContentsMargins(8, 8, 8, 8)

        self.set_patch_controls_visible(False)

    def set_cursor_values(
        self, x: int | None, y: int | None, z: int | None, intensity: float | int | None
    ) -> None:
        self.x_value.setText("-" if x is None else str(x))
        self.y_value.setText("-" if y is None else str(y))
        self.z_value.setText("-" if z is None else str(z))
        self.intensity_value.setText(self._format_intensity(intensity))

    @staticmethod
    def _format_intensity(value: float | int | None) -> str:
        if value is None:
            return "-"
        if isinstance(value, np.floating):
            return f"{float(value):.3g}"
        return str(value)

    def set_patch_controls_visible(self, visible: bool) -> None:
        self.patch_group.setVisible(visible)
        self.patch_opacity_slider.setEnabled(visible)
        self.patch_width_spinbox.setEnabled(visible)
        self.patch_height_spinbox.setEnabled(visible)
        self.patch_depth_spinbox.setEnabled(visible)
        self.select_patch_button.setEnabled(visible)
        self.find_patch_box_button.setEnabled(visible)

    def set_patch_opacity(self, opacity: float) -> None:
        slider_value = int(round(min(max(opacity, 0.0), 1.0) * 100))
        was_blocked = self.patch_opacity_slider.blockSignals(True)
        self.patch_opacity_slider.setValue(slider_value)
        self.patch_opacity_slider.blockSignals(was_blocked)

    def _on_opacity_slider_changed(self, slider_value: int) -> None:
        self.patch_opacity_changed.emit(slider_value / 100.0)

    def set_patch_size_xyz(self, size_xyz: tuple[int, int, int]) -> None:
        x_size, y_size, z_size = size_xyz
        for spinbox, value in (
            (self.patch_width_spinbox, x_size),
            (self.patch_height_spinbox, y_size),
            (self.patch_depth_spinbox, z_size),
        ):
            was_blocked = spinbox.blockSignals(True)
            spinbox.setValue(max(1, int(value)))
            spinbox.blockSignals(was_blocked)

    def _on_patch_size_changed(self, _: int) -> None:
        self.patch_size_changed.emit(
            self.patch_width_spinbox.value(),
            self.patch_height_spinbox.value(),
            self.patch_depth_spinbox.value(),
        )
