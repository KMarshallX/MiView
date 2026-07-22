from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from mipview.viewer.oriented_volume import OrientedVolume
from mipview.viewer.slice_geometry import (
    Orientation,
    plane_axes_for_orientation,
    plane_definition_for_orientation,
)

DEFAULT_PATCH_SIZE = (64, 64, 10)

ANATOMICAL_DIRECTION_DELTAS = {
    "L": (-1, 0, 0),
    "R": (1, 0, 0),
    "A": (0, -1, 0),
    "P": (0, 1, 0),
    "S": (0, 0, -1),
    "I": (0, 0, 1),
}


@dataclass(frozen=True)
class PatchBounds:
    """Half-open 3D voxel bounds in canonical anatomical (RPI) index space."""

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
    """Shared 3D patch selection state in canonical anatomical (RPI) axes."""

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
        if len(shape) != 3 or any(int(length) <= 0 for length in shape):
            raise ValueError(f"Expected a positive 3D volume shape, got {shape}.")
        self._volume_shape = tuple(int(length) for length in shape)
        if self._center is not None:
            self._center = _clamp_patch_center(
                self._center,
                self._size,
                self._volume_shape,
            )

    def set_center(self, center: tuple[int, int, int]) -> None:
        normalized_center = tuple(int(index) for index in center)
        self._center = (
            normalized_center
            if self._volume_shape is None
            else _clamp_patch_center(
                normalized_center,
                self._size,
                self._volume_shape,
            )
        )

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
        if self._center is not None and self._volume_shape is not None:
            self._center = _clamp_patch_center(
                self._center,
                self._size,
                self._volume_shape,
            )
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


def translate_patch_bounds(
    bounds: PatchBounds,
    delta_xyz: tuple[int, int, int],
    volume_shape: tuple[int, int, int],
) -> tuple[PatchBounds, tuple[int, int, int]]:
    """Translate fixed-size bounds inside a volume and return the applied delta."""
    if len(volume_shape) != 3 or any(int(length) <= 0 for length in volume_shape):
        raise ValueError(f"Expected a positive 3D volume shape, got {volume_shape}.")

    starts = (bounds.x_start, bounds.y_start, bounds.z_start)
    ends = (bounds.x_end, bounds.y_end, bounds.z_end)
    new_starts: list[int] = []
    actual_delta: list[int] = []
    for axis, (start, end, requested_delta, axis_length) in enumerate(
        zip(starts, ends, delta_xyz, volume_shape, strict=True)
    ):
        extent = int(end) - int(start)
        if extent <= 0 or start < 0 or end > axis_length:
            raise ValueError(
                f"Patch bounds are invalid on axis {axis}: "
                f"[{start}, {end}) for length {axis_length}."
            )
        maximum_start = int(axis_length) - extent
        translated_start = min(
            max(int(start) + int(requested_delta), 0),
            maximum_start,
        )
        new_starts.append(translated_start)
        actual_delta.append(translated_start - int(start))

    extents = tuple(end - start for start, end in zip(starts, ends, strict=True))
    translated = PatchBounds(
        x_start=new_starts[0],
        x_end=new_starts[0] + extents[0],
        y_start=new_starts[1],
        y_end=new_starts[1] + extents[1],
        z_start=new_starts[2],
        z_end=new_starts[2] + extents[2],
    )
    return translated, tuple(actual_delta)


def patch_bounds_center(bounds: PatchBounds) -> tuple[int, int, int]:
    """Return the center convention used by fixed-size patch selection."""
    return (
        bounds.x_start + ((bounds.x_end - bounds.x_start) // 2),
        bounds.y_start + ((bounds.y_end - bounds.y_start) // 2),
        bounds.z_start + ((bounds.z_end - bounds.z_start) // 2),
    )


def patch_bounds_shape(bounds: PatchBounds) -> tuple[int, int, int]:
    return (
        bounds.x_end - bounds.x_start,
        bounds.y_end - bounds.y_start,
        bounds.z_end - bounds.z_start,
    )


def anatomical_direction_delta(
    direction: str,
    voxels: int = 1,
) -> tuple[int, int, int]:
    normalized_direction = str(direction).strip().upper()
    if normalized_direction not in ANATOMICAL_DIRECTION_DELTAS:
        raise ValueError("Patch direction must be L, R, A, P, S, or I.")
    normalized_voxels = int(voxels)
    if normalized_voxels <= 0:
        raise ValueError("Patch translation voxels must be positive.")
    unit_delta = ANATOMICAL_DIRECTION_DELTAS[normalized_direction]
    return tuple(component * normalized_voxels for component in unit_delta)


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
    if orientation == "coronal":
        return (0, 2)
    if orientation == "sagittal":
        return (1, 2)
    raise ValueError(f"Unsupported orientation: {orientation}")


def axis_for_resize_edge(orientation: Orientation, edge: str) -> int | None:
    if edge in ("top", "bottom"):
        if orientation == "axial":
            return 1
        if orientation in ("coronal", "sagittal"):
            return 2
        raise ValueError(f"Unsupported orientation: {orientation}")

    if edge in ("left", "right"):
        if orientation in ("axial", "coronal"):
            return 0
        if orientation == "sagittal":
            return 1
        raise ValueError(f"Unsupported orientation: {orientation}")

    if orientation not in ("axial", "coronal", "sagittal"):
        raise ValueError(f"Unsupported orientation: {orientation}")
    return None


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
    if axis_length <= 0:
        raise ValueError(f"Patch axis length must be positive, got {axis_length}.")
    effective_size = min(_clamp_patch_size(size), int(axis_length))
    requested_start = int(center) - (effective_size // 2)
    start = min(max(requested_start, 0), int(axis_length) - effective_size)
    return start, start + effective_size


def _clamp_patch_center(
    center: tuple[int, int, int],
    size: tuple[int, int, int],
    volume_shape: tuple[int, int, int],
) -> tuple[int, int, int]:
    clamped: list[int] = []
    for center_index, requested_size, axis_length in zip(
        center,
        size,
        volume_shape,
        strict=True,
    ):
        effective_size = min(_clamp_patch_size(requested_size), int(axis_length))
        lower = effective_size // 2
        upper = int(axis_length) - (effective_size - lower)
        clamped.append(min(max(int(center_index), lower), upper))
    return tuple(clamped)


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
