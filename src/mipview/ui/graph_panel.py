from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)


class GraphPanel(QWidget):
    activation_requested = Signal()
    visibility_changed = Signal(bool)
    opacity_changed = Signal(float)
    node_size_changed = Signal(int)
    edge_thickness_changed = Signal(int)
    curve_tool_requested = Signal(bool)
    straighten_edge_requested = Signal()
    calculate_angle_requested = Signal()
    cancel_requested = Signal()
    clear_angle_requested = Signal()

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

        group = QGroupBox("Graph", self)
        form = QFormLayout(group)

        self.activation_button = QPushButton("Activate", group)
        self.activation_button.clicked.connect(self.activation_requested.emit)

        self.visible_checkbox = QCheckBox("Visible", group)
        self.visible_checkbox.setChecked(True)
        self.visible_checkbox.toggled.connect(self.visibility_changed.emit)

        self.opacity_slider = QSlider(Qt.Orientation.Horizontal, group)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setValue(100)
        self.opacity_slider.valueChanged.connect(
            lambda value: self.opacity_changed.emit(value / 100.0)
        )

        self.node_size_slider = QSlider(Qt.Orientation.Horizontal, group)
        self.node_size_slider.setRange(1, 10)
        self.node_size_slider.setValue(4)
        self.node_size_slider.valueChanged.connect(self.node_size_changed.emit)

        self.edge_thickness_slider = QSlider(Qt.Orientation.Horizontal, group)
        self.edge_thickness_slider.setRange(1, 10)
        self.edge_thickness_slider.setValue(2)
        self.edge_thickness_slider.valueChanged.connect(
            self.edge_thickness_changed.emit
        )

        tool_row = QWidget(group)
        tool_layout = QHBoxLayout(tool_row)
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

        self.calculate_angle_button = QPushButton("Calculate Angle", group)
        self.calculate_angle_button.clicked.connect(
            self.calculate_angle_requested.emit
        )
        angle_action_row = QWidget(group)
        angle_action_layout = QHBoxLayout(angle_action_row)
        angle_action_layout.setContentsMargins(0, 0, 0, 0)
        angle_action_layout.setSpacing(6)
        self.cancel_button = QPushButton("Cancel", angle_action_row)
        self.cancel_button.clicked.connect(self.cancel_requested.emit)
        angle_action_layout.addWidget(self.cancel_button)
        self.clear_angle_button = QPushButton("Clear Angle", angle_action_row)
        self.clear_angle_button.clicked.connect(self.clear_angle_requested.emit)
        angle_action_layout.addWidget(self.clear_angle_button)
        self.angle_step_label = QLabel("Select Calculate Angle to begin", group)
        self.angle_step_label.setWordWrap(True)
        self.angle_result_label = QLabel("Angle: —", group)

        form.addRow(self.activation_button)
        form.addRow(self.visible_checkbox)
        form.addRow("Opacity:", self.opacity_slider)
        form.addRow("Node Size:", self.node_size_slider)
        form.addRow("Edge Thickness:", self.edge_thickness_slider)
        form.addRow("Curve:", tool_row)
        form.addRow(self.calculate_angle_button)
        form.addRow(angle_action_row)
        form.addRow(self.angle_step_label)
        form.addRow(self.angle_result_label)

        layout = QVBoxLayout(self)
        layout.addWidget(group)
        layout.setContentsMargins(8, 0, 8, 8)

        self.set_projection_available(False)
        self.set_editing_enabled(False)
        self.set_tool_state(
            active_tool=None,
            selected_edge_curved=False,
            angle_selection_step=0,
            angle_degrees=None,
            has_angle_data=False,
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
        angle_selection_step: int,
        angle_degrees: float | None,
        has_angle_data: bool,
    ) -> None:
        was_blocked = self.curve_edge_button.blockSignals(True)
        self.curve_edge_button.setChecked(active_tool == "curve_edge")
        self.curve_edge_button.blockSignals(was_blocked)
        self.straighten_edge_button.setEnabled(
            self.curve_edge_button.isEnabled() and bool(selected_edge_curved)
        )
        self.cancel_button.setEnabled(active_tool == "calculate_angle")
        self.clear_angle_button.setEnabled(
            bool(has_angle_data) or angle_selection_step > 0
        )
        prompts = (
            "Vector 1: select source node",
            "Vector 1: select target node",
            "Vector 2: select source node",
            "Vector 2: select target node",
        )
        if active_tool == "calculate_angle":
            step = min(max(int(angle_selection_step), 0), 3)
            self.angle_step_label.setText(prompts[step])
        else:
            self.angle_step_label.setText("Select Calculate Angle to begin")
        self.angle_result_label.setText(
            "Angle: —"
            if angle_degrees is None
            else f"Angle: {float(angle_degrees):.1f}°"
        )
