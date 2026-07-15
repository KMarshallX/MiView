from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGroupBox,
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

        form.addRow(self.activation_button)
        form.addRow(self.visible_checkbox)
        form.addRow("Opacity:", self.opacity_slider)
        form.addRow("Node Size:", self.node_size_slider)
        form.addRow("Edge Thickness:", self.edge_thickness_slider)

        layout = QVBoxLayout(self)
        layout.addWidget(group)
        layout.setContentsMargins(8, 0, 8, 8)

        self.set_projection_available(False)

    def set_projection_available(self, available: bool) -> None:
        self.activation_button.setEnabled(bool(available))

    def set_editing_enabled(self, enabled: bool) -> None:
        self.activation_button.setText("Exit" if enabled else "Activate")

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
