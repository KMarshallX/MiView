from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
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
    opacity_changed = Signal(float)
    vessel_graph_node_size_changed = Signal(int)
    vessel_graph_edge_thickness_changed = Signal(int)
    vessel_graph_unload_requested = Signal(object)
    colour_changed = Signal(object)
    render_mode_changed = Signal(str)
    mask_changed = Signal(object)
    threshold_changed = Signal(float)
    update_requested = Signal()
    reset_camera_requested = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        allow_vessel_graph_unload: bool = False,
    ) -> None:
        super().__init__("3D Volume", parent)
        self._colour = (255, 255, 255)
        self._source_kind: str | None = None

        form = QFormLayout(self)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)

        self.activation_button = QPushButton("Activate 3D View", self)
        self.activation_button.setCheckable(True)
        self.activation_button.toggled.connect(self._on_activation_toggled)

        self.source_combo = QComboBox(self)
        self.source_combo.currentIndexChanged.connect(
            lambda _index: self.source_changed.emit(self.source_combo.currentData())
        )

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

        self.vessel_graph_group = QGroupBox("Vessel Graph", self)
        vessel_form = QFormLayout(self.vessel_graph_group)
        vessel_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.vessel_graph_opacity_slider = QSlider(
            Qt.Orientation.Horizontal,
            self.vessel_graph_group,
        )
        self.vessel_graph_opacity_slider.setRange(0, 100)
        self.vessel_graph_opacity_slider.setValue(100)
        self.vessel_graph_opacity_slider.valueChanged.connect(
            lambda value: self.opacity_changed.emit(value / 100.0)
        )
        self.vessel_graph_node_size_slider = QSlider(
            Qt.Orientation.Horizontal,
            self.vessel_graph_group,
        )
        self.vessel_graph_node_size_slider.setRange(1, 10)
        self.vessel_graph_node_size_slider.setValue(4)
        self.vessel_graph_node_size_slider.valueChanged.connect(
            self.vessel_graph_node_size_changed.emit
        )
        self.vessel_graph_edge_thickness_slider = QSlider(
            Qt.Orientation.Horizontal,
            self.vessel_graph_group,
        )
        self.vessel_graph_edge_thickness_slider.setRange(1, 10)
        self.vessel_graph_edge_thickness_slider.setValue(2)
        self.vessel_graph_edge_thickness_slider.valueChanged.connect(
            self.vessel_graph_edge_thickness_changed.emit
        )
        vessel_form.addRow("Opacity:", self.vessel_graph_opacity_slider)
        vessel_form.addRow("Node size:", self.vessel_graph_node_size_slider)
        vessel_form.addRow(
            "Edge thickness:",
            self.vessel_graph_edge_thickness_slider,
        )
        if allow_vessel_graph_unload:
            self.vessel_graph_unload_button = QPushButton(
                "Unload Current Graph",
                self.vessel_graph_group,
            )
            self.vessel_graph_unload_button.clicked.connect(
                lambda: self.vessel_graph_unload_requested.emit(
                    self.selected_source_id()
                )
            )
            vessel_form.addRow(self.vessel_graph_unload_button)
        else:
            self.vessel_graph_unload_button = None
        self.vessel_graph_group.setVisible(False)

        self.opacity_label = QLabel("Opacity:", self)
        form.addRow(self.activation_button)
        form.addRow("3D Layer:", self.source_combo)
        form.addRow(self.opacity_label, self.opacity_slider)
        form.addRow("Colour:", self.colour_button)
        form.addRow("Render mode:", self.render_mode_combo)
        form.addRow(self.mask_label, self.mask_combo)
        form.addRow("Threshold:", self.threshold_spinbox)
        form.addRow(action_row)
        form.addRow(self.progress_bar)
        form.addRow(self.status_label)
        form.addRow(self.vessel_graph_group)
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
            self.opacity_slider,
            self.vessel_graph_opacity_slider,
            self.vessel_graph_node_size_slider,
            self.vessel_graph_edge_thickness_slider,
            self.mask_combo,
            self.threshold_spinbox,
        ):
            blockers.append((widget, widget.blockSignals(True)))
        self.opacity_slider.setValue(int(round(settings.opacity * 100.0)))
        self.vessel_graph_opacity_slider.setValue(
            int(round(settings.opacity * 100.0))
        )
        self.vessel_graph_node_size_slider.setValue(settings.node_size)
        self.vessel_graph_edge_thickness_slider.setValue(
            settings.edge_thickness
        )
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
            self.opacity_slider,
            self.update_button,
            self.reset_camera_button,
        ):
            widget.setEnabled(enabled)
        is_graph = self._source_kind == "vessel_graph"
        self.colour_button.setEnabled(enabled and not is_graph)
        self.render_mode_combo.setEnabled(enabled and not is_graph)
        self.mask_combo.setEnabled(enabled and not is_graph)
        self.threshold_spinbox.setEnabled(enabled and not is_graph)
        self.vessel_graph_opacity_slider.setEnabled(enabled and is_graph)
        self.vessel_graph_node_size_slider.setEnabled(enabled and is_graph)
        self.vessel_graph_edge_thickness_slider.setEnabled(
            enabled and is_graph
        )
        if self.vessel_graph_unload_button is not None:
            self.vessel_graph_unload_button.setEnabled(is_graph)
        self._refresh_threshold_availability()
        self._refresh_mask_availability()

    def set_source_kind(self, source_kind: str | None) -> None:
        self._source_kind = source_kind
        is_graph = source_kind == "vessel_graph"
        self.vessel_graph_group.setVisible(is_graph)
        self.opacity_label.setVisible(not is_graph)
        self.opacity_slider.setVisible(not is_graph)
        self._refresh_threshold_availability()
        self._refresh_mask_availability()
        self.set_render_controls_enabled(
            self.activation_button.isChecked()
            and self.source_combo.currentIndex() >= 0
        )

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
            active
            and self._source_kind != "vessel_graph"
            and mode in {"Translucent", "Isosurface", "Surface", "Points"}
        )

    def _refresh_mask_availability(self) -> None:
        mode = self.render_mode_combo.currentText()
        visible = (
            self._source_kind != "vessel_graph"
            and mode in {"MIP", "MinIP", "Surface", "Points"}
        )
        self.mask_label.setVisible(visible)
        self.mask_combo.setVisible(visible)
        self.mask_combo.setEnabled(
            visible
            and self.activation_button.isChecked()
            and self.source_combo.currentIndex() >= 0
        )
