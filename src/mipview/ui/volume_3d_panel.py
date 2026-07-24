from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSlider,
    QWidget,
)

from mipview.ui.collapsible_group_box import CollapsibleGroupBox
from mipview.viewer.render_3d_state import Render3DSettings


class Volume3DPanel(CollapsibleGroupBox):
    """Controls one isolated, manually refreshed NIfTI 3D render."""

    activation_requested = Signal(bool)
    source_changed = Signal(object)
    visibility_changed = Signal(bool)
    opacity_changed = Signal(float)
    colour_changed = Signal(object)
    render_mode_changed = Signal(str)
    mask_changed = Signal(object)
    threshold_changed = Signal(float)
    update_requested = Signal()
    reset_camera_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("3D Volume", parent)
        self._colour = (255, 255, 255)

        form = QFormLayout(self)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)

        self.activation_button = QPushButton("Activate 3D View", self)
        self.activation_button.setCheckable(True)
        self.activation_button.toggled.connect(self._on_activation_toggled)

        self.source_combo = QComboBox(self)
        self.source_combo.currentIndexChanged.connect(
            lambda _index: self.source_changed.emit(self.source_combo.currentData())
        )

        self.visible_checkbox = QCheckBox(self)
        self.visible_checkbox.setChecked(True)
        self.visible_checkbox.toggled.connect(self.visibility_changed.emit)

        self.opacity_slider = QSlider(Qt.Orientation.Horizontal, self)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setValue(100)
        self.opacity_slider.valueChanged.connect(
            lambda value: self.opacity_changed.emit(value / 100.0)
        )

        self.colour_button = QPushButton("Choose…", self)
        self.colour_button.clicked.connect(self._choose_colour)
        self._refresh_colour_button()

        self.render_mode_combo = QComboBox(self)
        self.render_mode_combo.currentTextChanged.connect(
            self._on_render_mode_changed
        )

        self.mask_combo = QComboBox(self)
        self.mask_combo.addItem("---", None)
        self.mask_combo.currentIndexChanged.connect(
            lambda _index: self.mask_changed.emit(self.mask_combo.currentData())
        )
        self.mask_label = QLabel("Mask:", self)

        self.threshold_spinbox = QDoubleSpinBox(self)
        self.threshold_spinbox.setDecimals(4)
        self.threshold_spinbox.setRange(-1.0e12, 1.0e12)
        self.threshold_spinbox.valueChanged.connect(self.threshold_changed.emit)

        action_row = QWidget(self)
        action_layout = QHBoxLayout(action_row)
        action_layout.setContentsMargins(0, 0, 0, 0)
        self.update_button = QPushButton("Update", action_row)
        self.update_button.clicked.connect(self.update_requested.emit)
        self.reset_camera_button = QPushButton("Reset Camera", action_row)
        self.reset_camera_button.clicked.connect(self.reset_camera_requested.emit)
        action_layout.addWidget(self.update_button)
        action_layout.addWidget(self.reset_camera_button)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setVisible(False)

        self.status_label = QLabel("Activate the 3D view to begin.", self)
        self.status_label.setWordWrap(True)

        form.addRow(self.activation_button)
        form.addRow("3D Layer:", self.source_combo)
        form.addRow("Visible:", self.visible_checkbox)
        form.addRow("Opacity:", self.opacity_slider)
        form.addRow("Colour:", self.colour_button)
        form.addRow("Render mode:", self.render_mode_combo)
        form.addRow(self.mask_label, self.mask_combo)
        form.addRow("Threshold:", self.threshold_spinbox)
        form.addRow(action_row)
        form.addRow(self.progress_bar)
        form.addRow(self.status_label)
        self.set_render_controls_enabled(False)
        self._refresh_mask_availability()

    def set_sources(
        self,
        sources: Sequence[tuple[str, str]],
        selected_source_id: str | None,
    ) -> None:
        was_blocked = self.source_combo.blockSignals(True)
        self.source_combo.clear()
        selected_index = -1
        for source_id, display_name in sources:
            self.source_combo.addItem(display_name, source_id)
            if source_id == selected_source_id:
                selected_index = self.source_combo.count() - 1
        if selected_index < 0 and self.source_combo.count() > 0:
            selected_index = 0
        self.source_combo.setCurrentIndex(selected_index)
        self.source_combo.blockSignals(was_blocked)
        self.set_render_controls_enabled(
            self.activation_button.isChecked() and selected_index >= 0
        )

    def selected_source_id(self) -> str | None:
        source_id = self.source_combo.currentData()
        return source_id if isinstance(source_id, str) else None

    def set_modes(self, modes: Sequence[str], selected_mode: str) -> None:
        was_blocked = self.render_mode_combo.blockSignals(True)
        self.render_mode_combo.clear()
        self.render_mode_combo.addItems(list(modes))
        index = self.render_mode_combo.findText(selected_mode)
        self.render_mode_combo.setCurrentIndex(max(index, 0))
        self.render_mode_combo.blockSignals(was_blocked)
        self._refresh_threshold_availability()
        self._refresh_mask_availability()

    def set_masks(
        self,
        masks: Sequence[tuple[str, str]],
        selected_mask_id: str | None,
    ) -> None:
        was_blocked = self.mask_combo.blockSignals(True)
        self.mask_combo.clear()
        self.mask_combo.addItem("---", None)
        selected_index = 0
        for source_id, display_name in masks:
            self.mask_combo.addItem(display_name, source_id)
            if source_id == selected_mask_id:
                selected_index = self.mask_combo.count() - 1
        self.mask_combo.setCurrentIndex(selected_index)
        self.mask_combo.blockSignals(was_blocked)
        self._refresh_mask_availability()

    def set_settings(self, settings: Render3DSettings) -> None:
        blockers: list[tuple[QWidget, bool]] = []
        for widget in (
            self.visible_checkbox,
            self.opacity_slider,
            self.mask_combo,
            self.threshold_spinbox,
        ):
            blockers.append((widget, widget.blockSignals(True)))
        self.visible_checkbox.setChecked(settings.visible)
        self.opacity_slider.setValue(int(round(settings.opacity * 100.0)))
        self.threshold_spinbox.setValue(settings.threshold)
        mask_index = self.mask_combo.findData(settings.mask_source_id)
        self.mask_combo.setCurrentIndex(max(mask_index, 0))
        for widget, blocked in blockers:
            widget.blockSignals(blocked)

        self._colour = settings.colour
        self._refresh_colour_button()
        index = self.render_mode_combo.findText(settings.render_mode)
        if index >= 0:
            was_blocked = self.render_mode_combo.blockSignals(True)
            self.render_mode_combo.setCurrentIndex(index)
            self.render_mode_combo.blockSignals(was_blocked)
        self._refresh_threshold_availability()
        self._refresh_mask_availability()
        self.set_status(
            "Update required." if settings.dirty else "3D layer ready."
        )

    def set_active(self, active: bool) -> None:
        was_blocked = self.activation_button.blockSignals(True)
        self.activation_button.setChecked(active)
        self.activation_button.setText(
            "Dismiss 3D View" if active else "Activate 3D View"
        )
        self.activation_button.blockSignals(was_blocked)
        self.set_render_controls_enabled(
            active and self.source_combo.currentIndex() >= 0
        )

    def set_render_controls_enabled(self, enabled: bool) -> None:
        for widget in (
            self.source_combo,
            self.visible_checkbox,
            self.opacity_slider,
            self.colour_button,
            self.render_mode_combo,
            self.mask_combo,
            self.threshold_spinbox,
            self.update_button,
            self.reset_camera_button,
        ):
            widget.setEnabled(enabled)
        self._refresh_threshold_availability()
        self._refresh_mask_availability()

    def set_busy(self, busy: bool, message: str = "Preparing 3D layer…") -> None:
        self.progress_bar.setVisible(busy)
        if busy:
            self.progress_bar.setRange(0, 0)
            self.status_label.setText(message)
        else:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
        self.update_button.setEnabled(
            not busy
            and self.activation_button.isChecked()
            and self.source_combo.currentIndex() >= 0
        )

    def set_progress(self, value: int, message: str) -> None:
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(min(max(int(value), 0), 100))
        self.status_label.setText(message)

    def set_status(self, message: str) -> None:
        self.status_label.setText(message)

    def current_colour(self) -> tuple[int, int, int]:
        return self._colour

    def _on_activation_toggled(self, active: bool) -> None:
        self.activation_button.setText(
            "Dismiss 3D View" if active else "Activate 3D View"
        )
        self.set_render_controls_enabled(
            active and self.source_combo.currentIndex() >= 0
        )
        self.activation_requested.emit(active)

    def _on_render_mode_changed(self, render_mode: str) -> None:
        self._refresh_threshold_availability()
        self._refresh_mask_availability()
        self.render_mode_changed.emit(render_mode)

    def _choose_colour(self) -> None:
        selected = QColorDialog.getColor(QColor(*self._colour), self, "3D Layer Colour")
        if not selected.isValid():
            return
        self._colour = (selected.red(), selected.green(), selected.blue())
        self._refresh_colour_button()
        self.colour_changed.emit(self._colour)

    def _refresh_colour_button(self) -> None:
        red, green, blue = self._colour
        foreground = "#000" if red + green + blue > 420 else "#fff"
        self.colour_button.setStyleSheet(
            f"background-color: rgb({red}, {green}, {blue}); color: {foreground};"
        )

    def _refresh_threshold_availability(self) -> None:
        mode = self.render_mode_combo.currentText()
        active = self.activation_button.isChecked()
        self.threshold_spinbox.setEnabled(
            active and mode in {"Translucent", "Isosurface", "Surface", "Points"}
        )

    def _refresh_mask_availability(self) -> None:
        mode = self.render_mode_combo.currentText()
        visible = mode in {"MIP", "MinIP", "Surface", "Points"}
        self.mask_label.setVisible(visible)
        self.mask_combo.setVisible(visible)
        self.mask_combo.setEnabled(
            visible
            and self.activation_button.isChecked()
            and self.source_combo.currentIndex() >= 0
        )
