from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class AnnotationPanel(QWidget):
    create_requested = Signal()
    load_requested = Signal()
    save_requested = Signal()
    visibility_changed = Signal(bool)
    opacity_changed = Signal(float)
    active_label_changed = Signal(int)
    brush_radius_changed = Signal(int)
    brush_mode_changed = Signal(str)
    undo_requested = Signal()

    PANEL_WIDTH = 220

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(self.PANEL_WIDTH)
        self._annotation_editing_enabled = False

        group = QGroupBox("Annotation", self)
        form = QFormLayout(group)

        self.create_button = QPushButton("Create", group)
        self.create_button.clicked.connect(self.create_requested.emit)
        self.load_button = QPushButton("Load", group)
        self.load_button.clicked.connect(self.load_requested.emit)
        self.save_button = QPushButton("Save", group)
        self.save_button.clicked.connect(self.save_requested.emit)

        action_row = QWidget(group)
        action_layout = QHBoxLayout(action_row)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.addWidget(self.create_button)
        action_layout.addWidget(self.load_button)
        action_layout.addWidget(self.save_button)

        self.visible_checkbox = QCheckBox("Visible", group)
        self.visible_checkbox.setChecked(True)
        self.visible_checkbox.toggled.connect(self.visibility_changed.emit)

        self.opacity_slider = QSlider(Qt.Orientation.Horizontal, group)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setValue(50)
        self.opacity_slider.valueChanged.connect(self._on_opacity_changed)

        self.active_label_spinbox = QSpinBox(group)
        self.active_label_spinbox.setRange(1, 65535)
        self.active_label_spinbox.setValue(1)
        self.active_label_spinbox.valueChanged.connect(self.active_label_changed.emit)

        self.brush_radius_spinbox = QSpinBox(group)
        self.brush_radius_spinbox.setRange(0, 99)
        self.brush_radius_spinbox.setValue(1)
        self.brush_radius_spinbox.setSuffix(" vox")
        self.brush_radius_spinbox.valueChanged.connect(self.brush_radius_changed.emit)

        mode_row = QWidget(group)
        mode_layout = QHBoxLayout(mode_row)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        self.paint_button = QPushButton("Paint", mode_row)
        self.paint_button.setCheckable(True)
        self.cursor_button = QPushButton("Cursor", mode_row)
        self.cursor_button.setCheckable(True)
        self.erase_button = QPushButton("Erase", mode_row)
        self.erase_button.setCheckable(True)
        self.mode_button_group = QButtonGroup(mode_row)
        self.mode_button_group.setExclusive(True)
        self.mode_button_group.addButton(self.paint_button)
        self.mode_button_group.addButton(self.cursor_button)
        self.mode_button_group.addButton(self.erase_button)
        self.paint_button.setChecked(True)
        self.paint_button.toggled.connect(
            lambda checked: checked and self.brush_mode_changed.emit("paint")
        )
        self.cursor_button.toggled.connect(
            lambda checked: checked and self.brush_mode_changed.emit("cursor")
        )
        self.erase_button.toggled.connect(
            lambda checked: checked and self.brush_mode_changed.emit("erase")
        )
        mode_layout.addWidget(self.paint_button)
        mode_layout.addWidget(self.cursor_button)
        mode_layout.addWidget(self.erase_button)

        self.undo_button = QPushButton("Undo", group)
        self.undo_button.setEnabled(False)
        self.undo_button.clicked.connect(self.undo_requested.emit)

        form.addRow(action_row)
        form.addRow(self.visible_checkbox)
        form.addRow("Opacity:", self.opacity_slider)
        form.addRow("Active Label:", self.active_label_spinbox)
        form.addRow("Brush Radius:", self.brush_radius_spinbox)
        form.addRow("Mode:", mode_row)
        form.addRow(self.undo_button)

        layout = QVBoxLayout(self)
        layout.addWidget(group)
        layout.setContentsMargins(8, 0, 8, 8)

        self.set_image_loaded(False)
        self.set_annotation_active(False)

    def set_image_loaded(self, loaded: bool) -> None:
        self.create_button.setEnabled(loaded)
        self.load_button.setEnabled(loaded)
        if not loaded:
            self.set_annotation_active(False)

    def set_annotation_active(
        self,
        active: bool,
        *,
        editing_enabled: bool | None = None,
        can_undo: bool = False,
    ) -> None:
        editing = active if editing_enabled is None else active and editing_enabled
        self._annotation_editing_enabled = editing
        self.create_button.setText("Exit..." if editing else "Create")
        for widget in (
            self.save_button,
            self.visible_checkbox,
            self.opacity_slider,
            self.active_label_spinbox,
            self.brush_radius_spinbox,
            self.paint_button,
            self.cursor_button,
            self.erase_button,
        ):
            widget.setEnabled(editing)
        self.undo_button.setEnabled(editing and can_undo)

    def set_undo_available(self, available: bool) -> None:
        self.undo_button.setEnabled(self._annotation_editing_enabled and available)

    def set_visible_checked(self, visible: bool) -> None:
        was_blocked = self.visible_checkbox.blockSignals(True)
        self.visible_checkbox.setChecked(visible)
        self.visible_checkbox.blockSignals(was_blocked)

    def set_opacity(self, opacity: float) -> None:
        value = int(round(min(max(float(opacity), 0.0), 1.0) * 100.0))
        was_blocked = self.opacity_slider.blockSignals(True)
        self.opacity_slider.setValue(value)
        self.opacity_slider.blockSignals(was_blocked)

    def set_active_label(self, label: int) -> None:
        was_blocked = self.active_label_spinbox.blockSignals(True)
        self.active_label_spinbox.setValue(max(1, int(label)))
        self.active_label_spinbox.blockSignals(was_blocked)

    def set_brush_radius(self, radius: int) -> None:
        was_blocked = self.brush_radius_spinbox.blockSignals(True)
        self.brush_radius_spinbox.setValue(max(0, int(radius)))
        self.brush_radius_spinbox.blockSignals(was_blocked)

    def set_brush_mode(self, mode: str) -> None:
        if mode == "erase":
            target = self.erase_button
        elif mode == "cursor":
            target = self.cursor_button
        else:
            target = self.paint_button
        was_paint_blocked = self.paint_button.blockSignals(True)
        was_cursor_blocked = self.cursor_button.blockSignals(True)
        was_erase_blocked = self.erase_button.blockSignals(True)
        target.setChecked(True)
        self.paint_button.blockSignals(was_paint_blocked)
        self.cursor_button.blockSignals(was_cursor_blocked)
        self.erase_button.blockSignals(was_erase_blocked)

    def _on_opacity_changed(self, value: int) -> None:
        self.opacity_changed.emit(value / 100.0)
