from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from mipview.viewer.physical_axes import physical_axis_direction_labels


class CursorInspectionPanel(QWidget):
    """Right-side panel for cursor/voxel readouts."""

    patch_activation_toggled = Signal(bool)
    patch_opacity_changed = Signal(float)
    patch_size_changed = Signal(int, int, int)
    select_patch_requested = Signal()
    find_patch_box_requested = Signal()

    PANEL_WIDTH = 220

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        adaptable_width: bool = False,
    ) -> None:
        super().__init__(parent)
        if adaptable_width:
            self.setMinimumWidth(self.PANEL_WIDTH)
            self.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Preferred,
            )
        else:
            self.setFixedWidth(self.PANEL_WIDTH)

        group = QGroupBox("Cursor Inspection", self)
        form = QFormLayout(group)

        self.x_value = QLabel("-", group)
        self.y_value = QLabel("-", group)
        self.z_value = QLabel("-", group)
        self.intensity_value = QLabel("-", group)

        self.x_axis_label = QLabel("X:", group)
        self.y_axis_label = QLabel("Y:", group)
        self.z_axis_label = QLabel("Z:", group)

        form.addRow(self.x_axis_label, self.x_value)
        form.addRow(self.y_axis_label, self.y_value)
        form.addRow(self.z_axis_label, self.z_value)
        form.addRow("Intensity:", self.intensity_value)

        self.patch_group = QGroupBox("Patch Selection", self)
        patch_form = QFormLayout(self.patch_group)
        self.patch_activation_button = QPushButton("Enable", self.patch_group)
        self.patch_activation_button.setCheckable(True)
        self.patch_activation_button.toggled.connect(self._on_patch_activation_toggled)
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
        patch_form.addRow(self.patch_activation_button)
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

        self.set_patch_controls_enabled(False)
        self.set_patch_selection_active(False)
        self.set_patch_activation_available(False)

    def set_cursor_values(
        self, x: int | None, y: int | None, z: int | None, intensity: float | int | None
    ) -> None:
        for label, value in (
            (self.x_value, x),
            (self.y_value, y),
            (self.z_value, z),
        ):
            label.setText("-" if value is None else str(value))
        self.intensity_value.setText(self._format_intensity(intensity))

    def set_axis_directions(self, affine: np.ndarray | None) -> None:
        if affine is None:
            direction_labels = (None, None, None)
        else:
            direction_labels = physical_axis_direction_labels(affine)

        for axis_name, direction, label in zip(
            ("X", "Y", "Z"),
            direction_labels,
            (self.x_axis_label, self.y_axis_label, self.z_axis_label),
            strict=True,
        ):
            suffix = "" if direction is None else f" ({direction})"
            label.setText(f"{axis_name}{suffix}:")

    @staticmethod
    def _format_intensity(value: float | int | None) -> str:
        if value is None:
            return "-"
        if isinstance(value, np.floating):
            return f"{float(value):.3g}"
        return str(value)

    def set_patch_controls_visible(self, visible: bool) -> None:
        self.patch_group.setVisible(visible)

    def set_patch_controls_enabled(self, enabled: bool) -> None:
        for widget in self._patch_control_widgets():
            widget.setEnabled(enabled)

    def set_patch_activation_available(self, available: bool) -> None:
        self.patch_activation_button.setEnabled(available)

    def set_patch_selection_active(self, active: bool) -> None:
        was_blocked = self.patch_activation_button.blockSignals(True)
        self.patch_activation_button.setChecked(active)
        self.patch_activation_button.setText("Disable" if active else "Enable")
        self.patch_activation_button.blockSignals(was_blocked)

    def set_patch_opacity(self, opacity: float) -> None:
        slider_value = int(round(min(max(opacity, 0.0), 1.0) * 100))
        was_blocked = self.patch_opacity_slider.blockSignals(True)
        self.patch_opacity_slider.setValue(slider_value)
        self.patch_opacity_slider.blockSignals(was_blocked)

    def _on_patch_activation_toggled(self, active: bool) -> None:
        self.patch_activation_button.setText("Disable" if active else "Enable")
        self.patch_activation_toggled.emit(active)

    def _on_opacity_slider_changed(self, slider_value: int) -> None:
        self.patch_opacity_changed.emit(slider_value / 100.0)

    def set_patch_size_xyz(self, size_xyz: tuple[int, int, int]) -> None:
        for spinbox, value in zip(self._patch_size_spinboxes(), size_xyz, strict=True):
            was_blocked = spinbox.blockSignals(True)
            spinbox.setValue(max(1, int(value)))
            spinbox.blockSignals(was_blocked)

    def _on_patch_size_changed(self, _: int) -> None:
        self.patch_size_changed.emit(
            self.patch_width_spinbox.value(),
            self.patch_height_spinbox.value(),
            self.patch_depth_spinbox.value(),
        )

    def _patch_control_widgets(self) -> tuple[QWidget, ...]:
        return (
            self.patch_opacity_slider,
            self.patch_width_spinbox,
            self.patch_height_spinbox,
            self.patch_depth_spinbox,
            self.select_patch_button,
            self.find_patch_box_button,
        )

    def _patch_size_spinboxes(self) -> tuple[QSpinBox, QSpinBox, QSpinBox]:
        return (
            self.patch_width_spinbox,
            self.patch_height_spinbox,
            self.patch_depth_spinbox,
        )
