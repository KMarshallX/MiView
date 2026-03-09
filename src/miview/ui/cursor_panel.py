from __future__ import annotations

from PySide6.QtWidgets import QFormLayout, QGroupBox, QLabel, QVBoxLayout, QWidget


class CursorInspectionPanel(QWidget):
    """Right-side panel for cursor/voxel readouts."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

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

        layout = QVBoxLayout(self)
        layout.addWidget(group)
        layout.addStretch(1)
        layout.setContentsMargins(8, 8, 8, 8)

