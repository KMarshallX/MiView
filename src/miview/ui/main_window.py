from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QSplitter,
)

from miview.io.nifti_loader import load_nifti
from miview.state.app_state import AppState
from miview.ui.cursor_panel import CursorInspectionPanel
from miview.viewer.triplanar_viewer_widget import TriPlanarViewerWidget


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("MiView")
        self.resize(1100, 700)
        self.state = AppState()
        self.slice_viewer = TriPlanarViewerWidget()
        self.cursor_panel = CursorInspectionPanel()
        self.loading_progress_bar = QProgressBar(self)
        self._loading_hide_timer = QTimer(self)
        self._loading_hide_timer.setSingleShot(True)
        self._loading_hide_timer.timeout.connect(self._hide_loading_progress)
        self.slice_viewer.cursor_inspection_changed.connect(
            self.cursor_panel.set_cursor_values
        )
        self.slice_viewer.cursor_state.cursor_changed.connect(self._update_cursor_position)

        self._setup_central_layout()
        self._setup_loading_progress_bar()
        self._setup_menu()
        self.statusBar().showMessage("Ready")

    def _setup_central_layout(self) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.addWidget(self.slice_viewer)
        splitter.addWidget(self.cursor_panel)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)

    def _setup_loading_progress_bar(self) -> None:
        self.loading_progress_bar.setRange(0, 0)
        self.loading_progress_bar.setVisible(False)
        self.loading_progress_bar.setTextVisible(False)
        self.loading_progress_bar.setFixedWidth(180)
        self.statusBar().addPermanentWidget(self.loading_progress_bar)

    def _setup_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        view_menu = self.menuBar().addMenu("&View")

        open_action = QAction("&Open", self)
        open_action.triggered.connect(self._on_open)
        file_menu.addAction(open_action)

        unload_action = QAction("&Unload Image", self)
        unload_action.triggered.connect(self._on_unload)
        file_menu.addAction(unload_action)

        file_menu.addSeparator()

        exit_action = QAction("E&xit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        cursor_overlay_action = QAction("Show &Cursor Overlay", self)
        cursor_overlay_action.setCheckable(True)
        cursor_overlay_action.setChecked(True)
        cursor_overlay_action.toggled.connect(
            self.slice_viewer.set_cursor_overlay_visible
        )
        view_menu.addAction(cursor_overlay_action)

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

        self._show_loading_progress()

        try:
            loaded = load_nifti(selected_file)
        except (FileNotFoundError, ValueError) as exc:
            QMessageBox.critical(self, "Open Failed", str(exc))
            self.statusBar().showMessage("Open failed")
            self._schedule_loading_progress_hide()
            return

        loaded_path = Path(selected_file)
        try:
            self.slice_viewer.load_volume(loaded)
        except ValueError as exc:
            QMessageBox.critical(self, "Open Failed", str(exc))
            self.statusBar().showMessage("Open failed")
            self._schedule_loading_progress_hide()
            return

        self.state.loaded_file_path = loaded_path
        self.state.volume = loaded
        self.state.cursor_position = self.slice_viewer.current_cursor_position()

        self.statusBar().showMessage(
            f"Loaded {loaded_path.name} | shape={loaded.shape} | dtype={loaded.dtype}"
        )
        self._schedule_loading_progress_hide()

    def _on_unload(self) -> None:
        self.slice_viewer.unload_volume()
        self.state.loaded_file_path = None
        self.state.volume = None
        self.state.cursor_position = None
        self.cursor_panel.set_cursor_values(None, None, None, None)
        self.statusBar().showMessage("Ready")

    def _update_cursor_position(
        self, x: int, y: int, z: int
    ) -> None:
        self.state.cursor_position = (x, y, z)

    def _show_loading_progress(self) -> None:
        self._loading_hide_timer.stop()
        self.loading_progress_bar.setVisible(True)
        self.statusBar().showMessage("Loading image...")
        QApplication.processEvents()

    def _schedule_loading_progress_hide(self) -> None:
        self._loading_hide_timer.start(50)

    def _hide_loading_progress(self) -> None:
        self.loading_progress_bar.setVisible(False)
