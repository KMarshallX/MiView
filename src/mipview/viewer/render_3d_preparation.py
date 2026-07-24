from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
from nibabel.affines import apply_affine
from skimage.measure import marching_cubes

from mipview.io.nifti_io import NiftiLoadResult
from mipview.patch.selector import PatchBounds


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


def prepare_render(
    volume: NiftiLoadResult,
    *,
    kind: str,
    render_mode: str,
    threshold: float,
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

    statistics_stride = max(1, math.ceil(max(sampled.shape) / 128))
    statistics_sample = sampled[
        ::statistics_stride,
        ::statistics_stride,
        ::statistics_stride,
    ]
    finite = statistics_sample[np.isfinite(statistics_sample)]
    if finite.size:
        source_range = (float(np.min(finite)), float(np.max(finite)))
    else:
        source_range = (0.0, 0.0)

    if kind == "image":
        source_range = _robust_image_range(finite, source_range)
        normalized = _normalize_to_uint8(sampled, source_range)
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
        )

    foreground = np.asarray(np.isfinite(sampled) & (sampled > float(threshold)))
    if render_mode == "Points":
        points = np.argwhere(foreground)
        if points.shape[0] > MAX_POINT_COUNT:
            selection_stride = math.ceil(points.shape[0] / MAX_POINT_COUNT)
            points = points[::selection_stride]
        source_points = points.astype(np.float32) * float(stride_value)
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
        )

    if not np.any(foreground):
        vertices = np.empty((0, 3), dtype=np.float32)
        faces = np.empty((0, 3), dtype=np.uint32)
    else:
        padded = np.pad(foreground.astype(np.uint8), 1)
        surface_step = _surface_step_size(foreground)
        while True:
            raw_vertices, raw_faces, _normals, _values = marching_cubes(
                padded,
                level=0.5,
                step_size=surface_step,
                allow_degenerate=False,
            )
            if (
                raw_faces.shape[0] <= MAX_SURFACE_FACES
                or surface_step >= min(foreground.shape)
            ):
                break
            surface_step *= 2
        # Remove the padding, restore source voxel scale, then use world space.
        source_vertices = (raw_vertices - 1.0) * float(stride_value)
        vertices = np.asarray(
            apply_affine(volume.affine, source_vertices),
            dtype=np.float32,
        )
        faces = np.asarray(raw_faces, dtype=np.uint32)
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
    padding = np.maximum(span * 0.04, minimum_padding)
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
