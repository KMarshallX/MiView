from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from mipview.annotation import (
    create_empty_annotation_mask,
    erase_stroke,
    paint_stroke,
    save_annotation_mask,
)
from mipview.control.result import CommandResult
from mipview.patch.extractor import extract_patch
from mipview.patch.saver import save_patch_nifti
from mipview.patch.selector import PatchBounds
from mipview.viewer.slice_geometry import Orientation


SUPPORTED_ORIENTATIONS: set[str] = {"axial", "coronal", "sagittal"}
SUPPORTED_PROJECTION_MODES: set[str] = {"MIP", "MINIP"}


class MipViewController:
    """Stable internal API for command-layer access to a running MipView window."""

    def __init__(self, main_window: Any) -> None:
        self.main_window = main_window

    def get_status(self) -> CommandResult:
        state = self.main_window.state
        image_loaded = state.volume is not None
        return CommandResult(
            True,
            "Status exported.",
            {
                "image_loaded": image_loaded,
                "loaded_image_path": _path_to_string(state.loaded_file_path),
                "image_shape": _shape_to_list(state.volume.shape if image_loaded else None),
                "cursor": _tuple_to_list(self.main_window.slice_viewer.current_cursor_position()),
                "patch_selection_enabled": bool(
                    self.main_window.slice_viewer.patch_selection_enabled()
                ),
                "annotation_active": state.annotation.active_mask is not None,
                "annotation_editing_enabled": bool(state.annotation.editing_enabled),
                "num_segmentations": len(state.loaded_segmentations),
            },
        )

    def export_viewer_state(self) -> CommandResult:
        state = self.main_window.state
        volume = state.volume
        slice_viewer = self.main_window.slice_viewer
        patch_bounds = slice_viewer.current_patch_bounds()
        active_segmentation = self._active_segmentation()
        annotation = state.annotation

        data: dict[str, Any] = {
            "loaded_image_path": _path_to_string(state.loaded_file_path),
            "image_shape": _shape_to_list(volume.shape if volume is not None else None),
            "voxel_spacing": _voxel_spacing(volume),
            "cursor": _tuple_to_list(slice_viewer.current_cursor_position()),
            "active_view": _active_view(slice_viewer),
            "slice_indices": _slice_indices(slice_viewer),
            "patch": {
                "center": _tuple_to_list(slice_viewer.current_patch_center()),
                "size": _tuple_to_list(slice_viewer.patch_size_xyz()),
                "bounds": _patch_bounds_to_dict(patch_bounds),
                "selection_enabled": bool(slice_viewer.patch_selection_enabled()),
            },
            "projection_mode": _projection_mode(slice_viewer),
            "segmentation": (
                None
                if active_segmentation is None
                else {
                    "id": active_segmentation.id,
                    "name": active_segmentation.display_name,
                    "kind": active_segmentation.kind,
                    "path": _path_to_string(active_segmentation.path),
                    "opacity": float(state.segmentation_opacity),
                }
            ),
            "annotation": {
                "active": annotation.active_mask is not None,
                "editing_enabled": bool(annotation.editing_enabled),
                "active_label": int(annotation.active_label),
                "visible": bool(annotation.visible),
                "opacity": float(annotation.opacity),
                "brush_radius": int(annotation.brush_radius),
                "brush_mode": annotation.brush_mode,
            },
        }
        if volume is not None:
            data["affine"] = np.asarray(volume.affine, dtype=float).tolist()

        return CommandResult(True, "Viewer state exported.", data)

    def move_cursor(self, x: int, y: int, z: int) -> CommandResult:
        shape_result = self._loaded_shape()
        if not shape_result.ok:
            return shape_result

        cursor = (int(x), int(y), int(z))
        shape = shape_result.data["shape"]
        invalid = _first_out_of_bounds_axis(cursor, shape)
        if invalid is not None:
            return CommandResult(
                False,
                f"Cursor coordinate {cursor} is outside image shape {shape}.",
            )

        self.main_window.slice_viewer.cursor_state.set_cursor_position(cursor)
        return CommandResult(True, "Cursor moved.", {"cursor": list(cursor)})

    def set_patch_size(self, sx: int, sy: int, sz: int) -> CommandResult:
        shape_result = self._loaded_shape()
        if not shape_result.ok:
            return shape_result

        size = (int(sx), int(sy), int(sz))
        if any(axis_size <= 0 for axis_size in size):
            return CommandResult(False, f"Patch size values must be positive, got {size}.")

        self.main_window.slice_viewer.set_patch_size_xyz(size)
        self._refresh_patch_selection_ui()
        return self._patch_result("Patch size updated.")

    def set_patch_center(self, x: int, y: int, z: int) -> CommandResult:
        shape_result = self._loaded_shape()
        if not shape_result.ok:
            return shape_result

        center = (int(x), int(y), int(z))
        shape = shape_result.data["shape"]
        invalid = _first_out_of_bounds_axis(center, shape)
        if invalid is not None:
            return CommandResult(
                False,
                f"Patch center {center} is outside image shape {shape}.",
            )

        self.main_window.slice_viewer.patch_selector.set_center(center)
        self.main_window.slice_viewer._update_patch_overlays()
        self._refresh_patch_selection_ui()
        return self._patch_result("Patch center updated.")

    def select_patch(self) -> CommandResult:
        if self.main_window.state.volume is None:
            return CommandResult(False, "No image is currently loaded.")

        bounds = self.main_window.slice_viewer.current_patch_bounds()
        if bounds is None:
            return CommandResult(False, "No patch is currently available to select.")

        extracted = extract_patch(self.main_window.state.volume, bounds)
        self.main_window.state.selected_patch_bounds = bounds
        self.main_window.state.selected_patch_data = extracted
        return CommandResult(
            True,
            "Patch selected.",
            {
                "bounds": _patch_bounds_to_dict(bounds),
                "shape": list(extracted.shape),
            },
        )

    def save_patch(self, path: str) -> CommandResult:
        selected_patch = self.main_window.state.selected_patch_data
        if selected_patch is None:
            selected = self.select_patch()
            if not selected.ok:
                return selected
            selected_patch = self.main_window.state.selected_patch_data
        if selected_patch is None:
            return CommandResult(False, "No selected patch data is available.")

        try:
            saved_path = save_patch_nifti(selected_patch, path)
        except (OSError, ValueError) as exc:
            return CommandResult(False, f"Patch save failed: {exc}")
        return CommandResult(True, "Patch saved.", {"path": str(saved_path)})

    def set_projection_mode(self, mode: str) -> CommandResult:
        normalized_mode = mode.strip().upper()
        if normalized_mode == "MINIP":
            normalized_mode = "MINIP"
        if normalized_mode not in SUPPORTED_PROJECTION_MODES:
            return CommandResult(
                False,
                "Projection mode must be 'MIP' or 'MinIP'.",
            )

        self.main_window.slice_viewer.set_projection_mode(normalized_mode)
        return CommandResult(
            True,
            "Projection mode updated.",
            {"mode": normalized_mode},
        )

    def save_projection(self, view: str, path: str) -> CommandResult:
        return CommandResult(
            False,
            "Projection saving is not implemented in Milestone 2.",
            {"view": view, "path": path},
        )

    def capture_screenshot(self, path: str | None = None) -> CommandResult:
        return CommandResult(
            False,
            "Screenshot capture is not implemented in Milestone 2.",
            {"path": path},
        )

    def create_annotation(self, label: int = 1) -> CommandResult:
        state = self.main_window.state
        if state.volume is None:
            return CommandResult(False, "No image is currently loaded.")

        active_label = max(int(label), 1)
        created_new_mask = state.annotation.active_mask is None
        if created_new_mask:
            state.annotation.active_mask = create_empty_annotation_mask(state.volume)
            state.annotation.undo_stack.clear()

        state.annotation.active_label = active_label
        state.annotation.editing_enabled = True
        self.main_window.slice_viewer.set_annotation_overlay(
            state.annotation.active_mask,
            opacity=state.annotation.opacity,
            visible=state.annotation.visible,
            active_label=state.annotation.active_label,
            undo_stack=state.annotation.undo_stack,
        )
        self._call_if_present("_register_annotation_as_segmentation")
        self._call_if_present("_sync_annotation_brush_settings")
        self._call_if_present("_refresh_annotation_ui")
        self._call_if_present("_update_patch_windows_annotation_for_current_image")
        return CommandResult(
            True,
            "Annotation created." if created_new_mask else "Annotation mode enabled.",
            {
                "created": created_new_mask,
                "active_label": state.annotation.active_label,
                "shape": list(state.annotation.active_mask.shape),
            },
        )

    def paint_annotation_stroke(
        self,
        points: list[list[int]],
        radius: int,
        label: int,
        view: str | None = None,
    ) -> CommandResult:
        return self._apply_annotation_stroke(
            operation="paint",
            points=points,
            radius=radius,
            label=label,
            view=view,
        )

    def erase_annotation_stroke(
        self,
        points: list[list[int]],
        radius: int,
        view: str | None = None,
    ) -> CommandResult:
        return self._apply_annotation_stroke(
            operation="erase",
            points=points,
            radius=radius,
            label=None,
            view=view,
        )

    def save_annotation(self, path: str) -> CommandResult:
        annotation_mask = self.main_window.state.annotation.active_mask
        if annotation_mask is None:
            return CommandResult(False, "No annotation mask is currently active.")

        try:
            saved_path = save_annotation_mask(annotation_mask, path, overwrite=True)
        except (FileExistsError, OSError, ValueError) as exc:
            return CommandResult(False, f"Annotation save failed: {exc}")
        return CommandResult(True, "Annotation saved.", {"path": str(saved_path)})

    def _apply_annotation_stroke(
        self,
        *,
        operation: str,
        points: list[list[int]],
        radius: int,
        label: int | None,
        view: str | None,
    ) -> CommandResult:
        annotation_mask = self.main_window.state.annotation.active_mask
        if annotation_mask is None:
            return CommandResult(False, "No annotation mask is currently active.")

        orientation = _validate_orientation(view)
        if orientation is None:
            return CommandResult(False, "Annotation stroke requires explicit view.")

        stroke_points = [tuple(int(index) for index in point) for point in points]
        try:
            if operation == "erase":
                changed = erase_stroke(annotation_mask, orientation, stroke_points, int(radius))
            else:
                changed = paint_stroke(
                    annotation_mask,
                    orientation,
                    stroke_points,
                    int(radius),
                    int(label if label is not None else 1),
                )
        except (TypeError, ValueError) as exc:
            return CommandResult(False, f"Annotation stroke failed: {exc}")

        if changed > 0:
            self.main_window.slice_viewer.refresh_annotation_overlay()
            if hasattr(self.main_window, "_on_annotation_changed"):
                self.main_window._on_annotation_changed(changed)
        return CommandResult(
            True,
            "Annotation stroke applied.",
            {
                "operation": operation,
                "view": orientation,
                "radius": int(radius),
                "label": None if label is None else int(label),
                "num_voxels_modified": int(changed),
            },
        )

    def _loaded_shape(self) -> CommandResult:
        volume = self.main_window.state.volume
        if volume is None:
            return CommandResult(False, "No image is currently loaded.")
        if len(volume.shape) != 3:
            return CommandResult(False, f"Loaded image is not 3D: shape={volume.shape}.")
        return CommandResult(True, "Image shape available.", {"shape": tuple(volume.shape)})

    def _patch_result(self, message: str) -> CommandResult:
        bounds = self.main_window.slice_viewer.current_patch_bounds()
        return CommandResult(
            True,
            message,
            {
                "center": _tuple_to_list(self.main_window.slice_viewer.current_patch_center()),
                "size": _tuple_to_list(self.main_window.slice_viewer.patch_size_xyz()),
                "bounds": _patch_bounds_to_dict(bounds),
            },
        )

    def _active_segmentation(self) -> Any | None:
        if hasattr(self.main_window, "_active_segmentation"):
            return self.main_window._active_segmentation()
        active_id = self.main_window.state.active_segmentation_id
        if active_id is None:
            return None
        for segmentation in self.main_window.state.loaded_segmentations:
            if segmentation.id == active_id:
                return segmentation
        return None

    def _refresh_patch_selection_ui(self) -> None:
        self._call_if_present("_refresh_patch_selection_ui")

    def _call_if_present(self, method_name: str) -> None:
        method = getattr(self.main_window, method_name, None)
        if callable(method):
            method()


