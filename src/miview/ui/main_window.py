from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QFileDialog, QMainWindow, QSplitter

from miview.ui.cursor_panel import CursorInspectionPanel
from miview.ui.viewer_area import VisualizationPlaceholder


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("MiView")
        self.resize(1100, 700)

        self._setup_central_layout()
        self._setup_menu()
        self.statusBar().showMessage("Ready")

    def _setup_central_layout(self) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.addWidget(VisualizationPlaceholder(splitter))
        splitter.addWidget(CursorInspectionPanel(splitter))
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)

    def _setup_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")

        open_action = QAction("&Open", self)
        open_action.triggered.connect(self._on_open)
        file_menu.addAction(open_action)

        file_menu.addSeparator()

        exit_action = QAction("E&xit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

    def _on_open(self) -> None:
        file_filter = "NIfTI Files (*.nii *.nii.gz);;All Files (*)"
        selected_file, _ = QFileDialog.getOpenFileName(
            self,
            "Open NIfTI File",
            "",
            file_filter,
        )
        if selected_file:
            self.statusBar().showMessage(
                f"Open selected: {selected_file} (loading not implemented yet)"
            )
        else:
            self.statusBar().showMessage("Open canceled")

