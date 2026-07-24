from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
from PySide6.QtCore import (
    QEvent,
    QObject,
    QPointF,
    QRectF,
    QRunnable,
    QThreadPool,
    Qt,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QFont,
    QPaintEvent,
    QPainter,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from mipview.io.nifti_io import NiftiLoadResult
from mipview.patch.selector import PatchBounds
from mipview.ui.volume_3d_panel import Volume3DPanel
from mipview.viewer.orientation_indicator import (
    ORIENTATION_INDICATOR_LABELS,
    ORIENTATION_INDICATOR_WIDGET,
    OrientationIndicatorMode,
    normalize_orientation_indicator_mode,
    orientation_axis_colour,
)
from mipview.viewer.render_3d_preparation import (
    PreparedRender3D,
    cursor_world_position,
    orientation_label_world_positions,
    patch_box_world_segments,
    prepare_render,
    source_box_world_segments,
)
from mipview.viewer.render_3d_state import (
    RAW_RENDER_MODES,
    SEGMENTATION_RENDER_MODES,
    Render3DSource,
    Render3DState,
)


class _PreparationSignals(QObject):
    finished = Signal(int, object)
    failed = Signal(int, str)


class _PreparationWorker(QRunnable):
    def __init__(
        self,
        token: int,
        source: Render3DSource,
        render_mode: str,
        threshold: float,
    ) -> None:
        super().__init__()
        self.token = token
        self.source = source
        self.render_mode = render_mode
        self.threshold = threshold
        self.signals = _PreparationSignals()

    @Slot()
    def run(self) -> None:
        try:
            prepared = prepare_render(
                self.source.volume,
                kind=self.source.kind,
                render_mode=self.render_mode,
                threshold=self.threshold,
            )
        except Exception as exc:
            self.signals.failed.emit(self.token, str(exc))
            return
        self.signals.finished.emit(self.token, prepared)


@dataclass
class _PatchBoxState:
    bounds: PatchBounds | None = None
    affine: np.ndarray | None = None
    visible: bool = False


class _Volume3DCursorOverlay(QWidget):
    """Mouse-transparent cursor and orientation overlay above the VisPy canvas."""

    def __init__(
        self,
        position_provider: Callable[[], tuple[float, float] | None],
        mode_provider: Callable[[], OrientationIndicatorMode],
        orientation_provider: Callable[
            [], tuple[tuple[str, float, float], ...]
        ],
        widget_provider: Callable[
            [], tuple[tuple[str, float, float], ...]
        ],
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self._position_provider = position_provider
        self._mode_provider = mode_provider
        self._orientation_provider = orientation_provider
        self._widget_provider = widget_provider
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        parent.installEventFilter(self)
        self.setGeometry(parent.rect())
        self.show()
        self.raise_()

    def detach(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            parent.removeEventFilter(self)
        self.close()
        self.setParent(None)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        parent = self.parentWidget()
        if watched is parent and event.type() in {
            QEvent.Type.Resize,
            QEvent.Type.Show,
        }:
            self.setGeometry(parent.rect())
            self.raise_()
            self.update()
        return False

    def paintEvent(self, event: QPaintEvent) -> None:
        _ = event
        position = self._position_provider()
        orientation_mode = self._mode_provider()
        orientation_labels = (
            self._orientation_provider()
            if orientation_mode == ORIENTATION_INDICATOR_LABELS
            else ()
        )
        orientation_widget = (
            self._widget_provider()
            if orientation_mode == ORIENTATION_INDICATOR_WIDGET
            else ()
        )
        if (
            position is None
            and not orientation_labels
            and not orientation_widget
        ):
            return

        painter = QPainter(self)
        if position is not None:
            x = int(round(position[0]))
            y = int(round(position[1]))
            if 0 <= x < self.width() and 0 <= y < self.height():
                painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
                pen = QPen(QColor("#ffb000"))
                pen.setWidth(1)
                painter.setPen(pen)
                painter.drawLine(x, 0, x, self.height() - 1)
                painter.drawLine(0, y, self.width() - 1, y)

        if orientation_labels:
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            label_font = QFont(self.font())
            label_font.setBold(True)
            painter.setFont(label_font)
            painter.setPen(QPen(QColor("#ffd400")))
            font_metrics = painter.fontMetrics()
            margin = 8.0
            for label, projected_x, projected_y in orientation_labels:
                text_width = max(float(font_metrics.horizontalAdvance(label) + 6), 16.0)
                text_height = max(float(font_metrics.height() + 4), 16.0)
                center_x = min(
                    max(float(projected_x), margin + text_width / 2.0),
                    max(margin + text_width / 2.0, self.width() - margin - text_width / 2.0),
                )
                center_y = min(
                    max(float(projected_y), margin + text_height / 2.0),
                    max(
                        margin + text_height / 2.0,
                        self.height() - margin - text_height / 2.0,
                    ),
                )
                painter.drawText(
                    QRectF(
                        center_x - text_width / 2.0,
                        center_y - text_height / 2.0,
                        text_width,
                        text_height,
                    ),
                    Qt.AlignmentFlag.AlignCenter,
                    label,
                )
        if orientation_widget:
            self._draw_orientation_widget(painter, orientation_widget)
        painter.end()

    def _draw_orientation_widget(
        self,
        painter: QPainter,
        axes: tuple[tuple[str, float, float], ...],
    ) -> None:
        widget_extent = 42.0
        center = np.asarray(
            [
                max(
                    widget_extent + 8.0,
                    self.width() - widget_extent - 10.0,
                ),
                max(
                    widget_extent + 8.0,
                    self.height() - widget_extent - 10.0,
                ),
            ],
            dtype=np.float64,
        )
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        label_font = QFont(self.font())
        label_font.setBold(True)
        painter.setFont(label_font)
        axis_length = 25.0
        for index, (label, direction_x, direction_y) in enumerate(axes):
            colour = QColor(orientation_axis_colour(label))
            direction = np.asarray(
                [direction_x, direction_y],
                dtype=np.float64,
            )
            projected_length = float(np.linalg.norm(direction))
            if projected_length <= 1.0e-6:
                painter.setPen(QPen(colour, 2))
                painter.setBrush(colour)
                painter.drawEllipse(QPointF(*center), 3.0, 3.0)
                label_center = center + np.asarray(
                    [(index - 1) * 13.0, -9.0],
                    dtype=np.float64,
                )
            else:
                endpoint = center + direction * axis_length
                self._draw_widget_arrow(
                    painter,
                    QPointF(*center),
                    QPointF(*endpoint),
                    colour,
                )
                label_center = endpoint + (
                    direction / projected_length
                ) * 8.0
            painter.setPen(QPen(colour))
            painter.drawText(
                QRectF(
                    float(label_center[0] - 8.0),
                    float(label_center[1] - 8.0),
                    16.0,
                    16.0,
                ),
                Qt.AlignmentFlag.AlignCenter,
                label,
            )
        painter.restore()

    @staticmethod
    def _draw_widget_arrow(
        painter: QPainter,
        start: QPointF,
        end: QPointF,
        colour: QColor,
    ) -> None:
        pen = QPen(colour, 2)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(colour)
        painter.drawLine(start, end)
        delta = np.asarray(
            [end.x() - start.x(), end.y() - start.y()],
            dtype=np.float64,
        )
        length = float(np.linalg.norm(delta))
        if length <= 0.0:
            return
        unit = delta / length
        perpendicular = np.asarray([-unit[1], unit[0]])
        base = np.asarray([end.x(), end.y()]) - unit * 6.0
        painter.drawPolygon(
            QPolygonF(
                [
                    end,
                    QPointF(*(base + perpendicular * 4.0)),
                    QPointF(*(base - perpendicular * 4.0)),
                ]
            )
        )


class Volume3DWidget(QWidget):
    """Lazy VisPy scene for one isolated NIfTI layer plus locator geometry."""

    render_started = Signal()
    render_finished = Signal(object)
    render_failed = Signal(str)
    state_changed = Signal(object)
    active_changed = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.state = Render3DState()
        self._panel: Volume3DPanel | None = None
        self._thread_pool = QThreadPool.globalInstance()
        self._job_token = 0
        self._workers: dict[int, _PreparationWorker] = {}
        self._canvas: Any | None = None
        self._view: Any | None = None
        self._active_visual: Any | None = None
        self._prepared: PreparedRender3D | None = None
        self._patch_visual: Any | None = None
        self._source_box_visual: Any | None = None
        self._locator_visual: Any | None = None
        self._cursor_overlay: _Volume3DCursorOverlay | None = None
        self._volume_shape: tuple[int, int, int] | None = None
        self._volume_affine: np.ndarray | None = None
        self._cursor_position: tuple[int, int, int] | None = None
        self._cursor_visible = True
        self._orientation_indicator_mode: OrientationIndicatorMode = (
            ORIENTATION_INDICATOR_LABELS
        )
        self._locator_volume: NiftiLoadResult | None = None
        self._locator_visible = False
        self._locator_source_shape: tuple[int, int, int] | None = None
        self._locator_source_affine: np.ndarray | None = None
        self._patch_box = _PatchBoxState()

        self.title_label = QLabel("3D", self)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder = QLabel("3D view inactive", self)
        self.placeholder.setStyleSheet(
            "background: #121212; color: #aaa; padding: 12px;"
        )
        # Match the slice viewport's flexible minimum height so the shared
        # horizontal row splitter is not locked by the inactive 3D pane.
        self.placeholder.setMinimumSize(220, 96)
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._render_container = QWidget(self)
        self._render_layout = QVBoxLayout(self._render_container)
        self._render_layout.setContentsMargins(0, 0, 0, 0)
        self._render_layout.setSpacing(0)
        self._render_layout.addWidget(self.placeholder)
        self._footer_spacer = QWidget(self)
        self._footer_spacer.setFixedHeight(0)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self._layout.addWidget(self.title_label)
        self._layout.addWidget(self._render_container, 1)
        self._layout.addWidget(self._footer_spacer)

    def set_footer_height(self, height: int) -> None:
        """Match the space occupied by slice-slider controls in adjacent panes."""
        self._footer_spacer.setFixedHeight(max(int(height), 0))

    def connect_panel(self, panel: Volume3DPanel) -> None:
        self._panel = panel
        panel.activation_requested.connect(self.set_active)
        panel.source_changed.connect(self.select_source)
        panel.visibility_changed.connect(self.set_selected_visibility)
        panel.opacity_changed.connect(self.set_selected_opacity)
        panel.colour_changed.connect(self.set_selected_colour)
        panel.render_mode_changed.connect(self.set_selected_render_mode)
        panel.threshold_changed.connect(self.set_selected_threshold)
        panel.update_requested.connect(self.update_selected_render)
        panel.reset_camera_requested.connect(self.reset_camera)
        self._sync_panel_sources()
        self._sync_panel_settings()

    def set_sources(self, sources: list[Render3DSource]) -> None:
        if self.state.busy:
            self._cancel_pending_preparation("Loaded files changed; update again.")
        rendered_before = self.state.rendered_source_id
        previous_source = (
            None
            if rendered_before is None
            else self.state.sources.get(rendered_before)
        )
        replacement_source = next(
            (source for source in sources if source.id == rendered_before),
            None,
        )
        self.state.set_sources(sources)
        source_data_changed = (
            previous_source is not None
            and replacement_source is not None
            and previous_source.volume is not replacement_source.volume
        )
        if (
            rendered_before is not None
            and (
                self.state.rendered_source_id is None
                or source_data_changed
            )
        ):
            self._release_active_visual()
            self.state.rendered_source_id = None
            settings = self.state.settings.get(rendered_before)
            if settings is not None:
                settings.dirty = True
        self._sync_panel_sources()
        self._sync_panel_settings()
        self._emit_state()

    def select_source(self, source_id: object) -> None:
        if self.state.busy:
            self._cancel_pending_preparation("3D layer changed; click Update.")
        normalized = source_id if isinstance(source_id, str) else None
        rendered_source_id = self.state.rendered_source_id
        try:
            self.state.select_source(normalized)
        except ValueError as exc:
            self._set_error(str(exc))
            return
        if rendered_source_id is not None and normalized != rendered_source_id:
            self._release_active_visual()
            self.state.rendered_source_id = None
            self.state.prepared_shape = None
            self.state.downsample_stride = None
        self._sync_panel_settings()
        self._emit_state()

    def set_active(self, active: bool) -> None:
        if not active:
            self.dismiss()
            return
        if self.state.active:
            return
        try:
            self._initialize_canvas()
        except Exception as exc:
            self.state.active = False
            self._set_error(f"Unable to initialize 3D rendering: {exc}")
            if self._panel is not None:
                self._panel.set_active(False)
            return
        self.state.active = True
        self.state.last_error = None
        self.placeholder.setVisible(False)
        if self._panel is not None:
            self._panel.set_active(True)
            self._panel.set_status("Choose a layer and click Update.")
        self._refresh_patch_visual()
        self._refresh_locator_visual()
        self._refresh_cursor_overlay()
        self._refresh_orientation_overlay()
        self._emit_state()
        self.active_changed.emit(True)

    def dismiss(self) -> None:
        was_active = self.state.active
        self._job_token += 1
        self.state.busy = False
        self.state.active = False
        self.state.rendered_source_id = None
        self.state.prepared_shape = None
        self.state.downsample_stride = None
        self._prepared = None
        self._destroy_canvas()
        self.placeholder.setText("3D view inactive")
        self.placeholder.setVisible(True)
        if self._panel is not None:
            self._panel.set_busy(False)
            self._panel.set_active(False)
            self._panel.set_status("3D resources released.")
        self._emit_state()
        if was_active:
            self.active_changed.emit(False)

    def update_selected_render(self) -> None:
        if not self.state.active:
            self.set_active(True)
        if not self.state.active:
            return
        source = self.state.selected_source()
        settings = self.state.selected_settings()
        if source is None or settings is None:
            self._set_error("Load an image or segmentation before rendering.")
            return

        self._job_token += 1
        token = self._job_token
        worker = _PreparationWorker(
            token,
            source,
            settings.render_mode,
            settings.threshold,
        )
        self._workers[token] = worker
        worker.signals.finished.connect(self._on_preparation_finished)
        worker.signals.failed.connect(self._on_preparation_failed)
        self.state.busy = True
        self.state.last_error = None
        if self._panel is not None:
            self._panel.set_busy(True)
            self._panel.set_progress(10, "Preparing and downsampling 3D layer…")
        self.render_started.emit()
        self._emit_state()
        self._thread_pool.start(worker)

    def set_selected_visibility(self, visible: bool) -> None:
        settings = self.state.selected_settings()
        if settings is None:
            return
        settings.visible = bool(visible)
        if (
            self.state.selected_source_id == self.state.rendered_source_id
            and self._active_visual is not None
        ):
            self._active_visual.visible = settings.visible
            self._request_canvas_update()
        self._emit_state()

    def set_selected_opacity(self, opacity: float) -> None:
        settings = self.state.selected_settings()
        if settings is None:
            return
        settings.set_opacity(opacity)
        self._apply_active_style()
        self._emit_state()

    def set_selected_colour(self, colour: object) -> None:
        settings = self.state.selected_settings()
        if settings is None or not isinstance(colour, tuple):
            return
        settings.set_colour(colour)
        self._apply_active_style()
        self._emit_state()

    def set_selected_render_mode(self, render_mode: str) -> None:
        source = self.state.selected_source()
        settings = self.state.selected_settings()
        if source is None or settings is None:
            return
        allowed = RAW_RENDER_MODES if source.kind == "image" else SEGMENTATION_RENDER_MODES
        if render_mode not in allowed:
            return
        if settings.render_mode != render_mode:
            if self.state.busy:
                self._cancel_pending_preparation(
                    "Render mode changed; click Update."
                )
            settings.render_mode = render_mode
            settings.dirty = True
        if self._panel is not None:
            self._panel.set_status("Update required.")
        self._emit_state()

    def set_selected_threshold(self, threshold: float) -> None:
        settings = self.state.selected_settings()
        if settings is None:
            return
        value = float(threshold)
        if settings.threshold != value:
            if self.state.busy:
                self._cancel_pending_preparation(
                    "Threshold changed; click Update."
                )
            settings.threshold = value
            settings.dirty = True
        if self._panel is not None:
            self._panel.set_status("Update required.")
        self._emit_state()

    def mark_selected_dirty(self, message: str = "Update required.") -> None:
        self.state.mark_selected_dirty()
        if self._panel is not None:
            self._panel.set_status(message)
        self._emit_state()

    def reset_camera(self) -> None:
        if self._view is not None:
            camera = self._view.camera
            camera.azimuth = 30.0
            camera.elevation = 30.0
            camera.roll = 0.0
            limits = self._camera_world_limits()
            if limits is None:
                camera.set_range()
            else:
                camera.set_range(
                    x=limits[0],
                    y=limits[1],
                    z=limits[2],
                    margin=0.08,
                )
            self._request_canvas_update()

    def _camera_world_limits(
        self,
    ) -> tuple[
        tuple[float, float],
        tuple[float, float],
        tuple[float, float],
    ] | None:
        if self._locator_visible:
            if self._locator_volume is not None:
                return _volume_world_limits(
                    tuple(int(value) for value in self._locator_volume.shape),
                    self._locator_volume.affine,
                )
            if (
                self._locator_source_shape is not None
                and self._locator_source_affine is not None
            ):
                return _volume_world_limits(
                    self._locator_source_shape,
                    self._locator_source_affine,
                )

        if self._volume_shape is not None and self._volume_affine is not None:
            return _volume_world_limits(
                self._volume_shape,
                self._volume_affine,
            )

        prepared = self._prepared
        if prepared is None:
            return None
        if prepared.texture_affine is not None:
            return _volume_world_limits(
                prepared.prepared_shape,
                prepared.texture_affine,
            )
        if prepared.vertices is not None and prepared.vertices.size:
            return _point_world_limits(prepared.vertices)
        return None

    def set_patch_box(
        self,
        bounds: PatchBounds | None,
        affine: np.ndarray | None,
        *,
        visible: bool,
    ) -> None:
        self._patch_box = _PatchBoxState(
            bounds=bounds,
            affine=None if affine is None else np.asarray(affine, dtype=np.float64),
            visible=bool(visible),
        )
        self._refresh_patch_visual()

    def set_volume_geometry(
        self,
        shape: tuple[int, int, int] | None,
        affine: np.ndarray | None,
    ) -> None:
        """Set source voxel geometry used by the cursor and orientation labels."""
        if shape is None or affine is None:
            self._volume_shape = None
            self._volume_affine = None
            self._cursor_position = None
        else:
            normalized_shape = tuple(int(value) for value in shape)
            if len(normalized_shape) != 3 or any(
                value <= 0 for value in normalized_shape
            ):
                raise ValueError(
                    "3D source geometry must contain three positive shape values."
                )
            normalized_affine = np.asarray(affine, dtype=np.float64)
            if normalized_affine.shape != (4, 4):
                raise ValueError(
                    f"3D source affine must be 4x4, got {normalized_affine.shape}."
                )
            self._volume_shape = normalized_shape
            self._volume_affine = normalized_affine
        self._refresh_cursor_overlay()
        self._refresh_orientation_overlay()

    def set_cursor_position(
        self,
        cursor_position: tuple[int, int, int] | None,
    ) -> None:
        self._cursor_position = (
            None
            if cursor_position is None
            else tuple(int(value) for value in cursor_position)
        )
        self._refresh_cursor_overlay()

    def set_cursor_overlay_visible(self, visible: bool) -> None:
        self._cursor_visible = bool(visible)
        self._refresh_cursor_overlay()

    def set_orientation_indicator_mode(self, mode: str) -> None:
        normalized = normalize_orientation_indicator_mode(mode)
        if normalized == self._orientation_indicator_mode:
            return
        self._orientation_indicator_mode = normalized
        self._refresh_orientation_overlay()

    def orientation_indicator_mode(self) -> OrientationIndicatorMode:
        return self._orientation_indicator_mode

    def set_locator_context(
        self,
        volume: NiftiLoadResult | None,
        *,
        visible: bool,
    ) -> None:
        if (
            self._locator_volume is volume
            and self._locator_visible == bool(visible)
            and (
                not visible
                or self._view is None
                or self._locator_visual is not None
            )
        ):
            return
        self._locator_volume = volume
        self._locator_visible = bool(visible)
        self._refresh_locator_visual()

    def set_locator_source_extent(
        self,
        shape: tuple[int, int, int] | None,
        affine: np.ndarray | None,
    ) -> None:
        self._locator_source_shape = shape
        self._locator_source_affine = (
            None if affine is None else np.asarray(affine, dtype=np.float64)
        )
        self._refresh_locator_visual()

    def status(self) -> dict[str, object]:
        status = self.state.status()
        status["locator_visible"] = self._locator_visible
        status["patch_box_visible"] = self._patch_box.visible
        status["cursor_visible"] = self._cursor_visible
        status["cursor_position"] = (
            None
            if self._cursor_position is None
            else list(self._cursor_position)
        )
        status["orientation_indicator_mode"] = (
            self._orientation_indicator_mode
        )
        return status

    def closeEvent(self, event: QCloseEvent) -> None:
        self.dismiss()
        super().closeEvent(event)

    @Slot(int, object)
    def _on_preparation_finished(
        self,
        token: int,
        prepared: PreparedRender3D,
    ) -> None:
        self._workers.pop(token, None)
        if token != self._job_token or not self.state.active:
            return
        source_id = self.state.selected_source_id
        settings = self.state.selected_settings()
        if source_id is None or settings is None:
            return
        try:
            if self._panel is not None:
                self._panel.set_progress(85, "Uploading 3D layer to the GPU…")
            self._release_active_visual()
            self._prepared = prepared
            self._active_visual = self._create_visual(prepared, settings)
        except Exception as exc:
            self._on_preparation_failed(token, f"GPU upload failed: {exc}")
            return

        self.state.rendered_source_id = source_id
        self.state.prepared_shape = prepared.prepared_shape
        self.state.downsample_stride = prepared.stride
        self.state.busy = False
        settings.dirty = False
        if self._panel is not None:
            self._panel.set_busy(False)
            self._panel.set_status(
                "3D layer ready"
                if prepared.stride == (1, 1, 1)
                else f"3D layer ready (overview stride {prepared.stride[0]})."
            )
        self.reset_camera()
        payload = self.status()
        self.render_finished.emit(payload)
        self._emit_state()

    @Slot(int, str)
    def _on_preparation_failed(self, token: int, message: str) -> None:
        self._workers.pop(token, None)
        if token != self._job_token:
            return
        self.state.busy = False
        self._set_error(message)
        if self._panel is not None:
            self._panel.set_busy(False)

    def _initialize_canvas(self) -> None:
        if self._canvas is not None:
            return
        from vispy import app, scene

        app.use_app("pyside6")
        canvas = scene.SceneCanvas(
            keys="interactive",
            show=False,
            bgcolor="#121212",
            parent=self,
        )
        native = canvas.native
        self._render_layout.addWidget(native)
        # Mark the native canvas visible even when its parent viewer is
        # temporarily hidden by the selected layout mode. Qt will expose it
        # when the 3D pane is inserted into the active splitter.
        native.show()
        self._canvas = canvas
        self._view = canvas.central_widget.add_view()
        class _MiddlePanTurntableCamera(scene.cameras.TurntableCamera):
            def viewbox_mouse_event(camera_self: Any, event: Any) -> None:
                if _pan_camera_with_middle_drag(camera_self, event):
                    return
                super().viewbox_mouse_event(event)

        self._view.camera = _MiddlePanTurntableCamera(
            fov=45.0,
            up="+z",
        )
        self._cursor_overlay = _Volume3DCursorOverlay(
            self._cursor_canvas_position,
            self.orientation_indicator_mode,
            self._orientation_canvas_positions,
            self._orientation_widget_axes,
            native,
        )
        self._view.scene.transform.changed.connect(
            self._on_scene_transform_changed
        )
        if self.isVisible():
            QApplication.processEvents()
            if hasattr(native, "isValid") and not native.isValid():
                self._destroy_canvas()
                raise RuntimeError(
                    "OpenGL context creation failed. Check the display connection "
                    "and graphics driver."
                )

    def _destroy_canvas(self) -> None:
        self._release_active_visual()
        if self._view is not None:
            self._view.scene.transform.changed.disconnect(
                self._on_scene_transform_changed
            )
        if self._cursor_overlay is not None:
            self._cursor_overlay.detach()
            self._cursor_overlay = None
        for name in (
            "_patch_visual",
            "_source_box_visual",
            "_locator_visual",
        ):
            visual = getattr(self, name)
            if visual is not None:
                visual.parent = None
                setattr(self, name, None)
        if self._canvas is not None:
            native = self._canvas.native
            self._render_layout.removeWidget(native)
            self._canvas.close()
            native.setParent(None)
            native.deleteLater()
        self._canvas = None
        self._view = None

    def _release_active_visual(self) -> None:
        if self._active_visual is not None:
            self._active_visual.parent = None
        self._active_visual = None
        self._prepared = None

    def _create_visual(self, prepared: PreparedRender3D, settings: Any) -> Any:
        if self._view is None:
            raise RuntimeError("3D scene is not initialized.")
        from vispy import scene
        from vispy.visuals.transforms import MatrixTransform

        rgba = _rgba(settings.colour, settings.opacity)
        if prepared.kind == "image":
            _require_pyopengl_3d_textures()
            method = {
                "MIP": "mip",
                "MinIP": "minip",
                "Translucent": "translucent",
                "Isosurface": "iso",
            }[prepared.render_mode]
            cutoff = _normalized_threshold(
                settings.threshold,
                prepared.source_range,
            )
            visual = scene.visuals.Volume(
                prepared.data,
                method=method,
                clim=(0, 255),
                cmap=_volume_colormap(
                    settings.colour,
                    settings.opacity,
                    translucent=method == "translucent",
                    cutoff=cutoff,
                ),
                parent=self._view.scene,
            )
            if method == "iso":
                visual.threshold = _normalized_threshold(
                    settings.threshold,
                    prepared.source_range,
                )
            transform = MatrixTransform()
            transform.matrix = np.asarray(prepared.texture_affine).T
            visual.transform = transform
        elif prepared.render_mode == "Points":
            visual = scene.visuals.Markers(parent=self._view.scene)
            visual.set_data(
                prepared.vertices,
                face_color=rgba,
                edge_width=0,
                size=4,
            )
        else:
            if prepared.vertices is None or prepared.vertices.size == 0:
                raise ValueError("The selected threshold contains no foreground voxels.")
            visual = scene.visuals.Mesh(
                vertices=prepared.vertices,
                faces=prepared.faces,
                color=rgba,
                shading="smooth",
                parent=self._view.scene,
            )
        visual.visible = settings.visible
        return visual

    def _apply_active_style(self) -> None:
        if (
            self._active_visual is None
            or self._prepared is None
            or self.state.selected_source_id != self.state.rendered_source_id
        ):
            return
        settings = self.state.selected_settings()
        if settings is None:
            return
        rgba = _rgba(settings.colour, settings.opacity)
        if self._prepared.kind == "image":
            cutoff = _normalized_threshold(
                settings.threshold,
                self._prepared.source_range,
            )
            self._active_visual.cmap = _volume_colormap(
                settings.colour,
                settings.opacity,
                translucent=self._prepared.render_mode == "Translucent",
                cutoff=cutoff,
            )
        elif self._prepared.render_mode == "Points":
            self._active_visual.set_data(
                self._prepared.vertices,
                face_color=rgba,
                edge_width=0,
                size=4,
            )
        else:
            self._active_visual.color = rgba
        self._request_canvas_update()

    def _refresh_patch_visual(self) -> None:
        if self._view is None:
            return
        if self._patch_visual is not None:
            self._patch_visual.parent = None
            self._patch_visual = None
        state = self._patch_box
        if not state.visible or state.bounds is None or state.affine is None:
            self._request_canvas_update()
            return
        from vispy import scene

        segments = patch_box_world_segments(state.bounds, state.affine)
        self._patch_visual = scene.visuals.Line(
            pos=segments,
            connect="segments",
            color=(1.0, 0.85, 0.05, 1.0),
            width=2.5,
            parent=self._view.scene,
        )
        self._request_canvas_update()

    def _refresh_cursor_overlay(self) -> None:
        if self._cursor_overlay is not None:
            self._cursor_overlay.update()

    def _cursor_canvas_position(self) -> tuple[float, float] | None:
        if (
            self._view is None
            or not self._cursor_visible
            or self._cursor_position is None
            or self._volume_shape is None
            or self._volume_affine is None
        ):
            return None
        try:
            centre = cursor_world_position(
                self._cursor_position,
                self._volume_shape,
                self._volume_affine,
            )
        except ValueError:
            return None
        return self._world_canvas_position(centre)

    def _world_canvas_position(
        self,
        world_position: np.ndarray,
    ) -> tuple[float, float] | None:
        if self._view is None:
            return None
        mapped = np.asarray(
            self._view.scene.transform.map(world_position),
            dtype=np.float64,
        )
        if mapped.shape != (4,) or not np.all(np.isfinite(mapped)):
            return None
        if abs(float(mapped[3])) <= np.finfo(np.float64).eps:
            return None
        return float(mapped[0] / mapped[3]), float(mapped[1] / mapped[3])

    def _orientation_canvas_positions(
        self,
    ) -> tuple[tuple[str, float, float], ...]:
        if (
            self._view is None
            or self._volume_shape is None
            or self._volume_affine is None
        ):
            return ()
        labels, world_positions = orientation_label_world_positions(
            self._volume_shape,
            self._volume_affine,
        )
        projected: list[tuple[str, float, float]] = []
        for label, world_position in zip(labels, world_positions, strict=True):
            canvas_position = self._world_canvas_position(world_position)
            if canvas_position is not None:
                projected.append(
                    (label, canvas_position[0], canvas_position[1])
                )
        return tuple(projected)

    def _orientation_widget_axes(
        self,
    ) -> tuple[tuple[str, float, float], ...]:
        if (
            self._view is None
            or self._volume_shape is None
            or self._volume_affine is None
        ):
            return ()
        limits = _volume_world_limits(
            self._volume_shape,
            self._volume_affine,
        )
        world_center = np.asarray(
            [
                (minimum + maximum) / 2.0
                for minimum, maximum in limits
            ],
            dtype=np.float64,
        )
        center_canvas = self._world_canvas_position(world_center)
        if center_canvas is None:
            return ()
        world_span = max(
            maximum - minimum
            for minimum, maximum in limits
        )
        axis_step = max(float(world_span) * 0.12, 1.0e-3)
        projected_axes: list[tuple[str, float, float]] = []
        for axis, label in enumerate(("R", "A", "S")):
            endpoint = world_center.copy()
            endpoint[axis] += axis_step
            endpoint_canvas = self._world_canvas_position(endpoint)
            if endpoint_canvas is None:
                continue
            projected_axes.append(
                (
                    label,
                    endpoint_canvas[0] - center_canvas[0],
                    endpoint_canvas[1] - center_canvas[1],
                )
            )
        if not projected_axes:
            return ()
        maximum_length = max(
            float(np.hypot(direction_x, direction_y))
            for _label, direction_x, direction_y in projected_axes
        )
        if maximum_length <= 1.0e-6:
            return tuple(
                (label, 0.0, 0.0)
                for label, _direction_x, _direction_y in projected_axes
            )
        return tuple(
            (
                label,
                direction_x / maximum_length,
                direction_y / maximum_length,
            )
            for label, direction_x, direction_y in projected_axes
        )

    def _on_scene_transform_changed(self, _event: object = None) -> None:
        self._refresh_cursor_overlay()

    def _refresh_orientation_overlay(self) -> None:
        self._refresh_cursor_overlay()

    def _refresh_locator_visual(self) -> None:
        if self._view is None:
            return
        for name in ("_locator_visual", "_source_box_visual"):
            visual = getattr(self, name)
            if visual is not None:
                visual.parent = None
                setattr(self, name, None)
        if not self._locator_visible:
            self._request_canvas_update()
            return
        from vispy import scene
        if self._locator_volume is not None:
            from vispy.visuals.transforms import MatrixTransform

            locator = prepare_render(
                self._locator_volume,
                kind="image",
                render_mode="MIP",
                threshold=0.0,
                maximum_dimension=128,
            )
            self._locator_visual = scene.visuals.Volume(
                locator.data,
                method="mip",
                clim=(0, 255),
                cmap=_volume_colormap((170, 170, 170), 0.18),
                parent=self._view.scene,
            )
            transform = MatrixTransform()
            transform.matrix = np.asarray(locator.texture_affine).T
            self._locator_visual.transform = transform
        source_shape = (
            tuple(int(value) for value in self._locator_volume.shape)
            if self._locator_volume is not None
            else self._locator_source_shape
        )
        source_affine = (
            self._locator_volume.affine
            if self._locator_volume is not None
            else self._locator_source_affine
        )
        if source_shape is not None and source_affine is not None:
            source_segments = source_box_world_segments(
                source_shape,
                source_affine,
            )
            self._source_box_visual = scene.visuals.Line(
                pos=source_segments,
                connect="segments",
                color=(0.55, 0.55, 0.55, 0.8),
                width=1.0,
                parent=self._view.scene,
            )
        self.reset_camera()

    def _sync_panel_sources(self) -> None:
        if self._panel is None:
            return
        self._panel.set_sources(
            [
                (source.id, source.display_name)
                for source in self.state.sources.values()
            ],
            self.state.selected_source_id,
        )

    def _sync_panel_settings(self) -> None:
        if self._panel is None:
            return
        source = self.state.selected_source()
        settings = self.state.selected_settings()
        if source is None or settings is None:
            self._panel.set_status("Load an image before rendering.")
            self._panel.set_render_controls_enabled(False)
            return
        modes = RAW_RENDER_MODES if source.kind == "image" else SEGMENTATION_RENDER_MODES
        self._panel.set_modes(modes, settings.render_mode)
        self._panel.set_settings(settings)
        self._panel.set_render_controls_enabled(self.state.active)

    def _set_error(self, message: str) -> None:
        self.state.last_error = str(message)
        if self._panel is not None:
            self._panel.set_status(str(message))
        self.placeholder.setText(str(message))
        self.render_failed.emit(str(message))
        self._emit_state()

    def _cancel_pending_preparation(self, message: str) -> None:
        self._job_token += 1
        self.state.busy = False
        if self._panel is not None:
            self._panel.set_busy(False)
            self._panel.set_status(message)

    def _emit_state(self) -> None:
        self.state_changed.emit(self.status())

    def _request_canvas_update(self) -> None:
        if self._canvas is not None:
            self._canvas.update()


def _rgba(
    colour: tuple[int, int, int],
    opacity: float,
) -> tuple[float, float, float, float]:
    return (
        colour[0] / 255.0,
        colour[1] / 255.0,
        colour[2] / 255.0,
        min(max(float(opacity), 0.0), 1.0),
    )


def _volume_world_limits(
    shape: tuple[int, int, int],
    affine: np.ndarray,
) -> tuple[
    tuple[float, float],
    tuple[float, float],
    tuple[float, float],
]:
    return _point_world_limits(source_box_world_segments(shape, affine))


def _point_world_limits(
    points: np.ndarray,
) -> tuple[
    tuple[float, float],
    tuple[float, float],
    tuple[float, float],
]:
    coordinates = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    minimum = np.min(coordinates, axis=0)
    maximum = np.max(coordinates, axis=0)
    return tuple(
        (float(minimum[axis]), float(maximum[axis]))
        for axis in range(3)
    )


def _pan_camera_with_middle_drag(camera: Any, event: Any) -> bool:
    """Translate a VisPy turntable camera during an unmodified middle drag."""
    if (
        event.type != "mouse_move"
        or event.press_event is None
        or 3 not in event.buttons
        or event.mouse_event.modifiers
    ):
        return False

    press_position = np.asarray(event.mouse_event.press_event.pos, dtype=np.float64)
    current_position = np.asarray(event.mouse_event.pos, dtype=np.float64)
    view_size = np.asarray(camera._viewbox.size, dtype=np.float64)
    normalization = float(np.mean(view_size))
    if normalization <= 0.0:
        return False
    event_value = camera._event_value
    if event_value is None or np.asarray(event_value).shape != (3,):
        camera._event_value = tuple(float(value) for value in camera.center)

    distance = (press_position - current_position) / normalization
    distance *= float(camera._scale_factor)
    distance[1] *= -1.0
    delta_x, delta_y, delta_z = camera._dist_to_trans(distance)
    flip_factors = camera._flip_factors
    up, forward, right = camera._get_dim_vectors()
    delta_x, delta_y, delta_z = (
        right * delta_x + forward * delta_y + up * delta_z
    )
    delta_x = flip_factors[0] * delta_x
    delta_y = flip_factors[1] * delta_y
    delta_z = flip_factors[2] * delta_z
    start_x, start_y, start_z = camera._event_value
    camera.center = (
        start_x + delta_x,
        start_y + delta_y,
        start_z + delta_z,
    )
    event.handled = True
    return True


def _require_pyopengl_3d_textures() -> None:
    """Fail before VisPy's deferred draw when 3D texture support is absent."""
    try:
        import OpenGL.GL  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "PyOpenGL is required for raw-image 3D rendering. "
            "Reinstall MipView dependencies or run "
            "`python -m pip install PyOpenGL` in the active environment."
        ) from exc


def _volume_colormap(
    colour: tuple[int, int, int],
    opacity: float,
    *,
    translucent: bool = False,
    cutoff: float = 0.0,
) -> Any:
    from vispy.color import Colormap

    red, green, blue, alpha = _rgba(colour, opacity)
    if translucent:
        # Straight alpha accumulation makes a long run of dim background
        # samples turn opaque before a ray reaches useful anatomy. Keep the
        # selected lower threshold transparent and ramp opacity slowly above it.
        lower = min(max(float(cutoff), 0.0), 0.98)
        middle = lower + (1.0 - lower) * 0.65
        if lower <= 0.0:
            return Colormap(
                [
                    (0.0, 0.0, 0.0, 0.0),
                    (red * middle, green * middle, blue * middle, alpha * 0.02),
                    (red, green, blue, alpha * 0.25),
                ],
                controls=[0.0, middle, 1.0],
            )
        return Colormap(
            [
                (0.0, 0.0, 0.0, 0.0),
                (0.0, 0.0, 0.0, 0.0),
                (red * middle, green * middle, blue * middle, alpha * 0.02),
                (red, green, blue, alpha * 0.25),
            ],
            controls=[0.0, lower, middle, 1.0],
        )
    return Colormap(
        [
            (0.0, 0.0, 0.0, 0.0),
            (red, green, blue, alpha),
        ]
    )


def _normalized_threshold(
    threshold: float,
    source_range: tuple[float, float],
) -> float:
    minimum, maximum = source_range
    if maximum <= minimum:
        return 0.5
    return min(max((float(threshold) - minimum) / (maximum - minimum), 0.0), 1.0)
