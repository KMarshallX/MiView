from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QEvent, QObject, QPoint, QTimer, Qt
from PySide6.QtGui import QAction, QDragEnterEvent, QDragMoveEvent, QDropEvent, QResizeEvent
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

from mipview.nifti_io import load_nifti
from mipview.patch_extractor import extract_patch
from mipview.patch_selector import PatchBounds
from mipview.segmentation_models import LoadedSegmentation
from mipview.segmentation_validation import validate_segmentation_compatibility
from mipview.state.app_state import AppState
from mipview.state.contrast_state import ContrastState
from mipview.tools import get_tool
from mipview.ui.contrast_helpers import (
    apply_auto_contrast,
    connect_contrast_controls,
    initialize_contrast_state,
)
from mipview.ui.contrast_control_bar import ContrastControlBar
from mipview.ui.cursor_panel import CursorInspectionPanel
from mipview.ui.drop_load_choice_dialog import DropLoadChoice, DropLoadChoiceDialog
from mipview.ui.drop_loading import first_supported_local_nifti_path
from mipview.ui.patch_window import PatchViewerWindow
from mipview.ui.segmentation_config_window import SegmentationConfigWindow
from mipview.ui.tool_actions import apply_tool_to_volume
from mipview.ui.tools_menu import build_tools_submenu
from mipview.ui.window_styling import (
    ResponsiveFontScaler,
    apply_window_content_frame,
)
from mipview.viewer.triplanar_viewer_widget import TriPlanarViewerWidget


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("MipView")
        self.resize(1100, 700)
        self.state = AppState()
        self._font_scaler = ResponsiveFontScaler(
            self,
            reference_width=1100,
            reference_height=700,
        )
        self.contrast_state = ContrastState(self)
        self.slice_viewer = TriPlanarViewerWidget()
        self.cursor_panel = CursorInspectionPanel()
        self.contrast_control_bar = ContrastControlBar(self)
        self.cursor_overlay_action: QAction | None = None
        self._cursor_overlay_checked_before_patch = True
        self.patch_toggle_action: QAction | None = None
        self.load_segmentation_action: QAction | None = None
        self.unload_current_segmentation_action: QAction | None = None
        self.open_segmentation_config_action: QAction | None = None
        self.loading_progress_bar = QProgressBar(self)
        self._loading_hide_timer = QTimer(self)
        self._patch_windows: list[PatchViewerWindow] = []
        self._content_widget: QWidget | None = None
        self._main_splitter: QSplitter | None = None
        self.segmentation_config_window = SegmentationConfigWindow(self)
        self.setAcceptDrops(True)
        self._loading_hide_timer.setSingleShot(True)
        self._loading_hide_timer.timeout.connect(self._hide_loading_progress)
        self.segmentation_config_window.active_segmentation_changed.connect(
            self._on_active_segmentation_changed
        )
        self.segmentation_config_window.opacity_changed.connect(
            self._on_segmentation_opacity_changed
        )
        self.slice_viewer.cursor_inspection_changed.connect(
            self.cursor_panel.set_cursor_values
        )
        self.slice_viewer.nifti_file_dropped.connect(self._on_viewer_nifti_file_dropped)
        self.slice_viewer.cursor_state.cursor_changed.connect(self._update_cursor_position)
        self.slice_viewer.patch_selection_changed.connect(self._on_patch_selection_changed)
        self.cursor_panel.patch_opacity_changed.connect(self.slice_viewer.set_patch_overlay_opacity)
        self.cursor_panel.patch_size_changed.connect(self._on_patch_size_changed)
        self.cursor_panel.select_patch_requested.connect(self._on_select_patch)
        self.cursor_panel.find_patch_box_requested.connect(self._on_find_patch_box)
        connect_contrast_controls(
            self.contrast_control_bar,
            self.contrast_state,
            self.slice_viewer,
            self._on_auto_contrast,
        )

        self._setup_central_layout()
        self._setup_menu()
        self.slice_viewer.set_drop_loading_enabled(True)
        self.cursor_panel.set_patch_opacity(self.slice_viewer.patch_overlay_opacity())
        self.cursor_panel.set_patch_size_xyz(self.slice_viewer.patch_size_xyz())
        self.segmentation_config_window.set_opacity(self.state.segmentation_opacity)
        self._refresh_segmentation_ui()
        self._font_scaler.apply()
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
        content_widget.setAcceptDrops(True)
        splitter.setAcceptDrops(True)
        content_widget.installEventFilter(self)
        splitter.installEventFilter(self)
        self._content_widget = content_widget
        self._main_splitter = splitter

        content_layout.addWidget(self.contrast_control_bar)
        content_layout.addWidget(splitter, 1)
        self._setup_loading_progress_bar()
        content_layout.addWidget(self.loading_progress_bar)
        apply_window_content_frame(self, content_widget)
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
        segmentation_menu = self.menuBar().addMenu("&Segmentation")
        tools_menu = self.menuBar().addMenu("&Tools")

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
        tools_menu.addAction(self.patch_toggle_action)
        build_tools_submenu(
            self,
            tools_menu,
            self._on_apply_tool_to_main_image_requested,
        )

        self.load_segmentation_action = QAction("&Load Segmentation", self)
        self.load_segmentation_action.triggered.connect(self._on_load_segmentation)
        segmentation_menu.addAction(self.load_segmentation_action)

        self.unload_current_segmentation_action = QAction(
            "&Unload Current Segmentation", self
        )
        self.unload_current_segmentation_action.triggered.connect(
            self._on_unload_current_segmentation
        )
        segmentation_menu.addAction(self.unload_current_segmentation_action)

        segmentation_menu.addSeparator()

        self.open_segmentation_config_action = QAction(
            "Open &Configuration Panel", self
        )
        self.open_segmentation_config_action.triggered.connect(
            self._on_open_segmentation_configuration
        )
        segmentation_menu.addAction(self.open_segmentation_config_action)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._font_scaler.apply()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._accept_drop_for_viewer(event, self):
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if self._accept_drop_for_viewer(event, self):
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        if self._handle_drop_for_viewer(event, self):
            return
        super().dropEvent(event)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched in {self._content_widget, self._main_splitter} and self._handle_viewer_drop_event(
            watched, event
        ):
            return True
        return super().eventFilter(watched, event)

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

        self._load_base_image_from_path(Path(selected_file))

    def _on_unload(self) -> None:
        self.slice_viewer.unload_volume()
        self.contrast_state.clear()
        self.state.loaded_file_path = None
        self.state.volume = None
        self.state.cursor_position = None
        self.state.selected_patch_bounds = None
        self.state.selected_patch_data = None
        self._clear_segmentation_session()
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
        initialize_contrast_state(self.contrast_state, self.state.volume)

    def _on_auto_contrast(self) -> None:
        apply_auto_contrast(
            self.contrast_state,
            None if self.state.volume is None else self.state.volume.data,
        )

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
        active_segmentation = self._active_segmentation()
        patch_window = PatchViewerWindow(
            extracted,
            segmentation_volume=(
                extract_patch(active_segmentation.volume, bounds)
                if active_segmentation is not None
                else None
            ),
            segmentation_opacity=self.state.segmentation_opacity,
            parent=self,
            source_image_name=source_image_name,
            source_image_path=self.state.loaded_file_path,
            source_patch_bounds=bounds,
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
        self.state.selected_patch_bounds = bounds if isinstance(bounds, PatchBounds) else None
        self.cursor_panel.set_patch_size_xyz(self.slice_viewer.patch_size_xyz())

    def _on_patch_size_changed(self, width_lr: int, height_ap: int, depth_si: int) -> None:
        self.slice_viewer.set_patch_size_xyz((width_lr, height_ap, depth_si))

    def _on_find_patch_box(self) -> None:
        self.slice_viewer.recenter_views_on_patch_box()

    def _on_apply_tool_to_main_image_requested(self, tool_id: str) -> None:
        if self.state.volume is None:
            QMessageBox.warning(
                self,
                "No Image Loaded",
                "Load an image volume before applying a tool.",
            )
            return

        transformed_volume, status_message = apply_tool_to_volume(
            self,
            tool_id,
            self.state.volume,
        )
        if transformed_volume is None:
            self.statusBar().showMessage(status_message)
            return

        self.state.volume = transformed_volume
        cursor_position = self.state.cursor_position
        patch_enabled = self.slice_viewer.patch_selection_enabled()
        patch_center = self.slice_viewer.current_patch_center()
        patch_size = self.slice_viewer.patch_size_xyz()
        self.slice_viewer.replace_volume(
            transformed_volume,
            cursor_position=cursor_position,
            patch_center=patch_center,
            patch_size_xyz=patch_size,
            patch_selection_enabled=patch_enabled,
        )
        self.state.cursor_position = self.slice_viewer.current_cursor_position()
        self.state.selected_patch_bounds = self.slice_viewer.current_patch_bounds()
        if self.state.selected_patch_bounds is not None:
            self.state.selected_patch_data = extract_patch(
                transformed_volume,
                self.state.selected_patch_bounds,
            )
        else:
            self.state.selected_patch_data = None

        self._initialize_contrast_for_loaded_volume()
        self._sync_patch_windows_from_processed_main_image()
        self._apply_active_segmentation_overlay()

        tool_label = get_tool(tool_id).label
        self.statusBar().showMessage(f"Applied {tool_label} to main image")

    def _on_load_segmentation(self) -> None:
        if self.state.volume is None or self.state.loaded_file_path is None:
            QMessageBox.warning(
                self,
                "No Image Loaded",
                "Load a base image before loading segmentations.",
            )
            return
        if self.state.segmentation_image_path != self.state.loaded_file_path:
            self._reset_segmentation_session_for_loaded_image(self.state.loaded_file_path)

        file_filter = "NIfTI Files (*.nii *.nii.gz);;All Files (*)"
        selected_files, _ = QFileDialog.getOpenFileNames(
            self,
            "Load Segmentation File(s)",
            "",
            file_filter,
        )
        if not selected_files:
            self.statusBar().showMessage("Segmentation load canceled")
            return

        loaded_count = 0
        for selected_file in selected_files:
            if self._load_segmentation_from_path(Path(selected_file)):
                loaded_count += 1

        self._apply_active_segmentation_overlay()
        self._refresh_segmentation_ui()
        if loaded_count > 0:
            self.statusBar().showMessage(f"Loaded {loaded_count} segmentation file(s)")

    def _on_viewer_nifti_file_dropped(self, dropped_path: Path) -> None:
        choice = self._prompt_drop_load_choice()
        if choice is None:
            self.statusBar().showMessage("Dropped file load canceled")
            return
        if choice == DropLoadChoice.BASE_IMAGE:
            self._load_base_image_from_path(dropped_path)
            return
        self._load_segmentation_from_path(dropped_path)

    def _on_unload_current_segmentation(self) -> None:
        if self.state.active_segmentation_id is None:
            self.statusBar().showMessage("No active segmentation to unload")
            return

        self.state.loaded_segmentations = [
            segmentation
            for segmentation in self.state.loaded_segmentations
            if segmentation.id != self.state.active_segmentation_id
        ]
        self.state.active_segmentation_id = (
            self.state.loaded_segmentations[0].id
            if self.state.loaded_segmentations
            else None
        )
        self._apply_active_segmentation_overlay()
        self._refresh_segmentation_ui()
        self.statusBar().showMessage("Unloaded current segmentation")

    def _on_open_segmentation_configuration(self) -> None:
        self._refresh_segmentation_ui()
        self.segmentation_config_window.show()
        self.segmentation_config_window.raise_()
        self.segmentation_config_window.activateWindow()

    def _on_active_segmentation_changed(self, segmentation_id: str) -> None:
        if any(
            segmentation.id == segmentation_id
            for segmentation in self.state.loaded_segmentations
        ):
            self.state.active_segmentation_id = segmentation_id
            self._apply_active_segmentation_overlay()
            self._refresh_segmentation_ui()

    def _on_segmentation_opacity_changed(self, opacity: float) -> None:
        self.state.segmentation_opacity = min(max(opacity, 0.0), 1.0)
        self.slice_viewer.set_segmentation_overlay_opacity(self.state.segmentation_opacity)
        self._update_patch_windows_segmentation_opacity_for_current_image()

    def _active_segmentation(self) -> LoadedSegmentation | None:
        if self.state.active_segmentation_id is None:
            return None
        for segmentation in self.state.loaded_segmentations:
            if segmentation.id == self.state.active_segmentation_id:
                return segmentation
        return None

    def _apply_active_segmentation_overlay(self) -> None:
        active_segmentation = self._active_segmentation()
        if active_segmentation is None:
            self.slice_viewer.set_segmentation_overlay(
                None,
                opacity=self.state.segmentation_opacity,
            )
            self._update_patch_windows_segmentation_for_current_image(None)
            return
        self.slice_viewer.set_segmentation_overlay(
            active_segmentation.volume,
            opacity=self.state.segmentation_opacity,
        )
        self._update_patch_windows_segmentation_for_current_image(active_segmentation)

    def _refresh_segmentation_ui(self) -> None:
        has_image = self.state.volume is not None
        has_segmentations = len(self.state.loaded_segmentations) > 0

        if self.load_segmentation_action is not None:
            self.load_segmentation_action.setEnabled(has_image)
        if self.unload_current_segmentation_action is not None:
            self.unload_current_segmentation_action.setEnabled(has_segmentations)
        if self.open_segmentation_config_action is not None:
            self.open_segmentation_config_action.setEnabled(has_image)

        image_name = (
            self.state.loaded_file_path.name
            if self.state.loaded_file_path is not None
            else None
        )
        self.segmentation_config_window.set_current_image_name(image_name)
        self.segmentation_config_window.set_segmentations(
            [
                (segmentation.id, segmentation.display_name, str(segmentation.path))
                for segmentation in self.state.loaded_segmentations
            ],
            self.state.active_segmentation_id,
        )
        self.segmentation_config_window.set_opacity(self.state.segmentation_opacity)

    def _clear_segmentation_session(self) -> None:
        self.state.segmentation_image_path = None
        self.state.loaded_segmentations = []
        self.state.active_segmentation_id = None
        self._apply_active_segmentation_overlay()
        self._refresh_segmentation_ui()

    def _reset_segmentation_session_for_loaded_image(self, image_path: Path) -> int:
        cleared_count = len(self.state.loaded_segmentations)
        self._clear_segmentation_session()
        self.state.segmentation_image_path = image_path
        self._refresh_segmentation_ui()
        return cleared_count

    def _patch_windows_for_current_image(self) -> list[PatchViewerWindow]:
        return [
            patch_window
            for patch_window in self._patch_windows
            if patch_window.source_image_path() == self.state.loaded_file_path
        ]

    def _update_patch_windows_segmentation_for_current_image(
        self,
        active_segmentation: LoadedSegmentation | None,
    ) -> None:
        for patch_window in self._patch_windows_for_current_image():
            bounds = patch_window.source_patch_bounds()
            if active_segmentation is None or bounds is None:
                patch_window.update_segmentation_overlay(
                    None,
                    opacity=self.state.segmentation_opacity,
                )
                continue
            patch_window.update_segmentation_overlay(
                extract_patch(active_segmentation.volume, bounds),
                opacity=self.state.segmentation_opacity,
            )

    def _update_patch_windows_segmentation_opacity_for_current_image(self) -> None:
        for patch_window in self._patch_windows_for_current_image():
            patch_window.update_segmentation_opacity(self.state.segmentation_opacity)

    def _sync_patch_windows_from_processed_main_image(self) -> None:
        if self.state.volume is None:
            return
        for patch_window in self._patch_windows_for_current_image():
            bounds = patch_window.source_patch_bounds()
            if bounds is None:
                continue
            patch_window.sync_patch_from_parent(
                extract_patch(self.state.volume, bounds)
            )

    def _accept_drop_for_viewer(
        self,
        event: QDragEnterEvent | QDragMoveEvent,
        source_widget: QObject,
    ) -> bool:
        if self._dropped_nifti_path_for_viewer(event, source_widget) is None:
            event.ignore()
            return False
        event.acceptProposedAction()
        return True

    def _handle_viewer_drop_event(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.DragEnter:
            drag_enter_event = event if isinstance(event, QDragEnterEvent) else None
            return (
                drag_enter_event is not None
                and self._accept_drop_for_viewer(drag_enter_event, watched)
            )
        if event.type() == QEvent.Type.DragMove:
            drag_move_event = event if isinstance(event, QDragMoveEvent) else None
            return (
                drag_move_event is not None
                and self._accept_drop_for_viewer(drag_move_event, watched)
            )
        if event.type() == QEvent.Type.Drop:
            drop_event = event if isinstance(event, QDropEvent) else None
            return drop_event is not None and self._handle_drop_for_viewer(
                drop_event, watched
            )
        return False

    def _handle_drop_for_viewer(
        self,
        event: QDropEvent,
        source_widget: QObject,
    ) -> bool:
        dropped_path = self._dropped_nifti_path_for_viewer(event, source_widget)
        if dropped_path is None:
            event.ignore()
            return False
        event.acceptProposedAction()
        self._on_viewer_nifti_file_dropped(dropped_path)
        return True

    def _dropped_nifti_path_for_viewer(
        self,
        event: QDragEnterEvent | QDragMoveEvent | QDropEvent,
        source_widget: QObject,
    ) -> Path | None:
        if self._event_point_hits_slice_viewer(source_widget, event.position().toPoint()) is False:
            return None
        mime_data = event.mimeData()
        if mime_data is None or not mime_data.hasUrls():
            return None
        return first_supported_local_nifti_path(mime_data.urls())

    def _event_point_hits_slice_viewer(self, source_widget: QObject, point: QPoint) -> bool:
        if not isinstance(source_widget, QWidget):
            return False
        viewer_top_left = self.slice_viewer.mapFromGlobal(source_widget.mapToGlobal(point))
        return self.slice_viewer.rect().contains(viewer_top_left)

    def _prompt_drop_load_choice(self) -> DropLoadChoice | None:
        dialog = DropLoadChoiceDialog(
            allow_segmentation=self.state.volume is not None,
            parent=self,
        )
        if dialog.exec() != dialog.DialogCode.Accepted:
            return None
        return dialog.selected_choice()

    def _load_base_image_from_path(self, image_path: Path) -> bool:
        self._show_loading_progress()

        try:
            loaded = load_nifti(image_path)
        except (FileNotFoundError, ValueError) as exc:
            QMessageBox.critical(self, "Open Failed", str(exc))
            self.statusBar().showMessage("Open failed")
            self._schedule_loading_progress_hide()
            return False

        try:
            self.slice_viewer.load_volume(loaded)
        except ValueError as exc:
            QMessageBox.critical(self, "Open Failed", str(exc))
            self.statusBar().showMessage("Open failed")
            self._schedule_loading_progress_hide()
            return False

        self.state.loaded_file_path = image_path
        self.state.volume = loaded
        self.state.cursor_position = self.slice_viewer.current_cursor_position()
        self.state.selected_patch_bounds = None
        self.state.selected_patch_data = None
        cleared_count = self._reset_segmentation_session_for_loaded_image(image_path)
        self._initialize_contrast_for_loaded_volume()

        status_message = (
            f"Loaded {image_path.name} | shape={loaded.shape} | dtype={loaded.dtype}"
        )
        if cleared_count > 0:
            status_message = (
                f"{status_message} | cleared {cleared_count} segmentation(s) from previous image"
            )
        self.statusBar().showMessage(status_message)
        self._schedule_loading_progress_hide()
        return True

    def _load_segmentation_from_path(self, seg_path: Path) -> bool:
        if self.state.volume is None or self.state.loaded_file_path is None:
            QMessageBox.warning(
                self,
                "No Image Loaded",
                "Load a base image before loading segmentations.",
            )
            self.statusBar().showMessage("Segmentation load failed")
            return False

        if self.state.segmentation_image_path != self.state.loaded_file_path:
            self._reset_segmentation_session_for_loaded_image(self.state.loaded_file_path)

        try:
            segmentation = load_nifti(seg_path)
        except (FileNotFoundError, ValueError) as exc:
            QMessageBox.warning(
                self,
                "Segmentation Load Failed",
                f"{seg_path.name}: {exc}",
            )
            self.statusBar().showMessage("Segmentation load failed")
            return False

        validation = validate_segmentation_compatibility(self.state.volume, segmentation)
        if not validation.is_valid:
            QMessageBox.warning(
                self,
                "Segmentation Metadata Mismatch",
                f"{seg_path.name}: {validation.message}",
            )
            self.statusBar().showMessage("Segmentation load failed")
            return False

        loaded_segmentation = LoadedSegmentation(
            id=uuid4().hex,
            path=seg_path,
            volume=segmentation,
        )
        self.state.loaded_segmentations.append(loaded_segmentation)

        if self.state.active_segmentation_id is None:
            self.state.active_segmentation_id = loaded_segmentation.id

        self._apply_active_segmentation_overlay()
        self._refresh_segmentation_ui()
        self.statusBar().showMessage(f"Loaded segmentation {seg_path.name}")
        return True
