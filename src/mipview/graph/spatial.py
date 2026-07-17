from __future__ import annotations

import math

import numpy as np

from mipview.graph.curve import nearest_quadratic_bezier_parameter
from mipview.graph.model import (
    GraphEdge,
    ProjectedGraphNode,
    ProjectionGraphLayer,
    VoxelGraph,
    VoxelPoint,
)
from mipview.viewer.oriented_volume import OrientedVolume
from mipview.viewer.slice_geometry import (
    Orientation,
    plane_definition_for_orientation,
    plane_shape_for_orientation,
)


def build_projected_graph_layer(
    graph: VoxelGraph,
    oriented_volume: OrientedVolume,
    orientation: Orientation,
) -> ProjectionGraphLayer:
    nodes = {
        node.id: ProjectedGraphNode(
            node.id,
            *project_source_point(node.position(), oriented_volume, orientation),
        )
        for node in graph.nodes.values()
    }
    controls = {
        edge: project_source_point(point, oriented_volume, orientation)
        for edge, point in graph.curve_control_points.items()
    }
    return ProjectionGraphLayer(
        orientation=orientation,
        plane_shape=plane_shape_for_orientation(
            oriented_volume.display_shape,
            orientation,
        ),
        nodes=nodes,
        edges=frozenset(graph.edges),
        curve_control_points=controls,
    )


def project_source_point(
    source_point: tuple[int, int, int] | VoxelPoint,
    oriented_volume: OrientedVolume,
    orientation: Orientation,
) -> tuple[float, float]:
    display_point = _transform_point(
        tuple(float(value) for value in source_point),
        oriented_volume.source_to_display_affine,
    )
    definition = plane_definition_for_orientation(orientation)
    horizontal = display_point[definition.horizontal_axis]
    vertical = display_point[definition.vertical_axis]
    if definition.horizontal_flipped:
        horizontal = (
            oriented_volume.display_shape[definition.horizontal_axis] - 1 - horizontal
        )
    if definition.vertical_flipped:
        vertical = oriented_volume.display_shape[definition.vertical_axis] - 1 - vertical
    return (float(horizontal), float(vertical))


def resolve_projection_voxel(
    oriented_volume: OrientedVolume,
    orientation: Orientation,
    mode: str,
    horizontal_index: int,
    vertical_index: int,
    *,
    mask_display_data: np.ndarray | None = None,
    preferred_display_voxel: tuple[int, int, int] | None = None,
) -> tuple[int, int, int]:
    """Resolve a displayed projection index to its extremum source voxel."""
    horizontal = int(horizontal_index)
    vertical = int(vertical_index)
    plane_shape = plane_shape_for_orientation(
        oriented_volume.display_shape,
        orientation,
    )
    if not (0 <= horizontal < plane_shape[0] and 0 <= vertical < plane_shape[1]):
        raise ValueError(
            f"Graph projection coordinate {(horizontal, vertical)} is outside shape "
            f"{plane_shape}."
        )

    definition = plane_definition_for_orientation(orientation)
    display_voxel = [0, 0, 0]
    display_voxel[definition.horizontal_axis] = (
        oriented_volume.display_shape[definition.horizontal_axis] - 1 - horizontal
        if definition.horizontal_flipped
        else horizontal
    )
    display_voxel[definition.vertical_axis] = (
        oriented_volume.display_shape[definition.vertical_axis] - 1 - vertical
        if definition.vertical_flipped
        else vertical
    )

    ray_selector: list[int | slice] = list(display_voxel)
    ray_selector[definition.fixed_axis] = slice(None)
    ray_values = np.asarray(
        oriented_volume.display_data[tuple(ray_selector)],
        dtype=np.float64,
    )
    valid = np.isfinite(ray_values)
    if mask_display_data is not None:
        mask = np.asarray(mask_display_data)
        if mask.shape != oriented_volume.display_shape:
            raise ValueError("Projection mask shape must match the projected volume shape.")
        valid &= np.asarray(mask[tuple(ray_selector)]) != 0
    if not np.any(valid):
        raise ValueError(
            "The selected projection ray contains no finite contributing voxels."
        )

    normalized_mode = mode.strip().upper()
    if normalized_mode not in {"MIP", "MINIP"}:
        raise ValueError("Projection mode must be MIP or MinIP.")
    valid_values = ray_values[valid]
    extremum = (
        float(np.max(valid_values))
        if normalized_mode == "MIP"
        else float(np.min(valid_values))
    )
    candidates = np.flatnonzero(valid & (ray_values == extremum))
    preferred_depth = (
        int(preferred_display_voxel[definition.fixed_axis])
        if preferred_display_voxel is not None
        else 0
    )
    fixed_index = min(
        (int(index) for index in candidates),
        key=lambda index: (abs(index - preferred_depth), index),
    )
    display_voxel[definition.fixed_axis] = fixed_index
    return oriented_volume.display_to_source(tuple(display_voxel))


