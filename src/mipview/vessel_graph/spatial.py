from __future__ import annotations

import numpy as np
from nibabel.affines import apply_affine

from mipview.patch.selector import PatchBounds
from mipview.vessel_graph.model import (
    ClippedVesselGraph,
    ProjectedVesselGraphLayer,
    VesselGraphData,
)
from mipview.viewer.oriented_volume import OrientedVolume
from mipview.viewer.slice_geometry import (
    Orientation,
    plane_definition_for_orientation,
    plane_shape_for_orientation,
)


def full_vessel_graph_geometry(
    graph: VesselGraphData,
    *,
    use_centerlines: bool = True,
) -> tuple[tuple[np.ndarray, ...], np.ndarray]:
    """Return full graph world-space polylines and true node positions."""
    paths: list[np.ndarray] = []
    for edge_index, (source_index, target_index) in enumerate(
        graph.edge_node_indices
    ):
        source = graph.node_world_positions[int(source_index)]
        target = graph.node_world_positions[int(target_index)]
        if use_centerlines:
            centerline = graph.edge_centerline(edge_index)
            centerline_world = apply_affine(graph.original_affine, centerline)
            path = np.vstack((source, centerline_world, target))
        else:
            path = np.vstack((source, target))
        paths.append(_drop_adjacent_duplicates(path))
    return tuple(paths), np.asarray(graph.node_world_positions, dtype=np.float64)


def clip_vessel_graph_to_patch(
    graph: VesselGraphData,
    bounds: PatchBounds,
    patch_affine: np.ndarray,
) -> ClippedVesselGraph:
    """Clip graph paths to patch voxel-cell bounds and mark boundary intercepts."""
    starts = np.asarray(
        (bounds.x_start, bounds.y_start, bounds.z_start),
        dtype=np.float64,
    )
    lower = starts - 0.5
    upper = np.asarray(
        (bounds.x_end, bounds.y_end, bounds.z_end),
        dtype=np.float64,
    ) - 0.5

    node_loaded = np.asarray(
        apply_affine(
            graph.original_to_loaded_voxel_affine,
            graph.node_source_voxels,
        ),
        dtype=np.float64,
    )
    node_inside = np.all(node_loaded >= lower, axis=1) & np.all(
        node_loaded <= upper,
        axis=1,
    )
    inside_loaded = node_loaded[node_inside]
    inside_patch = inside_loaded - starts
    inside_world = np.asarray(
        apply_affine(patch_affine, inside_patch),
        dtype=np.float64,
    )

    clipped_patch_paths: list[np.ndarray] = []
    clipped_world_paths: list[np.ndarray] = []
    intercept_patch_points: list[np.ndarray] = []
    for edge_index, (source_index, target_index) in enumerate(
        graph.edge_node_indices
    ):
        source_original = graph.node_source_voxels[int(source_index)]
        target_original = graph.node_source_voxels[int(target_index)]
        original_path = np.vstack(
            (
                source_original,
                graph.edge_centerline(edge_index),
                target_original,
            )
        )
        loaded_path = np.asarray(
            apply_affine(graph.original_to_loaded_voxel_affine, original_path),
            dtype=np.float64,
        )
        for clipped, intercepts in _clip_polyline_to_box(loaded_path, lower, upper):
            patch_path = clipped - starts
            clipped_patch_paths.append(patch_path)
            clipped_world_paths.append(
                np.asarray(apply_affine(patch_affine, patch_path), dtype=np.float64)
            )
            intercept_patch_points.extend(point - starts for point in intercepts)

    intercept_patch = _unique_points(intercept_patch_points)
    intercept_world = np.asarray(
        apply_affine(patch_affine, intercept_patch),
        dtype=np.float64,
    )
    return ClippedVesselGraph(
        patch_shape=(
            bounds.x_end - bounds.x_start,
            bounds.y_end - bounds.y_start,
            bounds.z_end - bounds.z_start,
        ),
        patch_affine=np.asarray(patch_affine, dtype=np.float64),
        polylines_patch_voxel=tuple(clipped_patch_paths),
        polylines_world=tuple(clipped_world_paths),
        node_patch_voxels=inside_patch,
        node_world_positions=inside_world,
        intercept_patch_voxels=intercept_patch,
        intercept_world_positions=intercept_world,
    )


