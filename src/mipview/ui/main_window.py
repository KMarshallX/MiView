from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QEvent, QObject, QPoint, QTimer, Qt
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QSizePolicy,
    QVBoxLayout,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QProgressDialog,
    QScrollArea,
    QSplitter,
    QWidget,
)

from mipview.annotation import (
    AnnotationMask,
    AnnotationState,
    annotation_metadata_path,
    create_empty_annotation_mask,
    load_annotation_mask,
    recon_annotation_metadata,
    save_annotation_metadata,
    save_annotation_mask,
)
from mipview.io.nifti_io import NiftiLoadResult, load_nifti
from mipview.graph.io import GraphLoadResult, read_graph_restore_metadata
from mipview.patch.extractor import extract_patch
from mipview.patch.selector import (
    PatchBounds,
    anatomical_direction_delta,
    patch_bounds_center,
    patch_bounds_shape,
    translate_patch_bounds,
)
from mipview.segmentation.models import LoadedSegmentation
from mipview.segmentation.validation import validate_segmentation_compatibility
from mipview.state.app_state import AppState
from mipview.state.contrast_state import ContrastState
from mipview.tools import get_tool
from mipview.ui.contrast_helpers import (
    apply_auto_contrast,
    connect_contrast_controls,
    initialize_contrast_state,
)
from mipview.ui.contrast_control_bar import ContrastControlBar
from mipview.ui.annotation_panel import AnnotationPanel
from mipview.ui.cursor_panel import CursorInspectionPanel
from mipview.ui.drop_load_choice_dialog import DropLoadChoice, DropLoadChoiceDialog
from mipview.ui.drop_loading import (
    first_supported_local_drop_path,
    is_supported_graph_state_path,
)
from mipview.ui.overlay_opacity_control_bar import OverlayOpacityControlBar
from mipview.ui.patch_window import PatchViewerWindow
from mipview.ui.segmentation_config_window import SegmentationConfigWindow
from mipview.ui.tool_actions import apply_tool_to_volume
from mipview.ui.tools_menu import build_tools_submenu
from mipview.ui.volume_3d_panel import Volume3DPanel
from mipview.ui.window_styling import (
    ResponsiveFontScaler,
    apply_window_content_frame,
)
from mipview.viewer.orientation_indicator import (
    ORIENTATION_INDICATOR_LABELS,
    ORIENTATION_INDICATOR_OFF,
    ORIENTATION_INDICATOR_WIDGET,
)
from mipview.viewer.triplanar_viewer_widget import (
    VIEW_MODE_3D,
    VIEW_MODE_AXIAL,
    VIEW_MODE_CORONAL,
    VIEW_MODE_ORTHOGONAL,
    VIEW_MODE_ORTHOGONAL_3D,
    VIEW_MODE_SAGITTAL,
    TriPlanarViewerWidget,
)
from mipview.viewer.render_3d_state import Render3DSource

