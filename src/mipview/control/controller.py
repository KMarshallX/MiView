from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtGui import QImage

from mipview.annotation import (
    create_empty_annotation_mask,
    erase_stroke,
    paint_stroke,
    save_annotation_mask,
)
from mipview.annotation.annotation_overlay import build_annotation_overlay_rgba
from mipview.control.result import CommandResult
from mipview.patch.extractor import extract_patch
from mipview.patch.saver import save_patch_nifti
from mipview.patch.selector import PatchBounds
from mipview.viewer.intensity import normalize_slice_to_uint8
from mipview.viewer.oriented_volume import build_oriented_volume
from mipview.viewer.slice_geometry import Orientation
from mipview.viewer.slice_geometry import project_oriented_volume


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
                "num_graph_sessions": len(self.main_window.graph_session_summaries()),
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
            "graph_sessions": self.main_window.graph_session_summaries(),
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

    def export_raw_patch(self, path: str) -> CommandResult:
        if path is None or not str(path).strip():
            return CommandResult(False, "Raw patch export path is required.")

        output_path = Path(path)
        if output_path.suffix.lower() != ".npz":
            return CommandResult(False, "Raw patch export path must end with .npz.")

        parent = output_path.parent
        if not parent.exists():
            return CommandResult(
                False,
                f"Raw patch export directory does not exist: {parent}",
                {"path": str(output_path)},
            )
        if not parent.is_dir():
            return CommandResult(
                False,
                f"Raw patch export parent path is not a directory: {parent}",
                {"path": str(output_path)},
            )
        if not os.access(parent, os.W_OK):
            return CommandResult(
                False,
                f"Raw patch export directory is not writable: {parent}",
                {"path": str(output_path)},
            )

        selected_patch = self.main_window.state.selected_patch_data
        selected_bounds = self.main_window.state.selected_patch_bounds
        if selected_patch is None or selected_bounds is None:
            selected = self.select_patch()
            if not selected.ok:
                return selected
            selected_patch = self.main_window.state.selected_patch_data
            selected_bounds = self.main_window.state.selected_patch_bounds
        if selected_patch is None or selected_bounds is None:
            return CommandResult(False, "No selected patch data is available.")

        arrays: dict[str, Any] = {
            "image_patch": np.asarray(selected_patch.data),
            "bounds": _patch_bounds_to_array(selected_bounds),
            "patch_size": np.asarray(
                self.main_window.slice_viewer.patch_size_xyz(),
                dtype=np.int64,
            ),
            "patch_center": _tuple_to_array(
                self.main_window.slice_viewer.current_patch_center()
            ),
            "affine": np.asarray(selected_patch.affine, dtype=np.float64),
            "voxel_spacing": np.asarray(_voxel_spacing(selected_patch), dtype=np.float64),
            "source_image_path": np.asarray(
                _path_to_string(self.main_window.state.loaded_file_path) or ""
            ),
            "viewer_state_json": np.asarray(
                json.dumps(self.export_viewer_state().data, sort_keys=True)
            ),
        }

        annotation_included = False
        annotation_mask = self.main_window.state.annotation.active_mask
        if annotation_mask is not None:
            annotation_patch = extract_patch(annotation_mask, selected_bounds)
            arrays["annotation_patch"] = np.asarray(annotation_patch.data)
            annotation_included = True

        segmentation_included = False
        active_segmentation = self._active_segmentation()
        if active_segmentation is not None and active_segmentation.kind == "file":
            segmentation_patch = extract_patch(active_segmentation.volume, selected_bounds)
            arrays["segmentation_patch"] = np.asarray(segmentation_patch.data)
            segmentation_included = True

        try:
            np.savez_compressed(output_path, **arrays)
        except (OSError, ValueError) as exc:
            return CommandResult(False, f"Raw patch export failed: {exc}")

        return CommandResult(
            True,
            "Raw patch exported.",
            {
                "path": str(output_path),
                "bounds": _patch_bounds_to_dict(selected_bounds),
                "shape": list(selected_patch.shape),
                "annotation_included": annotation_included,
                "segmentation_included": segmentation_included,
            },
        )

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

    def get_graph_status(self, session_id: str) -> CommandResult:
        patch_window = self._graph_patch_window(session_id)
        if patch_window is None:
            return self._graph_session_not_found(session_id)
        return CommandResult(
            True,
            "Graph session exported.",
            patch_window.graph_status(),
        )

    def set_graph_active(self, session_id: str, enabled: bool) -> CommandResult:
        patch_window = self._graph_patch_window(session_id)
        if patch_window is None:
            return self._graph_session_not_found(session_id)
        try:
            patch_window.set_graph_editing_enabled(bool(enabled))
        except ValueError as exc:
            return CommandResult(False, str(exc), {"session_id": session_id})
        return CommandResult(
            True,
            "Graph mode activated." if enabled else "Graph mode exited.",
            patch_window.graph_status(),
        )

    def set_graph_display(
        self,
        session_id: str,
        visible: bool | None = None,
        opacity: float | None = None,
        node_size: int | None = None,
        edge_thickness: int | None = None,
    ) -> CommandResult:
        patch_window = self._graph_patch_window(session_id)
        if patch_window is None:
            return self._graph_session_not_found(session_id)
        if all(
            value is None
            for value in (visible, opacity, node_size, edge_thickness)
        ):
            return CommandResult(False, "At least one graph display option is required.")
        if opacity is not None and not 0.0 <= float(opacity) <= 1.0:
            return CommandResult(False, "Graph opacity must be between 0.0 and 1.0.")
        if node_size is not None and not 1 <= int(node_size) <= 10:
            return CommandResult(False, "Graph node size must be between 1 and 10.")
        if edge_thickness is not None and not 1 <= int(edge_thickness) <= 10:
            return CommandResult(False, "Graph edge thickness must be between 1 and 10.")
        patch_window.set_graph_display_options(
            visible=visible,
            opacity=opacity,
            node_size=node_size,
            edge_thickness=edge_thickness,
        )
        return CommandResult(
            True,
            "Graph display options updated.",
            patch_window.graph_status(),
        )

    def add_graph_node(
        self,
        session_id: str,
        view: str,
        horizontal: int,
        vertical: int,
    ) -> CommandResult:
        patch_window = self._graph_patch_window(session_id)
        if patch_window is None:
            return self._graph_session_not_found(session_id)
        orientation = _validate_orientation(view)
        if orientation is None:
            return CommandResult(False, "Graph view must be axial, coronal, or sagittal.")
        try:
            node = patch_window.add_graph_node(
                orientation,
                int(horizontal),
                int(vertical),
            )
        except ValueError as exc:
            return CommandResult(False, str(exc), {"session_id": session_id})
        return CommandResult(
            True,
            "Graph node created.",
            {
                "session_id": session_id,
                "view": orientation,
                "node": {
                    "id": node.id,
                    "horizontal_index": node.horizontal_index,
                    "vertical_index": node.vertical_index,
                },
            },
        )

    def delete_graph_node(
        self,
        session_id: str,
        view: str,
        node_id: int,
    ) -> CommandResult:
        patch_window = self._graph_patch_window(session_id)
        if patch_window is None:
            return self._graph_session_not_found(session_id)
        orientation = _validate_orientation(view)
        if orientation is None:
            return CommandResult(False, "Graph view must be axial, coronal, or sagittal.")
        try:
            patch_window.delete_graph_node(orientation, int(node_id))
        except ValueError as exc:
            return CommandResult(False, str(exc), {"session_id": session_id})
        return CommandResult(
            True,
            "Graph node deleted.",
            {"session_id": session_id, "view": orientation, "node_id": int(node_id)},
        )

    def add_graph_edge(
        self,
        session_id: str,
        view: str,
        start_node_id: int,
        end_node_id: int,
    ) -> CommandResult:
        return self._mutate_graph_edge(
            session_id,
            view,
            start_node_id,
            end_node_id,
            delete=False,
        )

    def delete_graph_edge(
        self,
        session_id: str,
        view: str,
        start_node_id: int,
        end_node_id: int,
    ) -> CommandResult:
        return self._mutate_graph_edge(
            session_id,
            view,
            start_node_id,
            end_node_id,
            delete=True,
        )

    def curve_graph_edge(
        self,
        session_id: str,
        view: str,
        start_node_id: int,
        end_node_id: int,
        control_horizontal: float,
        control_vertical: float,
    ) -> CommandResult:
        patch_window = self._graph_patch_window(session_id)
        if patch_window is None:
            return self._graph_session_not_found(session_id)
        orientation = _validate_orientation(view)
        if orientation is None:
            return CommandResult(False, "Graph view must be axial, coronal, or sagittal.")
        try:
            edge = patch_window.curve_graph_edge(
                orientation,
                int(start_node_id),
                int(end_node_id),
                float(control_horizontal),
                float(control_vertical),
            )
        except (TypeError, ValueError) as exc:
            return CommandResult(False, str(exc), {"session_id": session_id})
        control = patch_window.graph_state.layer(orientation).curve_control_points[edge]
        return CommandResult(
            True,
            "Graph edge curved.",
            {
                "session_id": session_id,
                "view": orientation,
                "edge": {
                    "start_node_id": edge.start_node_id,
                    "end_node_id": edge.end_node_id,
                    "control_point": [float(control[0]), float(control[1])],
                },
            },
        )

    def straighten_graph_edge(
        self,
        session_id: str,
        view: str,
        start_node_id: int,
        end_node_id: int,
    ) -> CommandResult:
        patch_window = self._graph_patch_window(session_id)
        if patch_window is None:
            return self._graph_session_not_found(session_id)
        orientation = _validate_orientation(view)
        if orientation is None:
            return CommandResult(False, "Graph view must be axial, coronal, or sagittal.")
        try:
            edge = patch_window.straighten_graph_edge(
                orientation,
                int(start_node_id),
                int(end_node_id),
            )
        except (TypeError, ValueError) as exc:
            return CommandResult(False, str(exc), {"session_id": session_id})
        return CommandResult(
            True,
            "Graph edge straightened.",
            {
                "session_id": session_id,
                "view": orientation,
                "edge": {
                    "start_node_id": edge.start_node_id,
                    "end_node_id": edge.end_node_id,
                },
            },
        )

    def split_graph_edge(
        self,
        session_id: str,
        view: str,
        start_node_id: int,
        end_node_id: int,
        horizontal: int,
        vertical: int,
    ) -> CommandResult:
        patch_window = self._graph_patch_window(session_id)
        if patch_window is None:
            return self._graph_session_not_found(session_id)
        orientation = _validate_orientation(view)
        if orientation is None:
            return CommandResult(False, "Graph view must be axial, coronal, or sagittal.")
        try:
            node, first_edge, second_edge = patch_window.split_graph_edge(
                orientation,
                int(start_node_id),
                int(end_node_id),
                int(horizontal),
                int(vertical),
            )
        except (TypeError, ValueError) as exc:
            return CommandResult(False, str(exc), {"session_id": session_id})
        return CommandResult(
            True,
            "Graph edge split with a new node.",
            {
                "session_id": session_id,
                "view": orientation,
                "node": {
                    "id": node.id,
                    "horizontal_index": node.horizontal_index,
                    "vertical_index": node.vertical_index,
                },
                "edges": [
                    {
                        "start_node_id": first_edge.start_node_id,
                        "end_node_id": first_edge.end_node_id,
                    },
                    {
                        "start_node_id": second_edge.start_node_id,
                        "end_node_id": second_edge.end_node_id,
                    },
                ],
            },
        )

    def calculate_graph_angle(
        self,
        session_id: str,
        view: str,
        vector_1_source: int,
        vector_1_target: int,
        vector_2_source: int,
        vector_2_target: int,
    ) -> CommandResult:
        patch_window = self._graph_patch_window(session_id)
        if patch_window is None:
            return self._graph_session_not_found(session_id)
        orientation = _validate_orientation(view)
        if orientation is None:
            return CommandResult(False, "Graph view must be axial, coronal, or sagittal.")
        try:
            angle = patch_window.calculate_graph_angle(
                orientation,
                int(vector_1_source),
                int(vector_1_target),
                int(vector_2_source),
                int(vector_2_target),
            )
        except (TypeError, ValueError) as exc:
            return CommandResult(False, str(exc), {"session_id": session_id})
        return CommandResult(
            True,
            "Graph angle calculated.",
            {
                "session_id": session_id,
                "view": orientation,
                "angle_degrees": float(angle),
                "vector_1": {
                    "source_node_id": int(vector_1_source),
                    "target_node_id": int(vector_1_target),
                },
                "vector_2": {
                    "source_node_id": int(vector_2_source),
                    "target_node_id": int(vector_2_target),
                },
            },
        )

    def clear_graph_angle(self, session_id: str) -> CommandResult:
        patch_window = self._graph_patch_window(session_id)
        if patch_window is None:
            return self._graph_session_not_found(session_id)
        patch_window.clear_graph_angle()
        return CommandResult(
            True,
            "Graph angle cleared.",
            patch_window.graph_status(),
        )

    def _mutate_graph_edge(
        self,
        session_id: str,
        view: str,
        start_node_id: int,
        end_node_id: int,
        *,
        delete: bool,
    ) -> CommandResult:
        patch_window = self._graph_patch_window(session_id)
        if patch_window is None:
            return self._graph_session_not_found(session_id)
        orientation = _validate_orientation(view)
        if orientation is None:
            return CommandResult(False, "Graph view must be axial, coronal, or sagittal.")
        try:
            if delete:
                edge = patch_window.delete_graph_edge(
                    orientation,
                    int(start_node_id),
                    int(end_node_id),
                )
            else:
                edge = patch_window.add_graph_edge(
                    orientation,
                    int(start_node_id),
                    int(end_node_id),
                )
        except ValueError as exc:
            return CommandResult(False, str(exc), {"session_id": session_id})
        return CommandResult(
            True,
            "Graph edge deleted." if delete else "Graph edge created.",
            {
                "session_id": session_id,
                "view": orientation,
                "edge": {
                    "start_node_id": edge.start_node_id,
                    "end_node_id": edge.end_node_id,
                },
            },
        )

    def _graph_patch_window(self, session_id: str) -> Any | None:
        return self.main_window.graph_patch_window(str(session_id))

    @staticmethod
    def _graph_session_not_found(session_id: str) -> CommandResult:
        return CommandResult(
            False,
            f"Graph patch session was not found: {session_id}",
            {"session_id": str(session_id)},
        )

    def save_projection(
        self,
        view: str,
        path: str,
        annotation_preview: bool = False,
    ) -> CommandResult:
        orientation = _validate_orientation(view)
        if orientation is None:
            return CommandResult(False, "Projection view must be axial, coronal, or sagittal.")
        if path is None or not str(path).strip():
            return CommandResult(False, "Projection save path is required.")

        try:
            output_path, format_name = _resolve_projection_output_path(path)
        except ValueError as exc:
            return CommandResult(False, str(exc), {"path": str(path), "view": orientation})

        parent = output_path.parent
        if not parent.exists():
            return CommandResult(
                False,
                f"Projection save directory does not exist: {parent}",
                {"path": str(output_path), "view": orientation},
            )
        if not parent.is_dir():
            return CommandResult(
                False,
                f"Projection save parent path is not a directory: {parent}",
                {"path": str(output_path), "view": orientation},
            )
        if not os.access(parent, os.W_OK):
            return CommandResult(
                False,
                f"Projection save directory is not writable: {parent}",
                {"path": str(output_path), "view": orientation},
            )

        selected_patch = self.main_window.state.selected_patch_data
        selected_bounds = self.main_window.state.selected_patch_bounds
        if selected_patch is None or selected_bounds is None:
            selected = self.select_patch()
            if not selected.ok:
                return selected
            selected_patch = self.main_window.state.selected_patch_data
            selected_bounds = self.main_window.state.selected_patch_bounds
        if selected_patch is None or selected_bounds is None:
            return CommandResult(False, "No selected patch data is available.")

        mode = _projection_mode(self.main_window.slice_viewer) or "MIP"
        normalized_mode = mode.strip().upper()
        if normalized_mode not in SUPPORTED_PROJECTION_MODES:
            normalized_mode = "MIP"
        projection = project_oriented_volume(
            build_oriented_volume(selected_patch.data, selected_patch.affine).display_data,
            orientation,
            normalized_mode,
        )
        image_data = normalize_slice_to_uint8(projection)

        annotation_preview_requested = bool(annotation_preview)
        annotation_overlay_applied = False
        warnings: list[str] = []
        if annotation_preview_requested:
            annotation_result = self._annotation_projection_for_selected_patch(
                selected_bounds,
                orientation,
            )
            annotation_plane = annotation_result["plane"]
            warnings.extend(annotation_result["warnings"])
            if annotation_plane is not None:
                image_data = _blend_annotation_overlay(
                    image_data,
                    annotation_plane,
                    opacity=self.main_window.state.annotation.opacity,
                    active_label=self.main_window.state.annotation.active_label,
                )
                annotation_overlay_applied = True

        qimage = (
            _rgb_image_from_array(image_data)
            if image_data.ndim == 3
            else _grayscale_image_from_array(image_data)
        )
        if not qimage.save(str(output_path), format_name):
            return CommandResult(
                False,
                "Projection save failed. Check path permissions and file format.",
                {
                    "path": str(output_path),
                    "view": orientation,
                    "mode": normalized_mode,
                    "annotation_preview_requested": annotation_preview_requested,
                    "annotation_overlay_applied": annotation_overlay_applied,
                },
            )

        data: dict[str, Any] = {
            "path": str(output_path),
            "view": orientation,
            "mode": normalized_mode,
            "patch_bounds": _patch_bounds_to_dict(selected_bounds),
            "shape": [int(image_data.shape[0]), int(image_data.shape[1])],
            "annotation_preview_requested": annotation_preview_requested,
            "annotation_overlay_applied": annotation_overlay_applied,
        }
        if annotation_preview_requested:
            data["annotation_projection_mode"] = "MIP"
        if warnings:
            data["warnings"] = warnings

        return CommandResult(
            True,
            "Projection saved.",
            data,
        )

    def _annotation_projection_for_selected_patch(
        self,
        selected_bounds: PatchBounds,
        orientation: Orientation,
    ) -> dict[str, Any]:
        annotation_mask = self.main_window.state.annotation.active_mask
        if annotation_mask is None:
            return {
                "plane": None,
                "warnings": ["No annotation exists in the selected patch."],
            }

        annotation_patch = extract_patch(annotation_mask, selected_bounds)
        if not np.any(np.asarray(annotation_patch.data) > 0):
            return {
                "plane": None,
                "warnings": ["No annotation exists in the selected patch."],
            }

        annotation_plane = project_oriented_volume(
            build_oriented_volume(
                annotation_patch.data,
                annotation_patch.affine,
            ).display_data,
            orientation,
            "MIP",
        )
        return {"plane": annotation_plane, "warnings": []}

    def capture_screenshot(self, path: str | None = None) -> CommandResult:
        if path is None or not str(path).strip():
            return CommandResult(False, "Screenshot path is required.")

        output_path = Path(path)
        parent = output_path.parent
        if not parent.exists():
            return CommandResult(
                False,
                f"Screenshot directory does not exist: {parent}",
                {"path": str(output_path)},
            )
        if not parent.is_dir():
            return CommandResult(
                False,
                f"Screenshot parent path is not a directory: {parent}",
                {"path": str(output_path)},
            )
        if not os.access(parent, os.W_OK):
            return CommandResult(
                False,
                f"Screenshot directory is not writable: {parent}",
                {"path": str(output_path)},
            )

        pixmap = self.main_window.grab()
        if pixmap.isNull():
            return CommandResult(
                False,
                "Screenshot capture produced an empty image.",
                {"path": str(output_path), "target": "full_window"},
            )
        if not pixmap.save(str(output_path)):
            return CommandResult(
                False,
                "Screenshot save failed. Check path permissions and file format.",
                {"path": str(output_path), "target": "full_window"},
            )

        viewer_state = self.export_viewer_state()
        return CommandResult(
            True,
            "Screenshot saved.",
            {
                "path": str(output_path),
                "target": "full_window",
                "viewer_state": viewer_state.data if viewer_state.ok else {},
            },
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


def _patch_bounds_to_array(bounds: PatchBounds) -> np.ndarray:
    return np.asarray(
        [
            [int(bounds.x_start), int(bounds.x_end)],
            [int(bounds.y_start), int(bounds.y_end)],
            [int(bounds.z_start), int(bounds.z_end)],
        ],
        dtype=np.int64,
    )


def _tuple_to_array(value: tuple[int, ...] | None) -> np.ndarray:
    if value is None:
        return np.asarray([], dtype=np.int64)
    return np.asarray([int(item) for item in value], dtype=np.int64)


def _resolve_projection_output_path(path: str | Path) -> tuple[Path, str]:
    output_path = Path(path)
    suffix = output_path.suffix.lower()
    if suffix == ".png":
        return output_path, "PNG"
    if suffix in {".jpg", ".jpeg"}:
        return output_path, "JPG"
    raise ValueError("Projection save path must end with .png, .jpg, or .jpeg.")


def _grayscale_image_from_array(image_data: np.ndarray) -> QImage:
    contiguous = np.ascontiguousarray(image_data, dtype=np.uint8)
    height, width = contiguous.shape
    return QImage(
        contiguous.data,
        width,
        height,
        width,
        QImage.Format.Format_Grayscale8,
    ).copy()


def _rgb_image_from_array(image_data: np.ndarray) -> QImage:
    contiguous = np.ascontiguousarray(image_data, dtype=np.uint8)
    height, width, channels = contiguous.shape
    if channels != 3:
        raise ValueError(f"RGB image export expects 3 channels, got {channels}.")
    return QImage(
        contiguous.data,
        width,
        height,
        width * 3,
        QImage.Format.Format_RGB888,
    ).copy()


def _blend_annotation_overlay(
    image_data: np.ndarray,
    annotation_plane: np.ndarray,
    *,
    opacity: float,
    active_label: int,
) -> np.ndarray:
    overlay = build_annotation_overlay_rgba(
        annotation_plane,
        opacity=opacity,
        active_label=active_label,
    )
    base = np.repeat(np.asarray(image_data, dtype=np.uint8)[..., None], 3, axis=2)
    alpha = overlay[..., 3:4].astype(np.float32) / 255.0
    blended = (
        base.astype(np.float32) * (1.0 - alpha)
        + overlay[..., :3].astype(np.float32) * alpha
    )
    return np.clip(np.rint(blended), 0, 255).astype(np.uint8)


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
