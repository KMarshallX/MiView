from __future__ import annotations

from enum import Enum

from PySide6.QtWidgets import QDialog, QPushButton, QVBoxLayout


class DropLoadChoice(str, Enum):
    BASE_IMAGE = "base_image"
    SEGMENTATION = "segmentation"


class DropLoadChoiceDialog(QDialog):
    def __init__(self, *, allow_segmentation: bool, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Load Dropped File")
        self.setModal(True)
        self._selected_choice: DropLoadChoice | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.base_image_button = QPushButton("Base Image", self)
        self.base_image_button.clicked.connect(
            lambda: self._finish_with_choice(DropLoadChoice.BASE_IMAGE)
        )
        layout.addWidget(self.base_image_button)

        self.segmentation_button = QPushButton("Segmentation", self)
        self.segmentation_button.setEnabled(allow_segmentation)
        self.segmentation_button.clicked.connect(
            lambda: self._finish_with_choice(DropLoadChoice.SEGMENTATION)
        )
        layout.addWidget(self.segmentation_button)

    def selected_choice(self) -> DropLoadChoice | None:
        return self._selected_choice

    def _finish_with_choice(self, choice: DropLoadChoice) -> None:
        self._selected_choice = choice
        self.accept()
