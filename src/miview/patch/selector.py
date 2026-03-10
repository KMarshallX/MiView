from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from miview.viewer.oriented_volume import OrientedVolume
from miview.viewer.slice_geometry import (
    Orientation,
    plane_axes_for_orientation,
    plane_definition_for_orientation,
)

DEFAULT_PATCH_SIZE = (64, 64, 10)


@dataclass(frozen=True)
class PatchBounds:
    """Half-open 3D voxel bounds in source index space."""

    x_start: int
    x_end: int
    y_start: int
    y_end: int
    z_start: int
    z_end: int

    def as_slices(self) -> tuple[slice, slice, slice]:
        return (
            slice(self.x_start, self.x_end),
            slice(self.y_start, self.y_end),
            slice(self.z_start, self.z_end),
        )


@dataclass(frozen=True)
class PatchPlaneBounds:
    """Half-open 2D bounds on the displayed orientation plane."""

    horizontal_start: int
    horizontal_end: int
    vertical_start: int
    vertical_end: int


class PatchSelector:
    """Shared 3D patch selection state centered on the logical source cursor."""

    def __init__(self, default_size: tuple[int, int, int] = DEFAULT_PATCH_SIZE) -> None:
        self._enabled = False
        self._opacity = 0.5
        self._size = (
            _clamp_patch_size(default_size[0]),
            _clamp_patch_size(default_size[1]),
            _clamp_patch_size(default_size[2]),
        )
        self._volume_shape: tuple[int, int, int] | None = None
        self._center: tuple[int, int, int] | None = None

    def clear(self) -> None:
        self._volume_shape = None
        self._center = None

    def set_volume_shape(self, shape: tuple[int, int, int]) -> None:
        self._volume_shape = shape

    def set_center(self, center: tuple[int, int, int]) -> None:
        self._center = center

    def center(self) -> tuple[int, int, int] | None:
        return self._center

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    def enabled(self) -> bool:
        return self._enabled

    def set_opacity(self, opacity: float) -> None:
        self._opacity = min(max(float(opacity), 0.0), 1.0)

    def opacity(self) -> float:
        return self._opacity

    def size_xyz(self) -> tuple[int, int, int]:
        return self._size

    def set_size_axis(self, axis: int, size: int) -> bool:
        if axis not in (0, 1, 2):
            raise ValueError(f"Expected patch axis in 0..2, got {axis}.")

        clamped_size = _clamp_patch_size(size)
        current = list(self._size)
        if current[axis] == clamped_size:
            return False

        current[axis] = clamped_size
        self._size = tuple(current)
        return True

    def current_bounds(self) -> PatchBounds | None:
        if self._volume_shape is None or self._center is None:
            return None
        return compute_patch_bounds(self._center, self._size, self._volume_shape)


def compute_patch_bounds(
    center: tuple[int, int, int],
    size: tuple[int, int, int],
    volume_shape: tuple[int, int, int],
) -> PatchBounds:
    x_start, x_end = _axis_bounds(center[0], size[0], volume_shape[0])
    y_start, y_end = _axis_bounds(center[1], size[1], volume_shape[1])
    z_start, z_end = _axis_bounds(center[2], size[2], volume_shape[2])
    return PatchBounds(
        x_start=x_start,
        x_end=x_end,
        y_start=y_start,
        y_end=y_end,
        z_start=z_start,
        z_end=z_end,
    )


def source_bounds_to_display_bounds(
    bounds: PatchBounds,
    display_volume: OrientedVolume,
) -> PatchBounds:
    """Map source-space patch bounds into half-open display-space bounds."""
    source_points = _bounds_corners(bounds)
    mapped = np.array(
        [display_volume.source_to_display(tuple(point)) for point in source_points],
        dtype=np.int64,
    )
    mins = mapped.min(axis=0)
    maxs = mapped.max(axis=0) + 1
    return PatchBounds(
        x_start=int(mins[0]),
        x_end=int(maxs[0]),
        y_start=int(mins[1]),
        y_end=int(maxs[1]),
        z_start=int(mins[2]),
        z_end=int(maxs[2]),
    )


