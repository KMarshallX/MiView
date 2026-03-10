from __future__ import annotations

import logging
import os

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QGridLayout, QWidget

from miview.state.cursor_state import CursorState
from miview.state.zoom_state import ZoomState
from miview.io.nifti_loader import NiftiLoadResult
from miview.patch.selector import (
    DEFAULT_PATCH_SIZE,
    PatchBounds,
    PatchSelector,
    orientation_slice_intersects_bounds,
    project_bounds_to_orientation,
    source_bounds_to_display_bounds,
)
from miview.viewer.oriented_volume import OrientedVolume, build_oriented_volume
from miview.viewer.slice_geometry import (
    center_cursor_for_volume,
    compute_shared_base_scale,
    plane_axes_for_orientation,
    plane_shape_for_orientation,
)
from miview.viewer.slice_viewer_widget import SliceViewerWidget

LOGGER = logging.getLogger(__name__)


class TriPlanarViewerWidget(QWidget):
    """Minimal tri-planar viewer with a shared logical cursor."""

    cursor_inspection_changed = Signal(object, object, object, object)
    patch_selection_changed = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._display_volume: OrientedVolume | None = None
        self._contrast_window: tuple[float, float] | None = None
        self._patch_debug_enabled = os.getenv("MIVIEW_PATCH_DEBUG", "").lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        self.cursor_state = CursorState(self)
        self.zoom_state = ZoomState(self)
        self.patch_selector = PatchSelector(DEFAULT_PATCH_SIZE)

        self.axial_view = SliceViewerWidget("axial", self)
        self.coronal_view = SliceViewerWidget("coronal", self)
        self.sagittal_view = SliceViewerWidget("sagittal", self)
        self._views = (
            self.axial_view,
            self.coronal_view,
            self.sagittal_view,
        )

        for view in self._views:
            view.cursor_position_selected.connect(self._on_cursor_selected)
            view.patch_center_position_selected.connect(self._on_patch_center_selected)
            view.zoom_factor_requested.connect(self.zoom_state.set_zoom_factor)
            view.patch_axis_size_requested.connect(self._on_patch_axis_size_requested)
            view.viewport_resized.connect(self._update_shared_base_scale)
        self.cursor_state.cursor_changed.connect(self._on_cursor_changed)
        self.zoom_state.zoom_changed.connect(self._on_zoom_changed)

        layout = QGridLayout(self)
        layout.addWidget(self.axial_view, 0, 0)
        layout.addWidget(self.coronal_view, 0, 1)
        layout.addWidget(self.sagittal_view, 0, 2)
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(2, 1)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

    def load_volume(self, volume: NiftiLoadResult) -> None:
        if volume.data.ndim != 3:
            raise ValueError(
                f"Tri-planar viewer expects a 3D volume, got {volume.data.ndim}D."
            )

        self._display_volume = build_oriented_volume(volume.data, volume.affine)
        self.cursor_state.set_volume_shape(self._display_volume.source_shape)
        self.patch_selector.set_volume_shape(self._display_volume.source_shape)
        for view in self._views:
            view.load_volume(self._display_volume)
            if self._contrast_window is not None:
                view.set_contrast_window(
                    self._contrast_window[0], self._contrast_window[1]
                )

        self._update_shared_base_scale()
        self.zoom_state.set_zoom_factor(1.0)
        initial_center = center_cursor_for_volume(self._display_volume.source_shape)
        self.patch_selector.set_center(initial_center)
        self.cursor_state.set_cursor_position(initial_center)

    def unload_volume(self) -> None:
        self._display_volume = None
        self.cursor_state.clear()
        self.zoom_state.set_zoom_factor(1.0)
        self.patch_selector.clear()
        for view in self._views:
            view.unload_volume()
            view.set_patch_overlay(
                False,
                None,
                self.patch_selector.opacity(),
                self.patch_selector.size_xyz(),
                None,
            )
        self.patch_selection_changed.emit(None)

    def current_cursor_position(self) -> tuple[int, int, int] | None:
        return self.cursor_state.cursor_position()

    def set_cursor_overlay_visible(self, visible: bool) -> None:
        for view in self._views:
            view.set_cursor_overlay_visible(visible)

    def set_patch_selection_enabled(self, enabled: bool) -> None:
        if enabled and self.cursor_state.cursor_position() is not None:
            self.patch_selector.set_center(self.cursor_state.cursor_position())
        self.patch_selector.set_enabled(enabled)
        self._update_patch_overlays()

    def patch_selection_enabled(self) -> bool:
        return self.patch_selector.enabled()

    def set_patch_overlay_opacity(self, opacity: float) -> None:
        self.patch_selector.set_opacity(opacity)
        self._update_patch_overlays()

    def patch_overlay_opacity(self) -> float:
        return self.patch_selector.opacity()

    def patch_size_xyz(self) -> tuple[int, int, int]:
        return self.patch_selector.size_xyz()

    def current_patch_bounds(self) -> PatchBounds | None:
        return self.patch_selector.current_bounds()

    def set_contrast_window(self, window_min: float, window_max: float) -> None:
        if window_max < window_min:
            window_min, window_max = window_max, window_min
        self._contrast_window = (window_min, window_max)
        for view in self._views:
            view.set_contrast_window(window_min, window_max)

    def _on_cursor_selected(self, x: int, y: int, z: int) -> None:
        self.cursor_state.set_cursor_position((x, y, z))

    def _on_cursor_changed(self, x: int, y: int, z: int) -> None:
        if self._display_volume is None:
            return

        cursor_position = (x, y, z)
        for view in self._views:
            view.set_cursor_position(cursor_position)

        intensity = self._display_volume.source_data[x, y, z].item()
        self.cursor_inspection_changed.emit(x, y, z, intensity)
        self._update_patch_overlays()

    def _on_patch_center_selected(self, x: int, y: int, z: int) -> None:
        self.patch_selector.set_center((x, y, z))
        self._update_patch_overlays()

    def _on_zoom_changed(self, zoom_factor: float) -> None:
        for view in self._views:
            view.set_zoom_factor(zoom_factor)

    def _update_shared_base_scale(self) -> None:
        if self._display_volume is None:
            return

        plane_sizes = [
            plane_shape_for_orientation(self._display_volume.display_shape, view.orientation)
            for view in self._views
        ]
        viewport_sizes = [view.viewport_size() for view in self._views]
        base_scale = compute_shared_base_scale(plane_sizes, viewport_sizes)
        for view in self._views:
            view.set_base_scale(base_scale)

    def _on_patch_axis_size_requested(self, axis: int, new_size: int) -> None:
        if not self.patch_selector.enabled():
            return
        if self.patch_selector.set_size_axis(axis, new_size):
            self._update_patch_overlays()

    def _update_patch_overlays(self) -> None:
        bounds = self.patch_selector.current_bounds()
        enabled = self.patch_selector.enabled()
        opacity = self.patch_selector.opacity()
        size_xyz = self.patch_selector.size_xyz()

        if self._display_volume is None or bounds is None:
            for view in self._views:
                view.set_patch_overlay(False, None, opacity, size_xyz, None)
            self.patch_selection_changed.emit(None)
            return

        display_bounds = source_bounds_to_display_bounds(bounds, self._display_volume)
        source_cursor = self.cursor_state.cursor_position()
        source_patch_center = self.patch_selector.center()
        if source_cursor is None or source_patch_center is None:
            for view in self._views:
                view.set_patch_overlay(False, None, opacity, size_xyz, None)
            self.patch_selection_changed.emit(None)
            return
        display_cursor = self._display_volume.source_to_display(source_cursor)
        for view in self._views:
            visible_in_view = (
                enabled
                and orientation_slice_intersects_bounds(
                    display_bounds, view.orientation, display_cursor
                )
            )
            plane_bounds = (
                project_bounds_to_orientation(
                    display_bounds,
                    view.orientation,
                    self._display_volume.display_shape,
                )
                if visible_in_view
                else None
            )
            view.set_patch_overlay(
                visible_in_view,
                plane_bounds,
                opacity,
                size_xyz,
                source_patch_center,
            )

        if self._patch_debug_enabled and enabled:
            LOGGER.warning(
                "Patch debug: center=(%d, %d, %d) bounds=(%d:%d, %d:%d, %d:%d)",
                source_patch_center[0],
                source_patch_center[1],
                source_patch_center[2],
                bounds.x_start,
                bounds.x_end,
                bounds.y_start,
                bounds.y_end,
                bounds.z_start,
                bounds.z_end,
            )
            for view in self._views:
                visible_in_view = orientation_slice_intersects_bounds(
                    display_bounds, view.orientation, display_cursor
                )
                if not visible_in_view:
                    _, _, fixed_axis = plane_axes_for_orientation(view.orientation)
                    LOGGER.warning(
                        "Patch debug [%s]: hidden at slice index=%d",
                        view.orientation,
                        display_cursor[fixed_axis],
                    )
                    continue
                plane_bounds = project_bounds_to_orientation(
                    display_bounds,
                    view.orientation,
                    self._display_volume.display_shape,
                )
                LOGGER.warning(
                    "Patch debug [%s]: rect h=(%d:%d) v=(%d:%d)",
                    view.orientation,
                    plane_bounds.horizontal_start,
                    plane_bounds.horizontal_end,
                    plane_bounds.vertical_start,
                    plane_bounds.vertical_end,
                )

        self.patch_selection_changed.emit(bounds if enabled else None)
