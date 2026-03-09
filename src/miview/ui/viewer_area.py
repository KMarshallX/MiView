from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class VisualizationPlaceholder(QWidget):
    """Central placeholder where image visualization will be added later."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        label = QLabel("Visualization Area", self)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("font-size: 18px; color: #444;")

        layout = QVBoxLayout(self)
        layout.addWidget(label)
        layout.setContentsMargins(12, 12, 12, 12)

