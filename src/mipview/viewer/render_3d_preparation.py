from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
from nibabel.affines import apply_affine
from skimage.measure import marching_cubes

from mipview.io.nifti_io import NiftiLoadResult
from mipview.patch.selector import PatchBounds
from mipview.vessel_graph.model import VesselGraphRenderGeometry
from mipview.viewer.render_3d_state import segmentation_labels


MAX_VOLUME_DIMENSION = 256
MAX_POINT_COUNT = 500_000
MAX_SURFACE_FACES = 1_500_000
TARGET_SURFACE_TRANSITIONS = 750_000


@dataclass(frozen=True)
class PreparedRender3D:
    kind: str
    render_mode: str
    data: np.ndarray | None
    vertices: np.ndarray | None
    faces: np.ndarray | None
    texture_affine: np.ndarray | None
    prepared_shape: tuple[int, int, int]
    stride: tuple[int, int, int]
    source_range: tuple[float, float]
    mask_applied: bool = False
    vertex_labels: np.ndarray | None = None
    graph_edge_segments: np.ndarray | None = None
    graph_node_positions: np.ndarray | None = None
    graph_intercept_positions: np.ndarray | None = None


def prepare_vessel_graph_render(
    geometry: VesselGraphRenderGeometry,
) -> PreparedRender3D:
    """Prepare bounded batched line-and-marker arrays for a vessel graph."""
    segments: list[np.ndarray] = []
    for polyline in geometry.polylines_world:
        path = np.asarray(polyline, dtype=np.float32)
        if path.ndim != 2 or path.shape[1] != 3:
            raise ValueError("Vessel graph polylines must be Nx3 world coordinates.")
        if path.shape[0] >= 2:
            segments.append(
                np.stack((path[:-1], path[1:]), axis=1).reshape(-1, 3)
            )
    edge_segments = (
        np.concatenate(segments, axis=0)
        if segments
        else np.empty((0, 3), dtype=np.float32)
    )
    nodes = np.asarray(geometry.node_world_positions, dtype=np.float32)
    intercepts = np.asarray(geometry.intercept_world_positions, dtype=np.float32)
    if nodes.ndim != 2 or nodes.shape[1:] != (3,):
        raise ValueError("Vessel graph node positions must be Nx3.")
    if intercepts.ndim != 2 or intercepts.shape[1:] != (3,):
        raise ValueError("Vessel graph intercept positions must be Nx3.")
    if not (
        np.all(np.isfinite(edge_segments))
        and np.all(np.isfinite(nodes))
        and np.all(np.isfinite(intercepts))
    ):
        raise ValueError("Vessel graph render geometry must be finite.")
    return PreparedRender3D(
        kind="vessel_graph",
        render_mode="Skeleton",
        data=None,
        vertices=None,
        faces=None,
        texture_affine=None,
        prepared_shape=(
            int(nodes.shape[0]),
            int(edge_segments.shape[0] // 2),
            int(intercepts.shape[0]),
        ),
        stride=(1, 1, 1),
        source_range=(0.0, 0.0),
        graph_edge_segments=edge_segments,
        graph_node_positions=nodes,
        graph_intercept_positions=intercepts,
    )


def prepare_render(
    volume: NiftiLoadResult,
    *,
    kind: str,
    render_mode: str,
    threshold: float,
    mask_volume: NiftiLoadResult | None = None,
    maximum_dimension: int = MAX_VOLUME_DIMENSION,
) -> PreparedRender3D:
    """Prepare a bounded-size CPU representation for later GPU upload."""
    source = np.asarray(volume.data)
    if source.ndim != 3:
        raise ValueError(f"3D rendering expects a 3D volume, got {source.ndim}D.")
    if maximum_dimension <= 0:
        raise ValueError("Maximum 3D render dimension must be positive.")

    stride_value = max(1, math.ceil(max(source.shape) / maximum_dimension))
    stride = (stride_value, stride_value, stride_value)
    sampled = source[::stride_value, ::stride_value, ::stride_value]
    prepared_shape = tuple(int(value) for value in sampled.shape)
    sampled_mask = _sample_render_mask(
        volume,
        mask_volume,
        stride_value=stride_value,
        kind=kind,
        render_mode=render_mode,
    )

    statistics_stride = max(1, math.ceil(max(sampled.shape) / 128))
    statistics_sample = sampled[
        ::statistics_stride,
        ::statistics_stride,
        ::statistics_stride,
    ]
    statistics_valid = np.isfinite(statistics_sample)
    if sampled_mask is not None:
        statistics_valid &= sampled_mask[
            ::statistics_stride,
            ::statistics_stride,
            ::statistics_stride,
        ]
    finite = statistics_sample[statistics_valid]
    if finite.size:
        source_range = (float(np.min(finite)), float(np.max(finite)))
    else:
        source_range = (0.0, 0.0)

    if kind == "image":
        source_range = _robust_image_range(finite, source_range)
        normalized = _normalize_to_uint8(sampled, source_range)
        if sampled_mask is not None:
            normalized = _apply_image_render_mask(
                normalized,
                sampled_mask,
                render_mode,
            )
        # VisPy Volume expects data ordered as z, y, x.
        texture_data = np.ascontiguousarray(normalized.transpose(2, 1, 0))
        scale = np.diag(
            [float(stride_value), float(stride_value), float(stride_value), 1.0]
        )
        return PreparedRender3D(
            kind=kind,
            render_mode=render_mode,
            data=texture_data,
            vertices=None,
            faces=None,
            texture_affine=np.asarray(volume.affine, dtype=np.float64) @ scale,
            prepared_shape=prepared_shape,
            stride=stride,
            source_range=source_range,
            mask_applied=sampled_mask is not None,
        )

    labels = segmentation_labels(volume)
    included_labels = tuple(
        label for label in labels if float(label) > float(threshold)
    )
    mask_data = None if mask_volume is None else np.asarray(mask_volume.data)
    source_mask = (
        None
        if mask_data is None
        else np.asarray(np.isfinite(mask_data) & (mask_data != 0))
    )
    if render_mode == "Points":
        points_parts: list[np.ndarray] = []
        point_label_parts: list[np.ndarray] = []
        for label in included_labels:
            label_foreground = _reduce_segmentation_label(
                source,
                label,
                stride_value=stride_value,
                source_mask=source_mask,
            )
            label_points = np.argwhere(label_foreground)
            if label_points.size:
                points_parts.append(label_points)
                point_label_parts.append(
                    np.full(label_points.shape[0], label, dtype=np.int64)
                )
        points = (
            np.concatenate(points_parts, axis=0)
            if points_parts
            else np.empty((0, 3), dtype=np.int64)
        )
        point_labels = (
            np.concatenate(point_label_parts, axis=0)
            if point_label_parts
            else np.empty((0,), dtype=np.int64)
        )
        if points.shape[0] > MAX_POINT_COUNT:
            selection_stride = math.ceil(points.shape[0] / MAX_POINT_COUNT)
            points = points[::selection_stride]
            point_labels = point_labels[::selection_stride]
        source_points = _reduced_to_source_coordinates(
            points,
            source_shape=source.shape,
            stride_value=stride_value,
        )
        vertices = np.asarray(
            apply_affine(volume.affine, source_points),
            dtype=np.float32,
        )
        return PreparedRender3D(
            kind=kind,
            render_mode=render_mode,
            data=None,
            vertices=vertices,
            faces=None,
            texture_affine=None,
            prepared_shape=prepared_shape,
            stride=stride,
            source_range=source_range,
            mask_applied=sampled_mask is not None,
            vertex_labels=point_labels,
        )

    vertex_parts: list[np.ndarray] = []
    face_parts: list[np.ndarray] = []
    vertex_label_parts: list[np.ndarray] = []
    vertex_offset = 0
    face_budget = max(
        1,
        MAX_SURFACE_FACES // max(len(included_labels), 1),
    )
    for label in included_labels:
        label_foreground = _reduce_segmentation_label(
            source,
            label,
            stride_value=stride_value,
            source_mask=source_mask,
        )
        if not np.any(label_foreground):
            continue
        padded = np.pad(label_foreground.astype(np.uint8), 1)
        surface_step = _surface_step_size(label_foreground)
        while True:
            raw_vertices, raw_faces, _normals, _values = marching_cubes(
                padded,
                level=0.5,
                step_size=surface_step,
                allow_degenerate=False,
            )
            if (
                raw_faces.shape[0] <= face_budget
                or surface_step >= min(label_foreground.shape)
            ):
                break
            surface_step *= 2
        source_vertices = _reduced_to_source_coordinates(
            raw_vertices - 1.0,
            source_shape=source.shape,
            stride_value=stride_value,
        )
        label_vertices = np.asarray(
            apply_affine(volume.affine, source_vertices),
            dtype=np.float32,
        )
        label_faces = np.asarray(raw_faces, dtype=np.uint32) + np.uint32(
            vertex_offset
        )
        vertex_parts.append(label_vertices)
        face_parts.append(label_faces)
        vertex_label_parts.append(
            np.full(label_vertices.shape[0], label, dtype=np.int64)
        )
        vertex_offset += label_vertices.shape[0]

    if not vertex_parts:
        vertices = np.empty((0, 3), dtype=np.float32)
        faces = np.empty((0, 3), dtype=np.uint32)
        vertex_labels = np.empty((0,), dtype=np.int64)
    else:
        vertices = np.concatenate(vertex_parts, axis=0)
        faces = np.concatenate(face_parts, axis=0)
        vertex_labels = np.concatenate(vertex_label_parts, axis=0)
    return PreparedRender3D(
        kind=kind,
        render_mode=render_mode,
        data=None,
        vertices=vertices,
        faces=faces,
        texture_affine=None,
        prepared_shape=prepared_shape,
        stride=stride,
        source_range=source_range,
        mask_applied=sampled_mask is not None,
        vertex_labels=vertex_labels,
    )


def patch_box_world_segments(
    bounds: PatchBounds,
    affine: np.ndarray,
) -> np.ndarray:
    """Return world-space line segments around half-open voxel bounds."""
    starts = np.array(
        [bounds.x_start, bounds.y_start, bounds.z_start],
        dtype=np.float64,
    ) - 0.5
    ends = np.array(
        [bounds.x_end, bounds.y_end, bounds.z_end],
        dtype=np.float64,
    ) - 0.5
    return box_world_segments(starts, ends, affine)


def patch_box_extension_world_segments(
    bounds: PatchBounds,
    source_shape: tuple[int, int, int],
    affine: np.ndarray,
) -> np.ndarray:
    """Return dashed extensions of patch edges to the source-volume boundary."""
    shape = np.asarray(source_shape, dtype=np.int64)
    if shape.shape != (3,) or np.any(shape <= 0):
        raise ValueError("Patch extension source shape must contain three positive sizes.")

    patch_starts = np.asarray(
        [bounds.x_start, bounds.y_start, bounds.z_start],
        dtype=np.float64,
    ) - 0.5
    patch_ends = np.asarray(
        [bounds.x_end, bounds.y_end, bounds.z_end],
        dtype=np.float64,
    ) - 0.5
    source_starts = np.full(3, -0.5, dtype=np.float64)
    source_ends = shape.astype(np.float64) - 0.5
    if np.any(patch_starts < source_starts) or np.any(
        patch_ends > source_ends
    ):
        raise ValueError("Patch bounds must stay inside the extension source volume.")

    transform = np.asarray(affine, dtype=np.float64)
    if transform.shape != (4, 4):
        raise ValueError(f"Patch extension affine must be 4x4, got {transform.shape}.")

    source_world = np.asarray(
        apply_affine(
            transform,
            np.asarray([source_starts, source_ends]),
        ),
        dtype=np.float64,
    )
    source_diagonal = float(np.linalg.norm(source_world[1] - source_world[0]))
    dash_length = max(source_diagonal / 80.0, np.finfo(np.float32).eps)
    gap_length = dash_length * 0.8
    dashed_segments: list[np.ndarray] = []

    for axis in range(3):
        fixed_axes = tuple(index for index in range(3) if index != axis)
        for first_value in (
            patch_starts[fixed_axes[0]],
            patch_ends[fixed_axes[0]],
        ):
            for second_value in (
                patch_starts[fixed_axes[1]],
                patch_ends[fixed_axes[1]],
            ):
                patch_start = patch_starts.copy()
                patch_end = patch_ends.copy()
                patch_start[fixed_axes[0]] = first_value
                patch_start[fixed_axes[1]] = second_value
                patch_end[fixed_axes[0]] = first_value
                patch_end[fixed_axes[1]] = second_value

                lower_source = patch_start.copy()
                lower_source[axis] = source_starts[axis]
                upper_source = patch_end.copy()
                upper_source[axis] = source_ends[axis]
                for start_voxel, end_voxel in (
                    (patch_start, lower_source),
                    (patch_end, upper_source),
                ):
                    world_endpoints = np.asarray(
                        apply_affine(
                            transform,
                            np.asarray([start_voxel, end_voxel]),
                        ),
                        dtype=np.float64,
                    )
                    dashed_segments.extend(
                        _dashed_line_world_segments(
                            world_endpoints[0],
                            world_endpoints[1],
                            dash_length=dash_length,
                            gap_length=gap_length,
                        )
                    )

    if not dashed_segments:
        return np.empty((0, 3), dtype=np.float32)
    return np.asarray(dashed_segments, dtype=np.float32).reshape(-1, 3)


def source_box_world_segments(
    shape: tuple[int, int, int],
    affine: np.ndarray,
) -> np.ndarray:
    starts = np.full(3, -0.5, dtype=np.float64)
    ends = np.asarray(shape, dtype=np.float64) - 0.5
    return box_world_segments(starts, ends, affine)


def cursor_world_position(
    voxel: tuple[int, int, int],
    shape: tuple[int, int, int],
    affine: np.ndarray,
) -> np.ndarray:
    """Map one validated source-voxel cursor position into RAS world space."""
    voxel_position = np.asarray(voxel, dtype=np.float64)
    volume_shape = np.asarray(shape, dtype=np.int64)
    if voxel_position.shape != (3,):
        raise ValueError("3D cursor position must contain exactly three coordinates.")
    if volume_shape.shape != (3,) or np.any(volume_shape <= 0):
        raise ValueError("3D cursor volume shape must contain three positive sizes.")
    if np.any(voxel_position < 0) or np.any(voxel_position >= volume_shape):
        raise ValueError(
            f"3D cursor {tuple(voxel)} is outside volume shape {tuple(shape)}."
        )

    transform = np.asarray(affine, dtype=np.float64)
    if transform.shape != (4, 4):
        raise ValueError(f"3D cursor affine must be 4x4, got {transform.shape}.")
    return np.asarray(
        apply_affine(transform, voxel_position),
        dtype=np.float32,
    )


def orientation_label_world_positions(
    shape: tuple[int, int, int],
    affine: np.ndarray,
) -> tuple[tuple[str, ...], np.ndarray]:
    """Place L/R, P/A, and I/S labels around the volume in RAS world space."""
    limits = _world_limits_for_shape(shape, affine)
    midpoints = np.asarray(
        [(minimum + maximum) / 2.0 for minimum, maximum in limits],
        dtype=np.float64,
    )
    span = np.asarray(
        [maximum - minimum for minimum, maximum in limits],
        dtype=np.float64,
    )
    minimum_padding = max(float(np.linalg.norm(span)) * 0.002, 1.0e-3)
    padding = np.maximum(span * 0.10, minimum_padding)
    positions = np.repeat(midpoints[None, :], 6, axis=0)
    positions[0, 0] = limits[0][0] - padding[0]
    positions[1, 0] = limits[0][1] + padding[0]
    positions[2, 1] = limits[1][0] - padding[1]
    positions[3, 1] = limits[1][1] + padding[1]
    positions[4, 2] = limits[2][0] - padding[2]
    positions[5, 2] = limits[2][1] + padding[2]
    return ("L", "R", "P", "A", "I", "S"), np.asarray(
        positions,
        dtype=np.float32,
    )


def box_world_segments(
    starts: np.ndarray,
    ends: np.ndarray,
    affine: np.ndarray,
) -> np.ndarray:
    corners = np.array(
        [
            [starts[0], starts[1], starts[2]],
            [ends[0], starts[1], starts[2]],
            [starts[0], ends[1], starts[2]],
            [ends[0], ends[1], starts[2]],
            [starts[0], starts[1], ends[2]],
            [ends[0], starts[1], ends[2]],
            [starts[0], ends[1], ends[2]],
            [ends[0], ends[1], ends[2]],
        ],
        dtype=np.float64,
    )
    world = np.asarray(apply_affine(affine, corners), dtype=np.float32)
    edge_indices = (
        (0, 1),
        (0, 2),
        (1, 3),
        (2, 3),
        (4, 5),
        (4, 6),
        (5, 7),
        (6, 7),
        (0, 4),
        (1, 5),
        (2, 6),
        (3, 7),
    )
    return np.asarray(
        [world[index] for edge in edge_indices for index in edge],
        dtype=np.float32,
    )


def _world_limits_for_shape(
    shape: tuple[int, int, int],
    affine: np.ndarray,
) -> tuple[
    tuple[float, float],
    tuple[float, float],
    tuple[float, float],
]:
    coordinates = source_box_world_segments(shape, affine).reshape(-1, 3)
    minimum = np.min(coordinates, axis=0)
    maximum = np.max(coordinates, axis=0)
    return tuple(
        (float(minimum[axis]), float(maximum[axis]))
        for axis in range(3)
    )


def _normalize_to_uint8(
    data: np.ndarray,
    source_range: tuple[float, float],
) -> np.ndarray:
    minimum, maximum = source_range
    if not np.isfinite(minimum) or not np.isfinite(maximum) or maximum <= minimum:
        return np.zeros(data.shape, dtype=np.uint8)
    scaled = (np.asarray(data, dtype=np.float32) - minimum) / (maximum - minimum)
    scaled[~np.isfinite(scaled)] = 0.0
    return np.asarray(np.clip(scaled * 255.0, 0.0, 255.0), dtype=np.uint8)


def _reduce_segmentation_label(
    source: np.ndarray,
    label: int,
    *,
    stride_value: int,
    source_mask: np.ndarray | None,
) -> np.ndarray:
    """Reduce one label without dropping thin structures between stride samples."""
    foreground = np.asarray(source == label)
    if source_mask is not None:
        foreground &= source_mask
    if stride_value == 1:
        return foreground

    reduced_shape = tuple(
        math.ceil(size / stride_value)
        for size in foreground.shape
    )
    reduced = np.zeros(reduced_shape, dtype=bool)
    for x_offset in range(stride_value):
        for y_offset in range(stride_value):
            for z_offset in range(stride_value):
                block_sample = foreground[
                    x_offset::stride_value,
                    y_offset::stride_value,
                    z_offset::stride_value,
                ]
                target = reduced[
                    : block_sample.shape[0],
                    : block_sample.shape[1],
                    : block_sample.shape[2],
                ]
                np.logical_or(target, block_sample, out=target)
    return reduced


def _reduced_to_source_coordinates(
    coordinates: np.ndarray,
    *,
    source_shape: tuple[int, ...],
    stride_value: int,
) -> np.ndarray:
    """Map reduced block coordinates to their voxel-space block centres."""
    reduced = np.asarray(coordinates, dtype=np.float64)
    source_coordinates = np.empty(reduced.shape, dtype=np.float64)
    for axis, source_size in enumerate(source_shape):
        reduced_size = math.ceil(source_size / stride_value)
        reduced_boundaries = np.arange(reduced_size + 1, dtype=np.float64) - 0.5
        source_boundaries = np.minimum(
            np.arange(reduced_size + 1, dtype=np.float64) * stride_value,
            source_size,
        ) - 0.5
        source_coordinates[:, axis] = np.interp(
            reduced[:, axis],
            reduced_boundaries,
            source_boundaries,
        )
    return source_coordinates


def _sample_render_mask(
    volume: NiftiLoadResult,
    mask_volume: NiftiLoadResult | None,
    *,
    stride_value: int,
    kind: str,
    render_mode: str,
) -> np.ndarray | None:
    if mask_volume is None:
        return None
    supported = (
        kind == "image"
        and render_mode in {"MIP", "MinIP"}
        or kind == "segmentation"
        and render_mode in {"Surface", "Points"}
    )
    if not supported:
        raise ValueError(
            f"3D masking is not supported for {kind} mode {render_mode!r}."
        )
    mask_data = np.asarray(mask_volume.data)
    if mask_data.ndim != 3:
        raise ValueError(f"3D render mask must be 3D, got {mask_data.ndim}D.")
    if volume.shape != mask_volume.shape:
        raise ValueError(
            "3D render mask shape does not match the selected layer: "
            f"layer={volume.shape}, mask={mask_volume.shape}."
        )
    if (
        np.asarray(volume.affine).shape != (4, 4)
        or np.asarray(mask_volume.affine).shape != (4, 4)
        or not np.allclose(
            volume.affine,
            mask_volume.affine,
            atol=1.0e-4,
            rtol=0.0,
        )
    ):
        raise ValueError(
            "3D render mask affine does not match the selected layer."
        )
    sampled = mask_data[::stride_value, ::stride_value, ::stride_value]
    return np.asarray(np.isfinite(sampled) & (sampled != 0))


def _apply_image_render_mask(
    normalized: np.ndarray,
    sampled_mask: np.ndarray,
    render_mode: str,
) -> np.ndarray:
    # Reserve one end of the scalar range as a transparent sentinel. For MinIP,
    # the sentinel must be greater than every included value so it cannot win a
    # ray minimum; MIP uses the inverse arrangement.
    scaled = (
        np.asarray(normalized, dtype=np.uint16) * np.uint16(254)
    ) // np.uint16(255)
    if render_mode == "MIP":
        included = np.asarray(scaled + 1, dtype=np.uint8)
        return np.where(sampled_mask, included, 0).astype(np.uint8, copy=False)
    if render_mode == "MinIP":
        included = np.asarray(scaled, dtype=np.uint8)
        return np.where(sampled_mask, included, 255).astype(np.uint8, copy=False)
    raise ValueError(f"Unsupported masked image render mode: {render_mode!r}.")


def _dashed_line_world_segments(
    start: np.ndarray,
    end: np.ndarray,
    *,
    dash_length: float,
    gap_length: float,
) -> list[np.ndarray]:
    delta = np.asarray(end, dtype=np.float64) - np.asarray(
        start,
        dtype=np.float64,
    )
    length = float(np.linalg.norm(delta))
    if length <= np.finfo(np.float32).eps:
        return []
    direction = delta / length
    segments: list[np.ndarray] = []
    distance = 0.0
    while distance < length:
        dash_end = min(distance + dash_length, length)
        segments.extend(
            (
                np.asarray(start, dtype=np.float64) + direction * distance,
                np.asarray(start, dtype=np.float64) + direction * dash_end,
            )
        )
        distance += dash_length + gap_length
    if not np.allclose(segments[-1], end):
        final_start = max(0.0, length - min(dash_length, length) * 0.5)
        segments.extend(
            (
                np.asarray(start, dtype=np.float64) + direction * final_start,
                np.asarray(end, dtype=np.float64),
            )
        )
    return segments


def _robust_image_range(
    finite: np.ndarray,
    fallback: tuple[float, float],
) -> tuple[float, float]:
    """Choose display limits that are not dominated by isolated outliers."""
    if finite.size < 2:
        return fallback
    lower, upper = np.percentile(finite, (1.0, 99.5))
    if not np.isfinite(lower) or not np.isfinite(upper) or upper <= lower:
        return fallback
    return float(lower), float(upper)


def _surface_step_size(foreground: np.ndarray) -> int:
    transitions = 0
    for axis in range(3):
        first = [slice(None), slice(None), slice(None)]
        second = [slice(None), slice(None), slice(None)]
        first[axis] = slice(1, None)
        second[axis] = slice(None, -1)
        transitions += int(
            np.count_nonzero(
                foreground[tuple(first)] != foreground[tuple(second)]
            )
        )
    if transitions <= TARGET_SURFACE_TRANSITIONS:
        return 1
    return max(
        1,
        int(math.ceil(math.sqrt(transitions / TARGET_SURFACE_TRANSITIONS))),
    )