def project_bounds_to_orientation(
    bounds: PatchBounds,
    orientation: Orientation,
    display_shape: tuple[int, int, int],
) -> PatchPlaneBounds:
    plane_definition = plane_definition_for_orientation(orientation)
    horizontal_axis, vertical_axis, _ = plane_axes_for_orientation(orientation)
    starts = (bounds.x_start, bounds.y_start, bounds.z_start)
    ends = (bounds.x_end, bounds.y_end, bounds.z_end)
    horizontal_start, horizontal_end = _project_axis_interval_to_orientation(
        starts[horizontal_axis],
        ends[horizontal_axis],
        display_shape[horizontal_axis],
        plane_definition.horizontal_flipped,
    )
    vertical_start, vertical_end = _project_axis_interval_to_orientation(
        starts[vertical_axis],
        ends[vertical_axis],
        display_shape[vertical_axis],
        plane_definition.vertical_flipped,
    )
    return PatchPlaneBounds(
        horizontal_start=horizontal_start,
        horizontal_end=horizontal_end,
        vertical_start=vertical_start,
        vertical_end=vertical_end,
    )


def orientation_slice_intersects_bounds(
    bounds: PatchBounds,
    orientation: Orientation,
    display_cursor: tuple[int, int, int],
) -> bool:
    _, _, fixed_axis = plane_axes_for_orientation(orientation)
    starts = (bounds.x_start, bounds.y_start, bounds.z_start)
    ends = (bounds.x_end, bounds.y_end, bounds.z_end)
    fixed_index = display_cursor[fixed_axis]
    return starts[fixed_axis] <= fixed_index < ends[fixed_axis]


def editable_axes_for_orientation(orientation: Orientation) -> tuple[int, ...]:
    """Return source-space axes editable in a given orientation view."""
    if orientation == "axial":
        return (0, 1)
    if orientation in ("sagittal", "coronal"):
        return (2,)
    raise ValueError(f"Unsupported orientation: {orientation}")


def axis_for_resize_edge(orientation: Orientation, edge: str) -> int | None:
    if orientation == "axial":
        if edge in ("left", "right"):
            return 0
        if edge in ("top", "bottom"):
            return 1
        return None
    if orientation in ("sagittal", "coronal"):
        if edge in ("top", "bottom"):
            return 2
        return None
    raise ValueError(f"Unsupported orientation: {orientation}")


def resized_axis_size_from_edge(
    center_index: int,
    edge_index: int,
    edge: str,
    current_size: int,
) -> int:
    """Convert an edge drag target into a symmetric size around center_index."""
    distance = abs(edge_index - center_index)
    is_even = (current_size % 2) == 0

    if edge in ("left", "top"):
        raw_size = 2 * distance if is_even else (2 * distance) + 1
    elif edge in ("right", "bottom"):
        raw_size = 2 * (distance + 1) if is_even else (2 * distance) + 1
    else:
        raise ValueError(f"Unsupported resize edge: {edge}")

    return _clamp_patch_size(raw_size)


def _bounds_corners(bounds: PatchBounds) -> list[tuple[int, int, int]]:
    max_x = max(bounds.x_end - 1, bounds.x_start)
    max_y = max(bounds.y_end - 1, bounds.y_start)
    max_z = max(bounds.z_end - 1, bounds.z_start)

    points: list[tuple[int, int, int]] = []
    for x in (bounds.x_start, max_x):
        for y in (bounds.y_start, max_y):
            for z in (bounds.z_start, max_z):
                points.append((x, y, z))
    return points


def _axis_bounds(center: int, size: int, axis_length: int) -> tuple[int, int]:
    requested_size = _clamp_patch_size(size)
    start = center - (requested_size // 2)
    end = start + requested_size
    return max(start, 0), min(end, axis_length)


def _clamp_patch_size(size: int) -> int:
    return max(1, int(size))


def _project_axis_interval_to_orientation(
    start: int, end: int, axis_size: int, flipped: bool
) -> tuple[int, int]:
    clamped_start = min(max(start, 0), axis_size)
    clamped_end = min(max(end, 0), axis_size)

    if flipped:
        return axis_size - clamped_end, axis_size - clamped_start
    return clamped_start, clamped_end
