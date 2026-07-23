from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from mipview.io.nifti_io import NiftiLoadResult
from mipview.patch.selector import PatchBounds
from mipview.ui.volume_3d_panel import Volume3DPanel
from mipview.viewer.render_3d_preparation import (
    PreparedRender3D,
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
            self._view.camera.set_range()
            self._request_canvas_update()

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
        self._view.camera = scene.cameras.TurntableCamera(
            fov=45.0,
            up="+z",
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
        for name in ("_patch_visual", "_source_box_visual", "_locator_visual"):
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