ANNOTATION_LOAD_FILTER = (
    "Annotation Files (*.nii *.nii.gz *.json);;"
    "NIfTI Files (*.nii *.nii.gz);;"
    "JSON Metadata (*.json);;"
    "All Files (*)"
)
ANNOTATION_SEGMENTATION_ID = "annotation-active"
ANNOTATION_SEGMENTATION_NAME = "Annotating Layer"
RECON_ANNOTATION_SEGMENTATION_NAME = f"recon_{ANNOTATION_SEGMENTATION_NAME}"


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
        self.slice_viewer = TriPlanarViewerWidget(maximum_zoom=25.0)
        self.cursor_panel = CursorInspectionPanel(adaptable_width=True)
        self.annotation_panel = AnnotationPanel(adaptable_width=True)
        self.volume_3d_panel = Volume3DPanel(self)
        self.slice_viewer.volume_3d_view.connect_panel(self.volume_3d_panel)
        self.contrast_control_bar = ContrastControlBar(self)
        self.overlay_opacity_control_bar = OverlayOpacityControlBar(
            self,
            opacity=self.state.segmentation_opacity,
        )
        self.cursor_overlay_action: QAction | None = None
        self.view_mode_actions: dict[str, QAction] = {}
        self.view_mode_action_group: QActionGroup | None = None
        self.orientation_indicator_actions: dict[str, QAction] = {}
        self.orientation_indicator_action_group: QActionGroup | None = None
        self.patch_extension_lines_action: QAction | None = None
        self.ruler_action: QAction | None = None
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
        self.overlay_opacity_control_bar.opacity_changed.connect(
            self._on_segmentation_opacity_changed
        )
        self.overlay_opacity_control_bar.segmentation_changed.connect(
            self._on_overlay_segmentation_changed
        )
        self.segmentation_config_window.unload_segmentation_requested.connect(
            self._on_unload_segmentation_requested
        )
        self.slice_viewer.cursor_inspection_changed.connect(
            self.cursor_panel.set_cursor_values
        )
        self.slice_viewer.annotation_changed.connect(self._on_annotation_changed)
        self.slice_viewer.annotation_undo_availability_changed.connect(
            self.annotation_panel.set_undo_available
        )
        self.slice_viewer.nifti_file_dropped.connect(self._on_viewer_nifti_file_dropped)
        self.slice_viewer.graph_state_file_dropped.connect(
            self._on_viewer_graph_state_file_dropped
        )
        self.slice_viewer.cursor_state.cursor_changed.connect(self._update_cursor_position)
        self.slice_viewer.patch_selection_changed.connect(self._on_patch_selection_changed)
        self.cursor_panel.patch_activation_toggled.connect(
            self._on_patch_activation_button_toggled
        )
        self.cursor_panel.patch_opacity_changed.connect(self.slice_viewer.set_patch_overlay_opacity)
        self.cursor_panel.patch_size_changed.connect(self._on_patch_size_changed)
        self.cursor_panel.select_patch_requested.connect(self._on_select_patch)
        self.cursor_panel.find_patch_box_requested.connect(self._on_find_patch_box)
        self.annotation_panel.create_requested.connect(self._on_create_annotation)
        self.annotation_panel.load_requested.connect(self._on_load_annotation)
        self.annotation_panel.save_requested.connect(self._on_save_annotation)
        self.annotation_panel.visibility_changed.connect(
            self._on_annotation_visibility_changed
        )
        self.annotation_panel.opacity_changed.connect(self._on_annotation_opacity_changed)
        self.annotation_panel.active_label_changed.connect(
            self._on_annotation_active_label_changed
        )
        self.annotation_panel.brush_radius_changed.connect(
            self._on_annotation_brush_radius_changed
        )
        self.annotation_panel.brush_mode_changed.connect(
            self._on_annotation_brush_mode_changed
        )
        self.annotation_panel.undo_requested.connect(self._on_annotation_undo_requested)
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
        self._refresh_annotation_ui()
        self.segmentation_config_window.set_opacity(self.state.segmentation_opacity)
        self._refresh_segmentation_ui()
        self._refresh_patch_selection_ui()
        self._font_scaler.apply()
        self.statusBar().showMessage("Ready")

    def _setup_central_layout(self) -> None:
        content_widget = QWidget(self)
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.addWidget(self.slice_viewer)
        right_panel = QWidget(self)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        right_layout.addWidget(self.cursor_panel)
        right_layout.addWidget(self.annotation_panel)
        volume_3d_panel_container = QWidget(right_panel)
        volume_3d_panel_layout = QVBoxLayout(volume_3d_panel_container)
        volume_3d_panel_layout.setContentsMargins(8, 0, 8, 8)
        volume_3d_panel_layout.setSpacing(0)
        volume_3d_panel_layout.addWidget(self.volume_3d_panel)
        right_layout.addWidget(volume_3d_panel_container)
        right_layout.addStretch(1)

        right_scroll_area = QScrollArea(self)
        right_scroll_area.setWidgetResizable(True)
        right_scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        right_scroll_area.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        right_scroll_area.setWidget(right_panel)
        splitter.addWidget(right_scroll_area)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)
        content_widget.setAcceptDrops(True)
        splitter.setAcceptDrops(True)
        content_widget.installEventFilter(self)
        splitter.installEventFilter(self)
        self._content_widget = content_widget
        self._main_splitter = splitter
        splitter.setSizes(
            [CursorInspectionPanel.PANEL_WIDTH * 4, CursorInspectionPanel.PANEL_WIDTH]
        )

        content_layout.addWidget(self.contrast_control_bar)
        content_layout.addWidget(self.overlay_opacity_control_bar)
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

        self._add_view_mode_actions(view_menu)
        view_menu.addSeparator()

        self.cursor_overlay_action = QAction("Show &Cursor Overlay", self)
        self.cursor_overlay_action.setCheckable(True)
        self.cursor_overlay_action.setChecked(True)
        self.cursor_overlay_action.toggled.connect(
            self.slice_viewer.set_cursor_overlay_visible
        )
        view_menu.addAction(self.cursor_overlay_action)
        view_menu.addSeparator()
        self._add_orientation_indicator_actions(view_menu)
        view_menu.addSeparator()
        self.patch_extension_lines_action = QAction(
            "Turn on/off patch indicator extension lines",
            self,
        )
        self.patch_extension_lines_action.setCheckable(True)
        self.patch_extension_lines_action.setChecked(True)
        self.patch_extension_lines_action.toggled.connect(
            self.slice_viewer.volume_3d_view.set_patch_extension_lines_visible
        )
        view_menu.addAction(self.patch_extension_lines_action)

        self.patch_toggle_action = QAction("&Patch Selection", self)
        self.patch_toggle_action.setCheckable(True)
        self.patch_toggle_action.setChecked(True)
        self.patch_toggle_action.toggled.connect(self._on_patch_selection_toggled)
        tools_menu.addAction(self.patch_toggle_action)

        self.ruler_action = QAction("Show &Ruler", self)
        self.ruler_action.setCheckable(True)
        self.ruler_action.setChecked(True)
        self.ruler_action.toggled.connect(self.slice_viewer.set_ruler_visible)
        tools_menu.addAction(self.ruler_action)

        tools_menu.addSeparator()
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

    def _add_view_mode_actions(self, view_menu: object) -> None:
        action_group = QActionGroup(self)
        action_group.setExclusive(True)
        self.view_mode_action_group = action_group
        labels = (
            ("Axial View", VIEW_MODE_AXIAL),
            ("Sagittal View", VIEW_MODE_SAGITTAL),
            ("Coronal View", VIEW_MODE_CORONAL),
            ("3D Render", VIEW_MODE_3D),
            ("Orthogonal", VIEW_MODE_ORTHOGONAL),
            ("Orthogonal and 3D", VIEW_MODE_ORTHOGONAL_3D),
        )
        for label, mode in labels:
            action = QAction(label, self)
            action.setCheckable(True)
            action.setChecked(mode == self.slice_viewer.view_mode())
            action.triggered.connect(
                lambda _checked=False, selected_mode=mode: (
                    self.slice_viewer.set_view_mode(selected_mode)
                )
            )
            action_group.addAction(action)
            view_menu.addAction(action)
            self.view_mode_actions[mode] = action
        self.slice_viewer.view_mode_changed.connect(
            self._on_view_mode_changed
        )

    def _on_view_mode_changed(self, mode: str) -> None:
        action = self.view_mode_actions.get(mode)
        if action is not None:
            action.setChecked(True)

    def _add_orientation_indicator_actions(self, view_menu: object) -> None:
        action_group = QActionGroup(self)
        action_group.setExclusive(True)
        self.orientation_indicator_action_group = action_group
        for label, mode in (
            ("Display orientation labels", ORIENTATION_INDICATOR_LABELS),
            ("Display orientation widget", ORIENTATION_INDICATOR_WIDGET),
            ("Turn off Orientation Indicator", ORIENTATION_INDICATOR_OFF),
        ):
            action = QAction(label, self)
            action.setCheckable(True)
            action.setChecked(
                mode == self.slice_viewer.orientation_indicator_mode()
            )
            action.triggered.connect(
                lambda _checked=False, selected_mode=mode: (
                    self.slice_viewer.set_orientation_indicator_mode(
                        selected_mode
                    )
                )
            )
            action_group.addAction(action)
            view_menu.addAction(action)
            self.orientation_indicator_actions[mode] = action

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
        self._clear_annotation_session()
        self._clear_segmentation_session()
        self._set_patch_selection_active(False)
        if self.cursor_overlay_action is not None:
            self.cursor_overlay_action.setEnabled(True)
            self.slice_viewer.set_cursor_overlay_visible(self.cursor_overlay_action.isChecked())
        self.cursor_panel.set_cursor_values(None, None, None, None)
        self.cursor_panel.set_axis_directions(None)
        self._refresh_patch_selection_ui()
        self._sync_volume_3d_sources()
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
        self.cursor_panel.set_patch_controls_visible(enabled)
        if enabled:
            self._refresh_patch_selection_ui()

    def _on_patch_activation_button_toggled(self, enabled: bool) -> None:
        self._set_patch_selection_active(enabled)

    def _set_patch_selection_active(self, enabled: bool) -> None:
        has_image = self.state.volume is not None
        effective_enabled = enabled and has_image
        was_enabled = self.slice_viewer.patch_selection_enabled()
        self.slice_viewer.set_patch_selection_enabled(effective_enabled)
        if self.cursor_overlay_action is not None:
            if effective_enabled and not was_enabled:
                self._cursor_overlay_checked_before_patch = self.cursor_overlay_action.isChecked()
                self.cursor_overlay_action.setChecked(False)
                self.cursor_overlay_action.setEnabled(False)
                self.slice_viewer.set_cursor_overlay_visible(False)
            elif not effective_enabled and was_enabled:
                self.cursor_overlay_action.setEnabled(True)
                self.cursor_overlay_action.setChecked(self._cursor_overlay_checked_before_patch)
        self._refresh_patch_selection_ui()

    def _refresh_patch_selection_ui(self) -> None:
        panel_visible = (
            self.patch_toggle_action.isChecked()
            if self.patch_toggle_action is not None
            else True
        )
        has_image = self.state.volume is not None
        patch_active = has_image and self.slice_viewer.patch_selection_enabled()

        self.cursor_panel.set_patch_controls_visible(panel_visible)
        self.cursor_panel.set_patch_selection_active(patch_active)
        self.cursor_panel.set_patch_activation_available(has_image)
        self.cursor_panel.set_patch_controls_enabled(has_image and patch_active)

        if has_image:
            self.cursor_panel.set_patch_opacity(self.slice_viewer.patch_overlay_opacity())
            self.cursor_panel.set_patch_size_xyz(self.slice_viewer.patch_size_xyz())

    def _on_select_patch(self) -> None:
        if self.state.volume is None:
            return

        bounds = self.slice_viewer.current_patch_bounds()
        center = self.slice_viewer.current_patch_center()
        if bounds is None:
            return

        patch_window = self._build_patch_window(
            bounds,
            center=center,
            patch_size=self.slice_viewer.patch_size_xyz(),
        )
        self.state.selected_patch_bounds = bounds
        self.state.selected_patch_data = patch_window.patch_volume()
        self._register_patch_window(patch_window)

    def _build_patch_window(
        self,
        bounds: PatchBounds,
        *,
        center: tuple[int, int, int] | None,
        patch_size: tuple[int, int, int],
    ) -> PatchViewerWindow:
        if self.state.volume is None:
            raise ValueError("Load a source image before opening a patch window.")
        extracted = extract_patch(self.state.volume, bounds)
        active_segmentation = self._active_segmentation()
        active_annotation_patch = self._extract_active_annotation_patch(bounds)
        patch_window = PatchViewerWindow(
            extracted,
            segmentation_volume=(
                extract_patch(active_segmentation.volume, bounds)
                if active_segmentation is not None and active_segmentation.kind == "file"
                else None
            ),
            active_segmentation_kind=(
                None if active_segmentation is None else active_segmentation.kind
            ),
            projection_mask_layers=self._projection_mask_layers_for_bounds(bounds),
            segmentation_opacity=self.state.segmentation_opacity,
            annotation_mask=active_annotation_patch,
            annotation_opacity=self.state.annotation.opacity,
            annotation_visible=self.state.annotation.visible,
            annotation_active_label=self.state.annotation.active_label,
            annotation_editing_enabled=self.state.annotation.editing_enabled
            and active_annotation_patch is not None,
            annotation_brush_radius=self.state.annotation.brush_radius,
            annotation_brush_mode=self.state.annotation.brush_mode,
            parent=self,
            source_image_name=(
                self.state.loaded_file_path.name
                if self.state.loaded_file_path is not None
                else "image.nii.gz"
            ),
            source_image_path=self.state.loaded_file_path,
            source_patch_bounds=bounds,
            source_image_shape=tuple(
                int(value) for value in self.state.volume.shape[:3]
            ),
            source_volume=self.state.volume,
            patch_center=center,
            patch_size=patch_size,
        )
        patch_window.annotation_create_requested.connect(
            self._on_patch_window_annotation_create_requested
        )
        patch_window.annotation_patch_changed.connect(
            self._on_patch_window_annotation_patch_changed
        )
        patch_window.annotation_undo_requested_from_patch.connect(
            self._on_patch_window_annotation_patch_changed
        )
        patch_window.annotation_visibility_changed.connect(
            self._on_annotation_visibility_changed
        )
        patch_window.annotation_opacity_changed.connect(
            self._on_annotation_opacity_changed
        )
        patch_window.overlay_opacity_changed.connect(
            self._on_segmentation_opacity_changed
        )
        patch_window.overlay_segmentation_changed.connect(
            self._on_overlay_segmentation_changed
        )
        patch_window.annotation_active_label_changed.connect(
            self._on_annotation_active_label_changed
        )
        patch_window.annotation_brush_radius_changed.connect(
            self._on_annotation_brush_radius_changed
        )
        patch_window.annotation_brush_mode_changed.connect(
            self._on_annotation_brush_mode_changed
        )
        patch_window.unload_current_segmentation_requested.connect(
            self._on_unload_current_segmentation
        )
        patch_window.open_segmentation_configuration_requested.connect(
            self._on_open_segmentation_configuration
        )
        patch_window.patch_translation_requested.connect(
            self._on_patch_translation_requested
        )
        self._sync_patch_window_segmentation_menu_state(patch_window)
        return patch_window

    def _register_patch_window(self, patch_window: PatchViewerWindow) -> None:
        patch_window.show()
        self._patch_windows.append(patch_window)
        patch_window.destroyed.connect(
            lambda _: self._patch_windows.remove(patch_window)
            if patch_window in self._patch_windows
            else None
        )

    def translate_patch_window(
        self,
        patch_window: PatchViewerWindow,
        direction: str,
        voxels: int = 1,
        *,
        discard_local_work: bool = False,
    ) -> dict[str, object]:
        if self.state.volume is None:
            raise ValueError("The source image is no longer loaded.")
        if patch_window not in self._patch_windows:
            raise ValueError("The requested patch window is not open.")
        if patch_window.source_image_path() != self.state.loaded_file_path:
            raise ValueError(
                "The patch window's source image is not the currently loaded image."
            )
        bounds = patch_window.source_patch_bounds()
        if bounds is None:
            raise ValueError("The patch window has no source-image bounds.")
        if patch_window.has_discardable_local_work() and not discard_local_work:
            raise ValueError(
                "Patch movement would reset local processing history or graph "
                "annotations. Save the local work and set discard_local_work=true."
            )

        normalized_direction = str(direction).strip().upper()
        requested_voxels = int(voxels)
        requested_delta = anatomical_direction_delta(
            normalized_direction,
            requested_voxels,
        )
        source_shape = tuple(int(value) for value in self.state.volume.shape[:3])
        translated_bounds, actual_delta = translate_patch_bounds(
            bounds,
            requested_delta,
            source_shape,
        )
        actual_voxels = max(abs(value) for value in actual_delta)
        moving_axis = next(
            axis for axis, component in enumerate(requested_delta) if component != 0
        )
        translated_starts = (
            translated_bounds.x_start,
            translated_bounds.y_start,
            translated_bounds.z_start,
        )
        translated_ends = (
            translated_bounds.x_end,
            translated_bounds.y_end,
            translated_bounds.z_end,
        )
        boundary_reached = (
            actual_voxels < requested_voxels
            or (
                requested_delta[moving_axis] < 0
                and translated_starts[moving_axis] == 0
            )
            or (
                requested_delta[moving_axis] > 0
                and translated_ends[moving_axis] == source_shape[moving_axis]
            )
        )
        if actual_voxels == 0:
            patch_window.patch_position_panel.set_source_geometry(bounds, source_shape)
            patch_window.patch_position_panel.stop_movement()
            return self._patch_translation_result(
                patch_window,
                normalized_direction,
                requested_voxels,
                actual_voxels,
                actual_delta,
                boundary_reached=True,
                history_reset=False,
                graph_reset=False,
            )

        patch_volume = extract_patch(self.state.volume, translated_bounds)
        active_segmentation = self._active_segmentation()
        segmentation_volume = (
            extract_patch(active_segmentation.volume, translated_bounds)
            if active_segmentation is not None and active_segmentation.kind == "file"
            else None
        )
        annotation_mask = self._extract_active_annotation_patch(translated_bounds)
        projection_mask_layers = self._projection_mask_layers_for_bounds(
            translated_bounds
        )
        reset_state = patch_window.apply_translated_source_patch(
            patch_volume,
            bounds=translated_bounds,
            source_shape=source_shape,
            direction=normalized_direction,
            actual_voxels=actual_voxels,
            segmentation_volume=segmentation_volume,
            annotation_mask=annotation_mask,
            projection_mask_layers=projection_mask_layers,
            active_segmentation_kind=(
                None if active_segmentation is None else active_segmentation.kind
            ),
            annotation_editing_enabled=(
                self.state.annotation.editing_enabled and annotation_mask is not None
            ),
            discard_local_work=discard_local_work,
        )
        return self._patch_translation_result(
            patch_window,
            normalized_direction,
            requested_voxels,
            actual_voxels,
            actual_delta,
            boundary_reached=boundary_reached,
            history_reset=reset_state["history_reset"],
            graph_reset=reset_state["graph_reset"],
        )

    def _on_patch_translation_requested(
        self,
        patch_window: PatchViewerWindow,
        direction: str,
        voxels: int,
        discard_local_work: bool,
    ) -> None:
        try:
            self.translate_patch_window(
                patch_window,
                direction,
                voxels,
                discard_local_work=discard_local_work,
            )
        except (TypeError, ValueError) as exc:
            patch_window.translation_failed(str(exc))

    @staticmethod
    def _patch_translation_result(
        patch_window: PatchViewerWindow,
        direction: str,
        requested_voxels: int,
        actual_voxels: int,
        actual_delta: tuple[int, int, int],
        *,
        boundary_reached: bool,
        history_reset: bool,
        graph_reset: bool,
    ) -> dict[str, object]:
        bounds = patch_window.source_patch_bounds()
        return {
            "session_id": patch_window.graph_session_id,
            "direction": direction,
            "requested_voxels": requested_voxels,
            "actual_voxels": actual_voxels,
            "actual_delta": list(actual_delta),
            "bounds": (
                None
                if bounds is None
                else {
                    "x": [bounds.x_start, bounds.x_end],
                    "y": [bounds.y_start, bounds.y_end],
                    "z": [bounds.z_start, bounds.z_end],
                }
            ),
            "center": None if bounds is None else list(patch_bounds_center(bounds)),
            "shape": None if bounds is None else list(patch_bounds_shape(bounds)),
            "boundary_reached": boundary_reached,
            "history_reset": history_reset,
            "graph_reset": graph_reset,
        }

    def _on_patch_selection_changed(self, bounds: object) -> None:
        self.state.selected_patch_bounds = bounds if isinstance(bounds, PatchBounds) else None
        self.cursor_panel.set_patch_size_xyz(self.slice_viewer.patch_size_xyz())
        volume = self.state.volume
        self.slice_viewer.volume_3d_view.set_patch_box(
            self.state.selected_patch_bounds,
            None if volume is None else volume.affine,
            visible=self.state.selected_patch_bounds is not None,
        )

    def _on_patch_size_changed(self, width_lr: int, height_ap: int, depth_si: int) -> None:
        self.slice_viewer.set_patch_size_xyz((width_lr, height_ap, depth_si))

    def _on_find_patch_box(self) -> None:
        self.slice_viewer.recenter_views_on_patch_box()

    def _on_create_annotation(self) -> None:
        if self.state.annotation.editing_enabled:
            self._exit_annotation_mode()
            return

        if self.state.volume is None:
            QMessageBox.warning(
                self,
                "No Image Loaded",
                "Load a base image before creating an annotation.",
            )
            return

        created_new_mask = self.state.annotation.active_mask is None
        if created_new_mask:
            annotation_mask = create_empty_annotation_mask(self.state.volume)
            self.state.annotation.active_mask = annotation_mask
            self.state.annotation.undo_stack.clear()
        else:
            annotation_mask = self.state.annotation.active_mask
        self.state.annotation.editing_enabled = True
        if created_new_mask:
            self.slice_viewer.set_annotation_overlay(
                annotation_mask,
                opacity=self.state.annotation.opacity,
                visible=self.state.annotation.visible,
                active_label=self.state.annotation.active_label,
                undo_stack=self.state.annotation.undo_stack,
            )
        self._register_annotation_as_segmentation(
            preserve_existing_display_name=not created_new_mask
        )
        self._sync_annotation_brush_settings()
        self._refresh_annotation_ui()
        if created_new_mask:
            self.statusBar().showMessage("Created empty annotation mask")
        else:
            self.statusBar().showMessage("Entered annotation mode")
        self._update_patch_windows_annotation_for_current_image()

    def _on_load_annotation(self) -> None:
        if self.state.volume is None:
            QMessageBox.warning(
                self,
                "No Image Loaded",
                "Load a base image before loading an annotation.",
            )
            return

        selected_file, _ = QFileDialog.getOpenFileName(
            self,
            "Load Annotation",
            "",
            ANNOTATION_LOAD_FILTER,
        )
        if not selected_file:
            self.statusBar().showMessage("Annotation load canceled")
            return

        selected_path = Path(selected_file)
        progress = self._show_annotation_load_progress(
            "Reconstructing annotation metadata..."
            if self._is_annotation_metadata_path(selected_path)
            else "Loading annotation..."
        )
        reconstructed_path: Path | None = None
        try:
            if self._is_annotation_metadata_path(selected_path):
                reconstructed_path = self._temporary_reconstructed_annotation_path(
                    selected_path
                )
                recon_annotation_metadata(
                    selected_path,
                    reconstructed_path,
                    source_image_path=self.state.loaded_file_path,
                )
                annotation_mask = load_annotation_mask(
                    reconstructed_path,
                    self.state.volume,
                )
            else:
                annotation_mask = load_annotation_mask(selected_path, self.state.volume)
        except (FileNotFoundError, ValueError, OSError) as exc:
            QMessageBox.warning(
                self,
                "Annotation Load Failed",
                str(exc),
            )
            self.statusBar().showMessage("Annotation load failed")
            return
        finally:
            progress.close()
            if reconstructed_path is not None:
                reconstructed_path.unlink(missing_ok=True)

        self._set_loaded_annotation_mask(
            annotation_mask,
            reconstructed_from_metadata=self._is_annotation_metadata_path(selected_path),
        )
        self.statusBar().showMessage(f"Loaded annotation {selected_path.name}")

    @staticmethod
    def _is_annotation_metadata_path(path: str | Path) -> bool:
        return Path(path).suffix.lower() == ".json"

    @staticmethod
    def _temporary_reconstructed_annotation_path(metadata_path: Path) -> Path:
        return metadata_path.with_name(
            f".{metadata_path.stem}.mipview-reconstructed-{uuid4().hex}.nii.gz"
        )

    def _show_annotation_load_progress(self, message: str) -> QProgressDialog:
        progress = QProgressDialog(message, None, 0, 0, self)
        progress.setWindowTitle("Loading Annotation")
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.setMinimumDuration(0)
        progress.setCancelButton(None)
        progress.show()
        QApplication.processEvents()
        return progress

    def _set_loaded_annotation_mask(
        self,
        annotation_mask: AnnotationMask,
        *,
        reconstructed_from_metadata: bool = False,
    ) -> None:
        self.state.annotation.active_mask = annotation_mask
        self.state.annotation.undo_stack.clear()
        self.state.annotation.editing_enabled = True
        self.slice_viewer.set_annotation_overlay(
            annotation_mask,
            opacity=self.state.annotation.opacity,
            visible=self.state.annotation.visible,
            active_label=self.state.annotation.active_label,
            undo_stack=self.state.annotation.undo_stack,
        )
        self._register_annotation_as_segmentation(
            reconstructed_from_metadata=reconstructed_from_metadata
        )
        self._sync_annotation_brush_settings()
        self._refresh_annotation_ui()
        self._update_patch_windows_annotation_for_current_image()

    def _on_save_annotation(self) -> None:
        annotation_mask = self.state.annotation.active_mask
        if annotation_mask is None:
            QMessageBox.warning(
                self,
                "No Annotation",
                "Create or load an annotation before saving.",
            )
            return

        export_type = self.annotation_panel.current_export_type()
        if export_type == AnnotationPanel.EXPORT_JSON:
            selected_path, _ = QFileDialog.getSaveFileName(
                self,
                "Save Annotation Metadata",
                str(self._default_annotation_metadata_save_path()),
                "JSON Files (*.json);;All Files (*)",
            )
            if not selected_path:
                self.statusBar().showMessage("Annotation save canceled")
                return

            metadata_path = Path(selected_path)
            if not self._confirm_overwrite_annotation_outputs([metadata_path]):
                return

            try:
                saved_metadata_path = save_annotation_metadata(
                    annotation_mask,
                    "",
                    metadata_path,
                    source_image_path=self.state.loaded_file_path,
                    overwrite=True,
                )
            except (FileExistsError, ValueError, OSError) as exc:
                QMessageBox.critical(self, "Annotation Save Failed", str(exc))
                self.statusBar().showMessage("Annotation save failed")
                return
            self.statusBar().showMessage(
                f"Saved annotation metadata {saved_metadata_path}"
            )
            return

        selected_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Annotation Mask",
            str(self._default_annotation_save_path()),
            "NIfTI Files (*.nii.gz *.nii);;All Files (*)",
        )
        if not selected_path:
            self.statusBar().showMessage("Annotation save canceled")
            return

        mask_path = Path(selected_path)
        metadata_path = annotation_metadata_path(mask_path)
        output_paths = (
            [mask_path, metadata_path]
            if export_type == AnnotationPanel.EXPORT_BOTH
            else [mask_path]
        )
        if not self._confirm_overwrite_annotation_outputs(output_paths):
            return

        try:
            saved_path = save_annotation_mask(
                annotation_mask,
                mask_path,
                overwrite=True,
            )
            if export_type == AnnotationPanel.EXPORT_BOTH:
                saved_metadata_path = save_annotation_metadata(
                    annotation_mask,
                    saved_path,
                    metadata_path,
                    source_image_path=self.state.loaded_file_path,
                    overwrite=True,
                )
            else:
                saved_metadata_path = None
        except (FileExistsError, ValueError, OSError) as exc:
            QMessageBox.critical(self, "Annotation Save Failed", str(exc))
            self.statusBar().showMessage("Annotation save failed")
            return

        if saved_metadata_path is None:
            self.statusBar().showMessage(f"Saved annotation {saved_path}")
        else:
            self.statusBar().showMessage(
                f"Saved annotation {saved_path} and metadata {saved_metadata_path}"
            )

    def _confirm_overwrite_annotation_outputs(self, output_paths: list[Path]) -> bool:
        existing_outputs = [path for path in output_paths if path.exists()]
        if existing_outputs:
            existing_names = "\n".join(str(path) for path in existing_outputs)
            choice = QMessageBox.question(
                self,
                "Overwrite Annotation Output?",
                (
                    "The following annotation output file(s) already exist:\n\n"
                    f"{existing_names}\n\nOverwrite them?"
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if choice != QMessageBox.StandardButton.Yes:
                self.statusBar().showMessage("Annotation save canceled")
                return False
        return True

    def _on_annotation_visibility_changed(self, visible: bool) -> None:
        self.state.annotation.visible = bool(visible)
        self.annotation_panel.set_visible_checked(self.state.annotation.visible)
        self.slice_viewer.set_annotation_overlay_visible(
            self.state.annotation.visible and self._active_segmentation_is_annotation()
        )
        self._update_patch_windows_annotation_display_options()

    def _on_annotation_opacity_changed(self, opacity: float) -> None:
        self.state.annotation.opacity = min(max(float(opacity), 0.0), 1.0)
        self.annotation_panel.set_opacity(self.state.annotation.opacity)
        self.slice_viewer.set_annotation_overlay_opacity(self.state.annotation.opacity)
        self._update_patch_windows_annotation_display_options()
        if self._active_segmentation_is_annotation():
            self._refresh_segmentation_ui()

    def _on_annotation_active_label_changed(self, label: int) -> None:
        self.state.annotation.active_label = max(int(label), 1)
        self.annotation_panel.set_active_label(self.state.annotation.active_label)
        self.slice_viewer.set_annotation_active_label(self.state.annotation.active_label)
        self._update_patch_windows_annotation_display_options()

    def _on_annotation_brush_radius_changed(self, radius: int) -> None:
        self.state.annotation.brush_radius = max(int(radius), 0)
        self.annotation_panel.set_brush_radius(self.state.annotation.brush_radius)
        self.slice_viewer.set_annotation_brush_radius(self.state.annotation.brush_radius)
        self._update_patch_windows_annotation_display_options()

    def _on_annotation_brush_mode_changed(self, mode: str) -> None:
        if mode not in {"paint", "cursor", "erase"}:
            return
        self.state.annotation.brush_mode = mode
        self.annotation_panel.set_brush_mode(mode)
        self.slice_viewer.set_annotation_brush_mode(mode)
        self._update_patch_windows_annotation_display_options()

    def _on_annotation_changed(self, changed_voxels: object) -> None:
        self.statusBar().showMessage(
            f"Annotation updated: {int(changed_voxels)} voxel(s) changed"
        )
        self.annotation_panel.set_undo_available(self.slice_viewer.annotation_can_undo())
        self._register_annotation_as_segmentation(
            preserve_existing_display_name=True,
            make_active=self._active_segmentation_is_annotation(),
        )
        self._update_patch_windows_annotation_for_current_image()

    def _on_annotation_undo_requested(self) -> None:
        changed = self.slice_viewer.undo_annotation()
        self.annotation_panel.set_undo_available(self.slice_viewer.annotation_can_undo())
        if changed <= 0:
            self.statusBar().showMessage("No annotation edit to undo")
            return
        self.statusBar().showMessage(
            f"Undid annotation edit: {changed} voxel(s) restored"
        )
        self._update_patch_windows_annotation_for_current_image()

    def _refresh_annotation_ui(self) -> None:
        annotation_state = self.state.annotation
        has_image = self.state.volume is not None
        has_mask = annotation_state.active_mask is not None
        editing_enabled = has_mask and annotation_state.editing_enabled
        self.annotation_panel.set_image_loaded(has_image)
        self.annotation_panel.set_annotation_active(
            has_mask,
            editing_enabled=editing_enabled,
        )
        self.annotation_panel.set_visible_checked(annotation_state.visible)
        self.annotation_panel.set_opacity(annotation_state.opacity)
        self.annotation_panel.set_active_label(annotation_state.active_label)
        self.annotation_panel.set_brush_radius(annotation_state.brush_radius)
        self.annotation_panel.set_brush_mode(annotation_state.brush_mode)
        self.annotation_panel.set_undo_available(self.slice_viewer.annotation_can_undo())
        self._sync_annotation_brush_settings()

    def _clear_annotation_session(self) -> None:
        self.state.annotation = AnnotationState()
        self.slice_viewer.set_annotation_overlay(
            None,
            undo_stack=self.state.annotation.undo_stack,
        )
        self._remove_annotation_segmentation_entry()
        self._refresh_annotation_ui()
        self._update_patch_windows_annotation_for_current_image()

    def _exit_annotation_mode(self) -> None:
        self.state.annotation.editing_enabled = False
        self.slice_viewer.set_annotation_editing_enabled(False)
        self._refresh_annotation_ui()
        self.statusBar().showMessage("Exited annotation mode")

    def _sync_annotation_brush_settings(self) -> None:
        self.slice_viewer.set_annotation_editing_enabled(
            self.state.annotation.editing_enabled
            and self.state.annotation.active_mask is not None
        )
        self.slice_viewer.set_annotation_brush_radius(self.state.annotation.brush_radius)
        self.slice_viewer.set_annotation_brush_mode(self.state.annotation.brush_mode)

    def _default_annotation_save_path(self) -> Path:
        if self.state.loaded_file_path is None:
            return Path.home() / "annotation_mask.nii.gz"
        source_name = self.state.loaded_file_path.name
        if source_name.lower().endswith(".nii.gz"):
            source_stem = source_name[:-7]
        elif source_name.lower().endswith(".nii"):
            source_stem = source_name[:-4]
        else:
            source_stem = self.state.loaded_file_path.stem
        return self.state.loaded_file_path.with_name(f"{source_stem}_annotation.nii.gz")

    def _default_annotation_metadata_save_path(self) -> Path:
        return annotation_metadata_path(self._default_annotation_save_path())

    def _active_annotation_volume(self) -> NiftiLoadResult | None:
        annotation_mask = self.state.annotation.active_mask
        if annotation_mask is None:
            return None
        return NiftiLoadResult(
            data=annotation_mask.data,
            affine=annotation_mask.affine,
            header=annotation_mask.header,
            shape=annotation_mask.shape,
            dtype=annotation_mask.dtype,
        )

    def _register_annotation_as_segmentation(
        self,
        *,
        reconstructed_from_metadata: bool = False,
        make_active: bool = True,
        preserve_existing_display_name: bool = False,
    ) -> None:
        annotation_volume = self._active_annotation_volume()
        if (
            annotation_volume is None
            or self.state.loaded_file_path is None
            or self.state.volume is None
        ):
            return

        if self.state.segmentation_image_path != self.state.loaded_file_path:
            self._reset_segmentation_session_for_loaded_image(self.state.loaded_file_path)

        existing_annotation = next(
            (
                segmentation
                for segmentation in self.state.loaded_segmentations
                if segmentation.kind == "annotation"
            ),
            None,
        )
        display_name = (
            RECON_ANNOTATION_SEGMENTATION_NAME
            if reconstructed_from_metadata
            else ANNOTATION_SEGMENTATION_NAME
        )
        if (
            preserve_existing_display_name
            and existing_annotation is not None
            and existing_annotation.display_name_override is not None
        ):
            display_name = existing_annotation.display_name_override
        annotation_segmentation = LoadedSegmentation(
            id=ANNOTATION_SEGMENTATION_ID,
            path=None,
            volume=annotation_volume,
            kind="annotation",
            display_name_override=display_name,
        )
        self.state.loaded_segmentations = [
            segmentation
            for segmentation in self.state.loaded_segmentations
            if segmentation.kind != "annotation"
        ]
        self.state.loaded_segmentations.append(annotation_segmentation)
        if make_active or self.state.active_segmentation_id is None:
            self.state.active_segmentation_id = ANNOTATION_SEGMENTATION_ID
        self._apply_active_segmentation_overlay()
        self._refresh_segmentation_ui()

    def _remove_annotation_segmentation_entry(self) -> None:
        removed_active = self._active_segmentation_is_annotation()
        self.state.loaded_segmentations = [
            segmentation
            for segmentation in self.state.loaded_segmentations
            if segmentation.kind != "annotation"
        ]
        if removed_active:
            self.state.active_segmentation_id = (
                self.state.loaded_segmentations[0].id
                if self.state.loaded_segmentations
                else None
            )
            self._apply_active_segmentation_overlay()
        self._refresh_segmentation_ui()

    def _active_segmentation_is_annotation(self) -> bool:
        active_segmentation = self._active_segmentation()
        return active_segmentation is not None and active_segmentation.kind == "annotation"

    def _extract_active_annotation_patch(
        self,
        bounds: PatchBounds,
    ) -> AnnotationMask | None:
        annotation_volume = self._active_annotation_volume()
        annotation_mask = self.state.annotation.active_mask
        if annotation_volume is None or annotation_mask is None:
            return None
        annotation_patch = extract_patch(annotation_volume, bounds)
        return AnnotationMask(
            data=annotation_patch.data,
            affine=annotation_patch.affine,
            header=annotation_patch.header,
            labels=annotation_mask.labels,
        )

    def _update_patch_windows_annotation_for_current_image(
        self,
        *,
        exclude: PatchViewerWindow | None = None,
    ) -> None:
        for patch_window in self._patch_windows_for_current_image():
            if patch_window is exclude:
                continue
            bounds = patch_window.source_patch_bounds()
            annotation_patch = (
                self._extract_active_annotation_patch(bounds)
                if bounds is not None
                else None
            )
            patch_window.update_annotation_overlay(
                annotation_patch,
                opacity=self.state.annotation.opacity,
                visible=self.state.annotation.visible,
                active_label=self.state.annotation.active_label,
                editing_enabled=self.state.annotation.editing_enabled
                and annotation_patch is not None,
                brush_radius=self.state.annotation.brush_radius,
                brush_mode=self.state.annotation.brush_mode,
            )

    def _update_patch_windows_annotation_display_options(self) -> None:
        for patch_window in self._patch_windows_for_current_image():
            patch_window.update_annotation_display_options(
                opacity=self.state.annotation.opacity,
                visible=self.state.annotation.visible,
                active_label=self.state.annotation.active_label,
                brush_radius=self.state.annotation.brush_radius,
                brush_mode=self.state.annotation.brush_mode,
            )

    def _on_patch_window_annotation_create_requested(
        self,
        patch_window: PatchViewerWindow,
    ) -> None:
        self._on_create_annotation()
        self._update_patch_windows_annotation_for_current_image(exclude=None)

    def _on_patch_window_annotation_patch_changed(
        self,
        patch_window: PatchViewerWindow,
    ) -> None:
        annotation_mask = self.state.annotation.active_mask
        patch_mask = patch_window.annotation_mask()
        bounds = patch_window.source_patch_bounds()
        if annotation_mask is None or patch_mask is None or bounds is None:
            return

        target = annotation_mask.data[bounds.as_slices()]
        if target.shape != patch_mask.shape:
            QMessageBox.warning(
                self,
                "Patch Annotation Failed",
                (
                    "Patch annotation shape does not match the selected source "
                    "bounds; changes were not applied."
                ),
            )
            return

        target[...] = patch_mask.data
        self.slice_viewer.refresh_annotation_overlay()
        self.annotation_panel.set_undo_available(self.slice_viewer.annotation_can_undo())
        self._register_annotation_as_segmentation(
            preserve_existing_display_name=True,
            make_active=self._active_segmentation_is_annotation(),
        )
        self._update_patch_windows_annotation_for_current_image(exclude=patch_window)
        self.statusBar().showMessage("Patch annotation updated source annotation layer")

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

    def _on_viewer_graph_state_file_dropped(self, dropped_path: Path) -> None:
        choice = QMessageBox.question(
            self,
            "Restore Patch Graph?",
            (
                f"Restore the patch window and graph state from\n"
                f"{dropped_path.name}?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if choice != QMessageBox.StandardButton.Yes:
            self.statusBar().showMessage("Graph state restoration canceled")
            return
        try:
            patch_window, result = self.restore_graph_patch(dropped_path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Graph State Load Failed", str(exc))
            self.statusBar().showMessage("Graph state restoration failed")
            return
        warning_suffix = (
            f" ({'; '.join(result.warnings)})" if result.warnings else ""
        )
        self.statusBar().showMessage(
            f"Restored graph patch {patch_window.graph_session_id}{warning_suffix}"
        )

    def restore_graph_patch(
        self, path: str | Path
    ) -> tuple[PatchViewerWindow, GraphLoadResult]:
        """Recreate a fresh source patch window and load its saved graph state."""

        if self.state.volume is None or self.state.loaded_file_path is None:
            raise ValueError(
                "Load the graph state's source image before restoring its patch."
            )
        metadata = read_graph_restore_metadata(path)
        bounds = metadata.patch_bounds
        if bounds is None:
            raise ValueError(
                "This graph state has no source patch bounds and cannot recreate a "
                "patch window."
            )
        source_shape = tuple(int(value) for value in self.state.volume.shape[:3])
        starts = (bounds.x_start, bounds.y_start, bounds.z_start)
        ends = (bounds.x_end, bounds.y_end, bounds.z_end)
        if any(
            start < 0 or end > source_shape[axis] or start >= end
            for axis, (start, end) in enumerate(zip(starts, ends, strict=True))
        ):
            raise ValueError(
                f"Saved patch bounds are outside the loaded source image shape "
                f"{source_shape}."
            )
        patch_shape = tuple(end - start for start, end in zip(starts, ends, strict=True))
        if patch_shape != metadata.patch_shape:
            raise ValueError(
                "Saved patch bounds do not match the saved patch dimensions."
            )
        center = tuple(
            (start + end - 1) // 2 for start, end in zip(starts, ends, strict=True)
        )
        patch_window = self._build_patch_window(
            bounds,
            center=center,
            patch_size=metadata.patch_shape,
        )
        try:
            result = patch_window.load_graph_state(path)
        except Exception:
            patch_window.deleteLater()
            raise
        self.state.selected_patch_bounds = bounds
        self.state.selected_patch_data = patch_window.patch_volume()
        self._register_patch_window(patch_window)
        return patch_window, result

    def _on_unload_current_segmentation(self) -> None:
        active_segmentation = self._active_segmentation()
        if active_segmentation is None:
            self.statusBar().showMessage("No active segmentation to unload")
            return

        self._unload_segmentation_by_id(active_segmentation.id)

    def _on_unload_segmentation_requested(self, segmentation_id: str) -> None:
        self._unload_segmentation_by_id(segmentation_id)

    def _unload_segmentation_by_id(self, segmentation_id: str) -> None:
        target_segmentation = next(
            (
                segmentation
                for segmentation in self.state.loaded_segmentations
                if segmentation.id == segmentation_id
            ),
            None,
        )
        if target_segmentation is None:
            self.statusBar().showMessage("Segmentation is no longer loaded")
            return

        if target_segmentation.kind == "annotation":
            self._clear_annotation_session()
            self.statusBar().showMessage("Unloaded annotation layer")
            return

        removed_active = self.state.active_segmentation_id == target_segmentation.id
        self.state.loaded_segmentations = [
            segmentation
            for segmentation in self.state.loaded_segmentations
            if segmentation.id != target_segmentation.id
        ]
        if removed_active:
            self.state.active_segmentation_id = (
                self.state.loaded_segmentations[0].id
                if self.state.loaded_segmentations
                else None
            )
        self._apply_active_segmentation_overlay()
        self._refresh_segmentation_ui()
        self.statusBar().showMessage("Unloaded segmentation")

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

    def _on_overlay_segmentation_changed(self, segmentation_id: object) -> None:
        if segmentation_id is None:
            self.state.active_segmentation_id = None
        elif isinstance(segmentation_id, str) and any(
            segmentation.id == segmentation_id
            for segmentation in self.state.loaded_segmentations
        ):
            self.state.active_segmentation_id = segmentation_id
        else:
            return
        self._apply_active_segmentation_overlay()
        self._refresh_segmentation_ui()

    def _on_segmentation_opacity_changed(self, opacity: float) -> None:
        if self._active_segmentation_is_annotation():
            self._on_annotation_opacity_changed(opacity)
            return
        self.state.segmentation_opacity = min(max(opacity, 0.0), 1.0)
        self.segmentation_config_window.set_opacity(self.state.segmentation_opacity)
        self.overlay_opacity_control_bar.set_opacity(
            self.state.segmentation_opacity
        )
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
        self.slice_viewer.set_annotation_overlay_visible(
            self.state.annotation.visible
            and active_segmentation is not None
            and active_segmentation.kind == "annotation"
        )
        if active_segmentation is None:
            self.slice_viewer.set_segmentation_overlay(
                None,
                opacity=self.state.segmentation_opacity,
            )
            self._update_patch_windows_segmentation_for_current_image(None)
            return
        if active_segmentation.kind == "annotation":
            self.slice_viewer.set_segmentation_overlay(
                None,
                opacity=self.state.segmentation_opacity,
            )
            self._update_patch_windows_segmentation_for_current_image(
                active_segmentation
            )
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
                (
                    segmentation.id,
                    segmentation.display_name,
                    str(segmentation.path)
                    if segmentation.path is not None
                    else segmentation.display_name,
                )
                for segmentation in self.state.loaded_segmentations
            ],
            self.state.active_segmentation_id,
        )
        active_opacity = (
            self.state.annotation.opacity
            if self._active_segmentation_is_annotation()
            else self.state.segmentation_opacity
        )
        self.segmentation_config_window.set_opacity(active_opacity)
        self.overlay_opacity_control_bar.set_opacity(active_opacity)
        overlay_options = [
            (segmentation.id, segmentation.display_name)
            for segmentation in self.state.loaded_segmentations
        ]
        self.overlay_opacity_control_bar.set_segmentations(
            overlay_options,
            self.state.active_segmentation_id,
        )
        self._update_patch_windows_projection_masks_for_current_image()
        self._sync_patch_windows_segmentation_menu_state()
        self._sync_volume_3d_sources()

    def _sync_volume_3d_sources(self) -> None:
        sources: list[Render3DSource] = []
        if self.state.volume is not None:
            sources.append(
                Render3DSource(
                    id="image",
                    display_name=(
                        self.state.loaded_file_path.name
                        if self.state.loaded_file_path is not None
                        else "Loaded image"
                    ),
                    volume=self.state.volume,
                    kind="image",
                )
            )
        sources.extend(
            Render3DSource(
                id=segmentation.id,
                display_name=segmentation.display_name,
                volume=segmentation.volume,
                kind="segmentation",
            )
            for segmentation in self.state.loaded_segmentations
        )
        self.slice_viewer.volume_3d_view.set_sources(sources)

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

    def graph_patch_window(self, session_id: str) -> PatchViewerWindow | None:
        normalized_session_id = str(session_id).strip()
        return next(
            (
                patch_window
                for patch_window in self._patch_windows_for_current_image()
                if patch_window.graph_session_id == normalized_session_id
            ),
            None,
        )

    def graph_session_summaries(self) -> list[dict[str, object]]:
        return [
            patch_window.graph_status()
            for patch_window in self._patch_windows_for_current_image()
        ]

    def _update_patch_windows_segmentation_for_current_image(
        self,
        active_segmentation: LoadedSegmentation | None,
    ) -> None:
        for patch_window in self._patch_windows_for_current_image():
            bounds = patch_window.source_patch_bounds()
            if (
                active_segmentation is None
                or active_segmentation.kind == "annotation"
                or bounds is None
            ):
                patch_window.update_segmentation_overlay(
                    None,
                    opacity=self.state.segmentation_opacity,
                    active_segmentation_kind=(
                        None
                        if active_segmentation is None
                        else active_segmentation.kind
                    ),
                )
                continue
            patch_window.update_segmentation_overlay(
                extract_patch(active_segmentation.volume, bounds),
                opacity=self.state.segmentation_opacity,
                active_segmentation_kind=active_segmentation.kind,
            )

    def _projection_mask_layers_for_bounds(
        self,
        bounds: PatchBounds,
    ) -> list[tuple[str, str, NiftiLoadResult]]:
        return [
            (
                segmentation.id,
                segmentation.display_name,
                extract_patch(segmentation.volume, bounds),
            )
            for segmentation in self.state.loaded_segmentations
            if segmentation.kind == "file"
        ]

    def _update_patch_windows_projection_masks_for_current_image(self) -> None:
        for patch_window in self._patch_windows_for_current_image():
            bounds = patch_window.source_patch_bounds()
            if bounds is None:
                patch_window.update_projection_mask_layers(())
                continue
            patch_window.update_projection_mask_layers(
                self._projection_mask_layers_for_bounds(bounds)
            )

    def _sync_patch_windows_segmentation_menu_state(self) -> None:
        has_image = self.state.volume is not None
        has_segmentations = len(self.state.loaded_segmentations) > 0
        for patch_window in self._patch_windows_for_current_image():
            self._sync_patch_window_segmentation_menu_state(
                patch_window,
                has_segmentations=has_segmentations,
                has_image=has_image,
            )

    def _sync_patch_window_segmentation_menu_state(
        self,
        patch_window: PatchViewerWindow,
        *,
        has_segmentations: bool | None = None,
        has_image: bool | None = None,
    ) -> None:
        patch_window.set_segmentation_menu_enabled(
            can_unload=(
                len(self.state.loaded_segmentations) > 0
                if has_segmentations is None
                else has_segmentations
            ),
            can_open_configuration=(
                self.state.volume is not None if has_image is None else has_image
            ),
        )
        patch_window.set_overlay_segmentations(
            [
                (segmentation.id, segmentation.display_name)
                for segmentation in self.state.loaded_segmentations
            ],
            self.state.active_segmentation_id,
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
        if self._dropped_path_for_viewer(event, source_widget) is None:
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
        dropped_path = self._dropped_path_for_viewer(event, source_widget)
        if dropped_path is None:
            event.ignore()
            return False
        event.acceptProposedAction()
        if is_supported_graph_state_path(dropped_path):
            self._on_viewer_graph_state_file_dropped(dropped_path)
        else:
            self._on_viewer_nifti_file_dropped(dropped_path)
        return True

    def _dropped_path_for_viewer(
        self,
        event: QDragEnterEvent | QDragMoveEvent | QDropEvent,
        source_widget: QObject,
    ) -> Path | None:
        if self._event_point_hits_slice_viewer(source_widget, event.position().toPoint()) is False:
            return None
        mime_data = event.mimeData()
        if mime_data is None or not mime_data.hasUrls():
            return None
        return first_supported_local_drop_path(mime_data.urls())

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
        self.cursor_panel.set_axis_directions(loaded.affine)
        self.state.cursor_position = self.slice_viewer.current_cursor_position()
        self.state.selected_patch_bounds = None
        self.state.selected_patch_data = None
        self._clear_annotation_session()
        cleared_count = self._reset_segmentation_session_for_loaded_image(image_path)
        self._sync_volume_3d_sources()
        self._initialize_contrast_for_loaded_volume()
        self._refresh_patch_selection_ui()

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
