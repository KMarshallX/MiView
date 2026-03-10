from __future__ import annotations

from typing import Literal

import numpy as np

Orientation = Literal["axial", "coronal", "sagittal"]


def center_cursor_for_volume(shape: tuple[int, int, int]) -> tuple[int, int, int]:
    """Return the logical center cursor as (x, y, z)."""
    if len(shape) != 3:
        raise ValueError(f"Expected a 3D shape, got {shape}.")
    return (shape[1] // 2, shape[0] // 2, shape[2] // 2)


def clamp_cursor_to_volume(
    cursor: tuple[int, int, int], shape: tuple[int, int, int]
) -> tuple[int, int, int]:
    x, y, z = cursor
    return (
        min(max(x, 0), shape[1] - 1),
        min(max(y, 0), shape[0] - 1),
        min(max(z, 0), shape[2] - 1),
    )


def plane_axes_for_orientation(orientation: Orientation) -> tuple[int, int, int]:
    """
    Return (horizontal_axis, vertical_axis, fixed_axis) in logical cursor space.

    Logical cursor axes are ordered as (x, y, z).
    """
    if orientation == "axial":
        return (0, 1, 2)
    if orientation == "coronal":
        return (0, 2, 1)
    if orientation == "sagittal":
        return (1, 2, 0)
    raise ValueError(f"Unsupported orientation: {orientation}")


def extract_oriented_slice(
    volume: np.ndarray,
    orientation: Orientation,
    cursor: tuple[int, int, int],
) -> np.ndarray:
    """Extract a 2D slice for the given orientation and logical cursor."""
    x_index, y_index, z_index = clamp_cursor_to_volume(cursor, tuple(volume.shape))

    if orientation == "axial":
        return volume[:, :, z_index]
    if orientation == "coronal":
        return volume[y_index, :, :].T
    if orientation == "sagittal":
        return volume[:, x_index, :].T
    raise ValueError(f"Unsupported orientation: {orientation}")


def map_plane_fraction_to_cursor(
    orientation: Orientation,
    shape: tuple[int, int, int],
    current_cursor: tuple[int, int, int],
    horizontal_fraction: float,
    vertical_fraction: float,
) -> tuple[int, int, int]:
    """
    Map normalized 2D plane coordinates back into logical voxel coordinates.

    Fractions are in the inclusive range [0.0, 1.0) along the displayed slice.
    """
    cursor = list(clamp_cursor_to_volume(current_cursor, shape))
    horizontal_axis, vertical_axis, _ = plane_axes_for_orientation(orientation)

    cursor[horizontal_axis] = _fraction_to_index(horizontal_fraction, shape, horizontal_axis)
    cursor[vertical_axis] = _fraction_to_index(vertical_fraction, shape, vertical_axis)
    return tuple(cursor)


def map_cursor_to_plane_indices(
    orientation: Orientation, cursor: tuple[int, int, int]
) -> tuple[int, int]:
    """Project a logical cursor into plane-local (horizontal, vertical) indices."""
    horizontal_axis, vertical_axis, _ = plane_axes_for_orientation(orientation)
    return cursor[horizontal_axis], cursor[vertical_axis]


def _fraction_to_index(
    fraction: float, shape: tuple[int, int, int], logical_axis: int
) -> int:
    logical_sizes = (shape[1], shape[0], shape[2])
    axis_size = logical_sizes[logical_axis]
    clamped_fraction = min(max(fraction, 0.0), np.nextafter(1.0, 0.0))
    return int(clamped_fraction * axis_size)
