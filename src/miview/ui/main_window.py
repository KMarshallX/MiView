from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QFileDialog, QMainWindow, QMessageBox, QSplitter

from miview.io.nifti_loader import load_nifti
from miview.state.app_state import AppState
from miview.ui.cursor_panel import CursorInspectionPanel
from miview.viewer.slice_viewer_widget import SliceViewerWidget


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("MiView")
        self.resize(1100, 700)
        self.state = AppState()
        self.slice_viewer = SliceViewerWidget()
        self.cursor_panel = CursorInspectionPanel()
        self.slice_viewer.cursor_inspection_changed.connect(
            self.cursor_panel.set_cursor_values
        )

        self._setup_central_layout()
        self._setup_menu()
        self.statusBar().showMessage("Ready")

    def _setup_central_layout(self) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.addWidget(self.slice_viewer)
        splitter.addWidget(self.cursor_panel)
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
        if not selected_file:
            self.statusBar().showMessage("Open canceled")
            return

        try:
            loaded = load_nifti(selected_file)
        except (FileNotFoundError, ValueError) as exc:
            QMessageBox.critical(self, "Open Failed", str(exc))
            self.statusBar().showMessage("Open failed")
            return

        loaded_path = Path(selected_file)
        try:
            self.slice_viewer.load_volume(loaded.data)
        except ValueError as exc:
            QMessageBox.critical(self, "Open Failed", str(exc))
            self.statusBar().showMessage("Open failed")
            return

        self.state.loaded_file_path = loaded_path
        self.state.volume = loaded

        self.statusBar().showMessage(
            f"Loaded {loaded_path.name} | shape={loaded.shape} | dtype={loaded.dtype}"
        )
