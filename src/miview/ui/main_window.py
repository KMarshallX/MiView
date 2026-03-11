from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QSizePolicy,
    QVBoxLayout,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QSplitter,
    QWidget,
)

from miview.io.nifti_loader import load_nifti
from miview.patch.extractor import extract_patch
from miview.state.app_state import AppState
from miview.state.contrast_state import ContrastState
from miview.ui.contrast_control_bar import ContrastControlBar
from miview.ui.cursor_panel import CursorInspectionPanel
from miview.ui.patch_window import PatchViewerWindow
from miview.viewer.intensity import robust_auto_window, volume_intensity_range
from miview.viewer.triplanar_viewer_widget import TriPlanarViewerWidget


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("MiView")
        self.resize(1100, 700)
        self.state = AppState()
        self.contrast_state = ContrastState(self)
        self.slice_viewer = TriPlanarViewerWidget()
        self.cursor_panel = CursorInspectionPanel()
        self.contrast_control_bar = ContrastControlBar(self)
        self.cursor_overlay_action: QAction | None = None
        self._cursor_overlay_checked_before_patch = True
        self.patch_toggle_action: QAction | None = None
        self.loading_progress_bar = QProgressBar(self)
        self._loading_hide_timer = QTimer(self)
        self._patch_windows: list[PatchViewerWindow] = []
        self._loading_hide_timer.setSingleShot(True)
        self._loading_hide_timer.timeout.connect(self._hide_loading_progress)
        self.slice_viewer.cursor_inspection_changed.connect(
            self.cursor_panel.set_cursor_values
        )
        self.slice_viewer.cursor_state.cursor_changed.connect(self._update_cursor_position)
        self.slice_viewer.patch_selection_changed.connect(self._on_patch_selection_changed)
        self.contrast_control_bar.window_changed.connect(self.contrast_state.set_window)
        self.contrast_control_bar.auto_requested.connect(self._on_auto_contrast)
        self.cursor_panel.patch_opacity_changed.connect(self.slice_viewer.set_patch_overlay_opacity)
        self.cursor_panel.patch_size_changed.connect(self._on_patch_size_changed)
        self.cursor_panel.select_patch_requested.connect(self._on_select_patch)
        self.cursor_panel.find_patch_box_requested.connect(self._on_find_patch_box)
        self.contrast_state.availability_changed.connect(
            self.contrast_control_bar.set_enabled_state
        )
        self.contrast_state.range_changed.connect(self.contrast_control_bar.set_available_range)
        self.contrast_state.window_changed.connect(self.contrast_control_bar.set_window)
        self.contrast_state.window_changed.connect(self.slice_viewer.set_contrast_window)

        self._setup_central_layout()
        self._setup_menu()
        self.cursor_panel.set_patch_opacity(self.slice_viewer.patch_overlay_opacity())
        self.cursor_panel.set_patch_size_xyz(self.slice_viewer.patch_size_xyz())
        self.statusBar().showMessage("Ready")

    def _setup_central_layout(self) -> None:
        content_widget = QWidget(self)
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.addWidget(self.slice_viewer)
        splitter.addWidget(self.cursor_panel)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)

        content_layout.addWidget(self.contrast_control_bar)
        content_layout.addWidget(splitter, 1)
        self._setup_loading_progress_bar()
        content_layout.addWidget(self.loading_progress_bar)
        self.setCentralWidget(content_widget)

    def _setup_loading_progress_bar(self) -> None:
        self.loading_progress_bar.setRange(0, 0)
        self.loading_progress_bar.setVisible(False)
        self.loading_progress_bar.setTextVisible(False)
        self.loading_progress_bar.setFixedHeight(8)
        self.loading_progress_bar.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )

    def _setup_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        view_menu = self.menuBar().addMenu("&View")
        tool_menu = self.menuBar().addMenu("&Tool")

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

        self.cursor_overlay_action = QAction("Show &Cursor Overlay", self)
        self.cursor_overlay_action.setCheckable(True)
        self.cursor_overlay_action.setChecked(True)
        self.cursor_overlay_action.toggled.connect(
            self.slice_viewer.set_cursor_overlay_visible
        )
        view_menu.addAction(self.cursor_overlay_action)

        self.patch_toggle_action = QAction("&Patch Selection", self)
        self.patch_toggle_action.setCheckable(True)
        self.patch_toggle_action.setChecked(False)
        self.patch_toggle_action.toggled.connect(self._on_patch_selection_toggled)
        tool_menu.addAction(self.patch_toggle_action)

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
        self.state.selected_patch_bounds = None
        self.state.selected_patch_data = None
        self._initialize_contrast_for_loaded_volume()

        self.statusBar().showMessage(
            f"Loaded {loaded_path.name} | shape={loaded.shape} | dtype={loaded.dtype}"
        )
        self._schedule_loading_progress_hide()

    def _on_unload(self) -> None:
        self.slice_viewer.unload_volume()
        self.contrast_state.clear()
        self.state.loaded_file_path = None
        self.state.volume = None
        self.state.cursor_position = None
        self.state.selected_patch_bounds = None
        self.state.selected_patch_data = None
        if self.patch_toggle_action is not None:
            was_blocked = self.patch_toggle_action.blockSignals(True)
            self.patch_toggle_action.setChecked(False)
            self.patch_toggle_action.blockSignals(was_blocked)
        self.slice_viewer.set_patch_selection_enabled(False)
        if self.cursor_overlay_action is not None:
            self.cursor_overlay_action.setEnabled(True)
            self.slice_viewer.set_cursor_overlay_visible(self.cursor_overlay_action.isChecked())
        self.cursor_panel.set_patch_controls_visible(False)
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

    def _initialize_contrast_for_loaded_volume(self) -> None:
        if self.state.volume is None:
            self.contrast_state.clear()
            return

        range_min, range_max = volume_intensity_range(self.state.volume.data)
        self.contrast_state.set_available_range(range_min, range_max)
        self.contrast_state.set_window(range_min, range_max, force_emit=True)

    def _on_auto_contrast(self) -> None:
        if self.state.volume is None or not self.contrast_state.is_enabled():
            return
        window_min, window_max = robust_auto_window(self.state.volume.data)
        self.contrast_state.set_window(window_min, window_max)

    def _on_patch_selection_toggled(self, enabled: bool) -> None:
        self.slice_viewer.set_patch_selection_enabled(enabled)
        self.cursor_panel.set_patch_controls_visible(enabled)
        if self.cursor_overlay_action is not None:
            if enabled:
                self._cursor_overlay_checked_before_patch = self.cursor_overlay_action.isChecked()
                self.cursor_overlay_action.setChecked(False)
                self.cursor_overlay_action.setEnabled(False)
                self.slice_viewer.set_cursor_overlay_visible(False)
            else:
                self.cursor_overlay_action.setEnabled(True)
                self.cursor_overlay_action.setChecked(self._cursor_overlay_checked_before_patch)
        if enabled:
            self.cursor_panel.set_patch_opacity(self.slice_viewer.patch_overlay_opacity())
            self.cursor_panel.set_patch_size_xyz(self.slice_viewer.patch_size_xyz())

    def _on_select_patch(self) -> None:
        if self.state.volume is None:
            return

        bounds = self.slice_viewer.current_patch_bounds()
        center = self.slice_viewer.current_patch_center()
        if bounds is None:
            return

        extracted = extract_patch(self.state.volume, bounds)
        self.state.selected_patch_bounds = bounds
        self.state.selected_patch_data = extracted

        source_image_name = (
            self.state.loaded_file_path.name
            if self.state.loaded_file_path is not None
            else "image.nii.gz"
        )
        patch_window = PatchViewerWindow(
            extracted,
            self,
            source_image_name=source_image_name,
            patch_center=center,
            patch_size=self.slice_viewer.patch_size_xyz(),
        )
        patch_window.show()
        self._patch_windows.append(patch_window)
        patch_window.destroyed.connect(
            lambda _: self._patch_windows.remove(patch_window)
            if patch_window in self._patch_windows
            else None
        )

    def _on_patch_selection_changed(self, bounds: object) -> None:
        self.state.selected_patch_bounds = bounds if bounds is not None else None
        self.cursor_panel.set_patch_size_xyz(self.slice_viewer.patch_size_xyz())

    def _on_patch_size_changed(self, width_lr: int, height_ap: int, depth_si: int) -> None:
        self.slice_viewer.set_patch_size_xyz((width_lr, height_ap, depth_si))

    def _on_find_patch_box(self) -> None:
        self.slice_viewer.recenter_views_on_patch_box()
