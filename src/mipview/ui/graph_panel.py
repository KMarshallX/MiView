from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from mipview.ui.collapsible_group_box import CollapsibleGroupBox


class GraphPanel(QWidget):
    activation_requested = Signal()
    visibility_changed = Signal(bool)
    opacity_changed = Signal(float)
    node_size_changed = Signal(int)
    edge_thickness_changed = Signal(int)
    curve_tool_requested = Signal(bool)
    straighten_edge_requested = Signal()
    clear_graph_requested = Signal()
    calculate_angle_requested = Signal(bool)
    cancel_requested = Signal()
    delete_angle_requested = Signal(int)
    clear_angles_requested = Signal()
    save_state_requested = Signal()
    load_state_requested = Signal()

    PANEL_WIDTH = 220
    ADAPTABLE_MINIMUM_WIDTH = 130

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        adaptable_width: bool = False,
    ) -> None:
        super().__init__(parent)
        if adaptable_width:
            self.setMinimumWidth(self.ADAPTABLE_MINIMUM_WIDTH)
            self.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Preferred,
            )
        else:
            self.setFixedWidth(self.PANEL_WIDTH)

        self.group = CollapsibleGroupBox("Graph", self)
        form = QFormLayout(self.group)
        if adaptable_width:
            form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)

        self.activation_button = QPushButton("Activate", self.group)
        self.activation_button.clicked.connect(self.activation_requested.emit)

        self.visible_checkbox = QCheckBox("Visible", self.group)
        self.visible_checkbox.setChecked(True)
        self.visible_checkbox.toggled.connect(self.visibility_changed.emit)

        self.opacity_slider = QSlider(Qt.Orientation.Horizontal, self.group)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setValue(100)
        self.opacity_slider.valueChanged.connect(
            lambda value: self.opacity_changed.emit(value / 100.0)
        )

        self.node_size_slider = QSlider(Qt.Orientation.Horizontal, self.group)
        self.node_size_slider.setRange(1, 10)
        self.node_size_slider.setValue(4)
        self.node_size_slider.valueChanged.connect(self.node_size_changed.emit)

        self.edge_thickness_slider = QSlider(Qt.Orientation.Horizontal, self.group)
        self.edge_thickness_slider.setRange(1, 10)
        self.edge_thickness_slider.setValue(2)
        self.edge_thickness_slider.valueChanged.connect(
            self.edge_thickness_changed.emit
        )

        tool_row = QWidget(self.group)
        tool_layout = (
            QVBoxLayout(tool_row) if adaptable_width else QHBoxLayout(tool_row)
        )
        tool_layout.setContentsMargins(0, 0, 0, 0)
        tool_layout.setSpacing(6)
        self.curve_edge_button = QPushButton("Curve Edge", tool_row)
        self.curve_edge_button.setCheckable(True)
        self.curve_edge_button.toggled.connect(self.curve_tool_requested.emit)
        tool_layout.addWidget(self.curve_edge_button)
        self.straighten_edge_button = QPushButton("Straighten Edge", tool_row)
        self.straighten_edge_button.clicked.connect(
            self.straighten_edge_requested.emit
        )
        tool_layout.addWidget(self.straighten_edge_button)

        self.clear_graph_button = QPushButton("Clear All Nodes & Edges", self.group)
        self.clear_graph_button.clicked.connect(self.clear_graph_requested.emit)

        file_row = QWidget(self.group)
        file_layout = (
            QVBoxLayout(file_row) if adaptable_width else QHBoxLayout(file_row)
        )
        file_layout.setContentsMargins(0, 0, 0, 0)
        file_layout.setSpacing(6)
        self.save_state_button = QPushButton("Save Graph State…", file_row)
        self.save_state_button.clicked.connect(self.save_state_requested.emit)
        file_layout.addWidget(self.save_state_button)
        self.load_state_button = QPushButton("Load Graph State…", file_row)
        self.load_state_button.clicked.connect(self.load_state_requested.emit)
        file_layout.addWidget(self.load_state_button)

        self.calculate_angle_button = QPushButton("Calculate Angle", self.group)
        self.calculate_angle_button.setCheckable(True)
        self.calculate_angle_button.toggled.connect(
            self.calculate_angle_requested.emit
        )
        angle_action_row = QWidget(self.group)
        angle_action_layout = (
            QVBoxLayout(angle_action_row)
            if adaptable_width
            else QHBoxLayout(angle_action_row)
        )
        angle_action_layout.setContentsMargins(0, 0, 0, 0)
        angle_action_layout.setSpacing(6)
        self.cancel_button = QPushButton("Cancel", angle_action_row)
        self.cancel_button.clicked.connect(self.cancel_requested.emit)
        angle_action_layout.addWidget(self.cancel_button)
        self.delete_angle_button = QPushButton("Delete", angle_action_row)
        self.delete_angle_button.clicked.connect(self._emit_delete_angle)
        angle_action_layout.addWidget(self.delete_angle_button)
        self.clear_angles_button = QPushButton("Clear All", angle_action_row)
        self.clear_angles_button.clicked.connect(self.clear_angles_requested.emit)
        angle_action_layout.addWidget(self.clear_angles_button)
        self.angle_step_label = QLabel("Select Calculate Angle to begin", self.group)
        self.angle_step_label.setWordWrap(True)
        self.angle_source_label = QLabel("Source: —", self.group)
        self.angle_measurement_list = QListWidget(self.group)
        self.angle_measurement_list.setMaximumHeight(96)
        self.angle_measurement_list.itemSelectionChanged.connect(
            self._refresh_angle_buttons
        )

        form.addRow(self.activation_button)
        form.addRow(self.visible_checkbox)
        form.addRow("Opacity:", self.opacity_slider)
        form.addRow("Node Size:", self.node_size_slider)
        form.addRow("Edge Thickness:", self.edge_thickness_slider)
        form.addRow("Curve:", tool_row)
        form.addRow(self.clear_graph_button)
        form.addRow(self.calculate_angle_button)
        form.addRow(angle_action_row)
        form.addRow(self.angle_step_label)
        form.addRow(self.angle_source_label)
        form.addRow(self.angle_measurement_list)
        form.addRow(file_row)

        layout = QVBoxLayout(self)
        layout.addWidget(self.group)
        layout.setContentsMargins(8, 0, 8, 8)

        self.set_projection_available(False)
        self.set_editing_enabled(False)
        self.set_tool_state(
            active_tool=None,
            selected_edge_curved=False,
            angle_source_vector_id=None,
            angle_source_color=None,
            measurements=(),
            has_graph_elements=False,
        )

    def set_projection_available(self, available: bool) -> None:
        self.activation_button.setEnabled(bool(available))

    def set_editing_enabled(self, enabled: bool) -> None:
        self.activation_button.setText("Exit" if enabled else "Activate")
        self.curve_edge_button.setEnabled(bool(enabled))
        self.calculate_angle_button.setEnabled(bool(enabled))
        if not enabled:
            self.straighten_edge_button.setEnabled(False)
            self.cancel_button.setEnabled(False)
            was_blocked = self.calculate_angle_button.blockSignals(True)
            self.calculate_angle_button.setChecked(False)
            self.calculate_angle_button.blockSignals(was_blocked)

    def set_visible_checked(self, visible: bool) -> None:
        was_blocked = self.visible_checkbox.blockSignals(True)
        self.visible_checkbox.setChecked(bool(visible))
        self.visible_checkbox.blockSignals(was_blocked)

    def set_opacity(self, opacity: float) -> None:
        value = int(round(min(max(float(opacity), 0.0), 1.0) * 100.0))
        was_blocked = self.opacity_slider.blockSignals(True)
        self.opacity_slider.setValue(value)
        self.opacity_slider.blockSignals(was_blocked)

    def set_node_size(self, node_size: int) -> None:
        was_blocked = self.node_size_slider.blockSignals(True)
        self.node_size_slider.setValue(min(max(int(node_size), 1), 10))
        self.node_size_slider.blockSignals(was_blocked)

    def set_edge_thickness(self, edge_thickness: int) -> None:
        was_blocked = self.edge_thickness_slider.blockSignals(True)
        self.edge_thickness_slider.setValue(
            min(max(int(edge_thickness), 1), 10)
        )
        self.edge_thickness_slider.blockSignals(was_blocked)

    def set_tool_state(
        self,
        *,
        active_tool: str | None,
        selected_edge_curved: bool,
        angle_source_vector_id: int | None,
        angle_source_color: str | None,
        measurements: tuple[tuple[int, int, int, float], ...],
        has_graph_elements: bool,
    ) -> None:
        was_blocked = self.curve_edge_button.blockSignals(True)
        self.curve_edge_button.setChecked(active_tool == "curve_edge")
        self.curve_edge_button.blockSignals(was_blocked)
        was_blocked = self.calculate_angle_button.blockSignals(True)
        self.calculate_angle_button.setChecked(active_tool == "calculate_angle")
        self.calculate_angle_button.blockSignals(was_blocked)
        self.straighten_edge_button.setEnabled(
            self.curve_edge_button.isEnabled() and bool(selected_edge_curved)
        )
        self.cancel_button.setEnabled(active_tool == "calculate_angle")
        self.clear_graph_button.setEnabled(bool(has_graph_elements))
        if active_tool == "calculate_angle":
            self.angle_step_label.setText(
                "Select source vector"
                if angle_source_vector_id is None
                else "Select target vector"
            )
        else:
            self.angle_step_label.setText("Select Calculate Angle to begin")
        if angle_source_vector_id is None or angle_source_color is None:
            self.angle_source_label.setText("Source: —")
            self.angle_source_label.setStyleSheet("")
        else:
            self.angle_source_label.setText(f"Source: V{angle_source_vector_id}")
            self.angle_source_label.setStyleSheet(
                f"border-left: 12px solid {angle_source_color}; padding-left: 4px;"
            )
        selected_id = self.selected_measurement_id()
        self.angle_measurement_list.clear()
        for measurement_id, source_id, target_id, angle in measurements:
            self.angle_measurement_list.addItem(
                f"A{measurement_id}: V{source_id} → V{target_id} = {angle:.1f}°"
            )
            item = self.angle_measurement_list.item(
                self.angle_measurement_list.count() - 1
            )
            item.setData(Qt.ItemDataRole.UserRole, measurement_id)
            if measurement_id == selected_id:
                item.setSelected(True)
        self._refresh_angle_buttons()

    def selected_measurement_id(self) -> int | None:
        items = self.angle_measurement_list.selectedItems()
        if not items:
            return None
        value = items[0].data(Qt.ItemDataRole.UserRole)
        return None if value is None else int(value)

    def _emit_delete_angle(self) -> None:
        measurement_id = self.selected_measurement_id()
        if measurement_id is not None:
            self.delete_angle_requested.emit(measurement_id)

    def _refresh_angle_buttons(self) -> None:
        self.delete_angle_button.setEnabled(self.selected_measurement_id() is not None)
        self.clear_angles_button.setEnabled(self.angle_measurement_list.count() > 0)