def project_clipped_vessel_graph(
    clipped: ClippedVesselGraph,
    oriented_volume: OrientedVolume,
    orientation: Orientation,
) -> ProjectedVesselGraphLayer:
    """Project known 3D graph geometry orthographically into a patch plane."""
    return ProjectedVesselGraphLayer(
        orientation=orientation,
        plane_shape=plane_shape_for_orientation(
            oriented_volume.display_shape,
            orientation,
        ),
        polylines=tuple(
            _project_points(path, oriented_volume, orientation)
            for path in clipped.polylines_patch_voxel
        ),
        node_positions=_project_points(
            clipped.node_patch_voxels,
            oriented_volume,
            orientation,
        ),
        intercept_positions=_project_points(
            clipped.intercept_patch_voxels,
            oriented_volume,
            orientation,
        ),
    )


def _project_points(
    source_points: np.ndarray,
    oriented_volume: OrientedVolume,
    orientation: Orientation,
) -> np.ndarray:
    points = np.asarray(source_points, dtype=np.float64)
    if points.size == 0:
        return np.empty((0, 2), dtype=np.float64)
    display_points = np.asarray(
        apply_affine(oriented_volume.source_to_display_affine, points),
        dtype=np.float64,
    )
    definition = plane_definition_for_orientation(orientation)
    horizontal = display_points[:, definition.horizontal_axis]
    vertical = display_points[:, definition.vertical_axis]
    if definition.horizontal_flipped:
        horizontal = (
            oriented_volume.display_shape[definition.horizontal_axis]
            - 1
            - horizontal
        )
    if definition.vertical_flipped:
        vertical = (
            oriented_volume.display_shape[definition.vertical_axis]
            - 1
            - vertical
        )
    return np.column_stack((horizontal, vertical))


def _clip_polyline_to_box(
    path: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
) -> list[tuple[np.ndarray, tuple[np.ndarray, ...]]]:
    results: list[tuple[np.ndarray, tuple[np.ndarray, ...]]] = []
    current: list[np.ndarray] = []
    current_intercepts: list[np.ndarray] = []
    for start, end in zip(path[:-1], path[1:]):
        clipped = _clip_segment_to_box(start, end, lower, upper)
        if clipped is None:
            if len(current) >= 2:
                results.append(
                    (_drop_adjacent_duplicates(np.asarray(current)), tuple(current_intercepts))
                )
            current = []
            current_intercepts = []
            continue
        first, second, first_intercept, second_intercept = clipped
        if not current or not np.allclose(current[-1], first, atol=1.0e-9, rtol=0.0):
            if len(current) >= 2:
                results.append(
                    (_drop_adjacent_duplicates(np.asarray(current)), tuple(current_intercepts))
                )
            current = [first]
            current_intercepts = []
        current.append(second)
        if first_intercept:
            current_intercepts.append(first)
        if second_intercept:
            current_intercepts.append(second)
    if len(current) >= 2:
        results.append(
            (_drop_adjacent_duplicates(np.asarray(current)), tuple(current_intercepts))
        )
    return results


def _clip_segment_to_box(
    start: np.ndarray,
    end: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, bool, bool] | None:
    delta = end - start
    t_min = 0.0
    t_max = 1.0
    for axis in range(3):
        if abs(float(delta[axis])) <= 1.0e-12:
            if start[axis] < lower[axis] or start[axis] > upper[axis]:
                return None
            continue
        first = (lower[axis] - start[axis]) / delta[axis]
        second = (upper[axis] - start[axis]) / delta[axis]
        entering = min(first, second)
        exiting = max(first, second)
        t_min = max(t_min, float(entering))
        t_max = min(t_max, float(exiting))
        if t_min > t_max:
            return None
    clipped_start = start + delta * t_min
    clipped_end = start + delta * t_max
    return (
        clipped_start,
        clipped_end,
        t_min > 1.0e-9,
        t_max < 1.0 - 1.0e-9,
    )


def _drop_adjacent_duplicates(points: np.ndarray) -> np.ndarray:
    array = np.asarray(points, dtype=np.float64)
    if array.shape[0] <= 1:
        return array
    keep = np.ones(array.shape[0], dtype=bool)
    keep[1:] = np.any(np.abs(np.diff(array, axis=0)) > 1.0e-9, axis=1)
    return array[keep]


def _unique_points(points: list[np.ndarray]) -> np.ndarray:
    if not points:
        return np.empty((0, 3), dtype=np.float64)
    unique: list[np.ndarray] = []
    for point in points:
        if not any(np.allclose(point, item, atol=1.0e-7, rtol=0.0) for item in unique):
            unique.append(np.asarray(point, dtype=np.float64))
    return np.asarray(unique, dtype=np.float64)