def _tuple_to_list(value: tuple[int, ...] | None) -> list[int] | None:
    if value is None:
        return None
    return [int(item) for item in value]


def _shape_to_list(value: tuple[int, ...] | None) -> list[int] | None:
    return _tuple_to_list(value)


def _path_to_string(path: str | Path | None) -> str | None:
    if path is None:
        return None
    return str(path)


def _voxel_spacing(volume: Any | None) -> list[float] | None:
    if volume is None:
        return None
    return [float(value) for value in volume.header.get_zooms()[:3]]


def _patch_bounds_to_dict(bounds: PatchBounds | None) -> dict[str, list[int]] | None:
    if bounds is None:
        return None
    return {
        "x": [int(bounds.x_start), int(bounds.x_end)],
        "y": [int(bounds.y_start), int(bounds.y_end)],
        "z": [int(bounds.z_start), int(bounds.z_end)],
    }


def _projection_mode(slice_viewer: Any) -> str | None:
    mode = getattr(slice_viewer, "_projection_mode", None)
    if mode is None:
        return None
    return str(mode)


def _active_view(slice_viewer: Any) -> str | None:
    active_view_method = getattr(slice_viewer, "active_view", None)
    if not callable(active_view_method):
        return None
    value = active_view_method()
    if value is None:
        return None
    return str(value)


def _slice_indices(slice_viewer: Any) -> dict[str, int] | None:
    indices_method = getattr(slice_viewer, "current_slice_indices", None)
    if not callable(indices_method):
        return None
    value = indices_method()
    if value is None:
        return None
    return {str(key): int(index) for key, index in value.items()}


def _first_out_of_bounds_axis(
    voxel: tuple[int, int, int],
    shape: tuple[int, int, int],
) -> int | None:
    for axis, index in enumerate(voxel):
        if index < 0 or index >= shape[axis]:
            return axis
    return None


def _validate_orientation(view: str | None) -> Orientation | None:
    if view is None:
        return None
    normalized = view.strip().lower()
    if normalized not in SUPPORTED_ORIENTATIONS:
        return None
    return normalized  # type: ignore[return-value]
