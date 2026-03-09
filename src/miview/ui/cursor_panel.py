from __future__ import annotations

import numpy as np
from PySide6.QtWidgets import QFormLayout, QGroupBox, QLabel, QVBoxLayout, QWidget


class CursorInspectionPanel(QWidget):
    """Right-side panel for cursor/voxel readouts."""

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

        layout = QVBoxLayout(self)
        layout.addWidget(group)
        layout.addStretch(1)
        layout.setContentsMargins(8, 8, 8, 8)

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