def update_control_point_from_projection(
    source_control_point: VoxelPoint,
    oriented_volume: OrientedVolume,
    orientation: Orientation,
    horizontal: float,
    vertical: float,
) -> VoxelPoint:
    """Update visible control coordinates while retaining projection depth."""
    if not math.isfinite(horizontal) or not math.isfinite(vertical):
        raise ValueError("Curve control point coordinates must be finite.")
    plane_shape = plane_shape_for_orientation(oriented_volume.display_shape, orientation)
    if not (0.0 <= horizontal <= plane_shape[0] - 1) or not (
        0.0 <= vertical <= plane_shape[1] - 1
    ):
        raise ValueError(
            f"Curve control point {(horizontal, vertical)} is outside shape {plane_shape}."
        )

    display_point = list(
        _transform_point(
            source_control_point,
            oriented_volume.source_to_display_affine,
        )
    )
    definition = plane_definition_for_orientation(orientation)
    display_point[definition.horizontal_axis] = (
        oriented_volume.display_shape[definition.horizontal_axis] - 1 - horizontal
        if definition.horizontal_flipped
        else horizontal
    )
    display_point[definition.vertical_axis] = (
        oriented_volume.display_shape[definition.vertical_axis] - 1 - vertical
        if definition.vertical_flipped
        else vertical
    )
    return _transform_point(
        tuple(display_point),
        oriented_volume.display_to_source_affine,
    )


def nearest_projected_edge_parameter(
    layer: ProjectionGraphLayer,
    edge: GraphEdge,
    near_position: tuple[int, int] | tuple[float, float],
) -> float:
    if edge not in layer.edges:
        raise ValueError(
            f"Graph edge {edge.start_node_id}-{edge.end_node_id} does not exist."
        )
    start = layer.nodes[edge.start_node_id].position()
    end = layer.nodes[edge.end_node_id].position()
    point = (float(near_position[0]), float(near_position[1]))
    control = layer.curve_control_points.get(edge)
    if control is not None:
        return nearest_quadratic_bezier_parameter(point, start, control, end)
    return _nearest_segment_parameter(point, start, end)


def _nearest_segment_parameter(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    delta_x = end[0] - start[0]
    delta_y = end[1] - start[1]
    squared_length = (delta_x * delta_x) + (delta_y * delta_y)
    if squared_length <= 0.0:
        return 0.0
    parameter = (
        ((point[0] - start[0]) * delta_x)
        + ((point[1] - start[1]) * delta_y)
    ) / squared_length
    return min(max(parameter, 0.0), 1.0)


def _transform_point(point: VoxelPoint, affine: np.ndarray) -> VoxelPoint:
    homogeneous = np.array([point[0], point[1], point[2], 1.0], dtype=np.float64)
    mapped = np.asarray(affine, dtype=np.float64) @ homogeneous
    return (float(mapped[0]), float(mapped[1]), float(mapped[2]))
