from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

Orientation = Literal["axial", "coronal", "sagittal"]


@dataclass(frozen=True)
class DisplayRect:
    left: float
    top: float
    width: float
    height: float


@dataclass(frozen=True)
class PlaneDefinition:
    horizontal_axis: int
    vertical_axis: int
    fixed_axis: int
    horizontal_flipped: bool
    vertical_flipped: bool


@dataclass(frozen=True)
class OrientationIndicators:
    left: str
    right: str
    top: str
    bottom: str


_AXIS_DIRECTION_CODES: dict[int, tuple[str, str]] = {
    0: ("L", "R"),
    1: ("P", "A"),
    2: ("I", "S"),
}


def center_cursor_for_volume(shape: tuple[int, int, int]) -> tuple[int, int, int]:
    """Return the logical center cursor as (x, y, z)."""
    if len(shape) != 3:
        raise ValueError(f"Expected a 3D shape, got {shape}.")
    return (shape[0] // 2, shape[1] // 2, shape[2] // 2)


def clamp_cursor_to_volume(
    cursor: tuple[int, int, int], shape: tuple[int, int, int]
) -> tuple[int, int, int]:
    x, y, z = cursor
    return (
        min(max(x, 0), shape[0] - 1),
        min(max(y, 0), shape[1] - 1),
        min(max(z, 0), shape[2] - 1),
    )


def plane_axes_for_orientation(orientation: Orientation) -> tuple[int, int, int]:
    """Return (horizontal_axis, vertical_axis, fixed_axis) in display RAS space."""
    plane_definition = plane_definition_for_orientation(orientation)
    return (
        plane_definition.horizontal_axis,
        plane_definition.vertical_axis,
        plane_definition.fixed_axis,
    )


def plane_definition_for_orientation(orientation: Orientation) -> PlaneDefinition:
    """
    Return the displayed plane definition in canonical RAS display space.

    Canonical display space axes are:
    - axis 0: left/right
    - axis 1: posterior/anterior
    - axis 2: inferior/superior

    Display conventions:
    - axial and coronal use radiological left-right display
    - sagittal uses anterior on the viewer left and superior at the top
    """
    if orientation == "axial":
        return PlaneDefinition(
            horizontal_axis=0,
            vertical_axis=1,
            fixed_axis=2,
            horizontal_flipped=True,
            vertical_flipped=True,
        )
    if orientation == "coronal":
        return PlaneDefinition(
            horizontal_axis=0,
            vertical_axis=2,
            fixed_axis=1,
            horizontal_flipped=True,
            vertical_flipped=True,
        )
    if orientation == "sagittal":
        return PlaneDefinition(
            horizontal_axis=1,
            vertical_axis=2,
            fixed_axis=0,
            horizontal_flipped=True,
            vertical_flipped=True,
        )
    raise ValueError(f"Unsupported orientation: {orientation}")


def extract_oriented_slice(
    volume: np.ndarray,
    orientation: Orientation,
    cursor: tuple[int, int, int],
) -> np.ndarray:
    """Extract a 2D slice from canonical RAS data using display orientation rules."""
    x_index, y_index, z_index = clamp_cursor_to_volume(cursor, tuple(volume.shape))

    if orientation == "axial":
        return volume[:, :, z_index].T[::-1, ::-1]
    if orientation == "coronal":
        return volume[:, y_index, :].T[::-1, ::-1]
    if orientation == "sagittal":
        return volume[x_index, :, :].T[::-1, ::-1]
    raise ValueError(f"Unsupported orientation: {orientation}")


def orientation_indicators_for_orientation(orientation: Orientation) -> OrientationIndicators:
    """Return boundary orientation labels for the displayed plane."""
    plane_definition = plane_definition_for_orientation(orientation)
    horizontal_codes = _AXIS_DIRECTION_CODES[plane_definition.horizontal_axis]
    vertical_codes = _AXIS_DIRECTION_CODES[plane_definition.vertical_axis]

    if plane_definition.horizontal_flipped:
        left, right = horizontal_codes[1], horizontal_codes[0]
    else:
        left, right = horizontal_codes[0], horizontal_codes[1]

    if plane_definition.vertical_flipped:
        top, bottom = vertical_codes[1], vertical_codes[0]
    else:
        top, bottom = vertical_codes[0], vertical_codes[1]

    return OrientationIndicators(left=left, right=right, top=top, bottom=bottom)


def step_cursor_slice(
    orientation: Orientation,
    shape: tuple[int, int, int],
    current_cursor: tuple[int, int, int],
    delta: int,
) -> tuple[int, int, int]:
    """Move the cursor along the orientation's fixed axis by delta slices."""
    cursor = list(clamp_cursor_to_volume(current_cursor, shape))
    fixed_axis = plane_definition_for_orientation(orientation).fixed_axis
    cursor[fixed_axis] = min(max(cursor[fixed_axis] + delta, 0), shape[fixed_axis] - 1)
    return tuple(cursor)


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
    plane_definition = plane_definition_for_orientation(orientation)

    horizontal_index = _fraction_to_index(
        horizontal_fraction, shape[plane_definition.horizontal_axis]
    )
    vertical_index = _fraction_to_index(
        vertical_fraction, shape[plane_definition.vertical_axis]
    )
    if plane_definition.horizontal_flipped:
        horizontal_index = shape[plane_definition.horizontal_axis] - 1 - horizontal_index
    if plane_definition.vertical_flipped:
        vertical_index = shape[plane_definition.vertical_axis] - 1 - vertical_index

    cursor[plane_definition.horizontal_axis] = horizontal_index
    cursor[plane_definition.vertical_axis] = vertical_index
    return tuple(cursor)


def map_cursor_to_plane_indices(
    orientation: Orientation, cursor: tuple[int, int, int], shape: tuple[int, int, int]
) -> tuple[int, int]:
    """Project a canonical RAS cursor into displayed plane-local indices."""
    plane_definition = plane_definition_for_orientation(orientation)
    horizontal_index = cursor[plane_definition.horizontal_axis]
    vertical_index = cursor[plane_definition.vertical_axis]

    if plane_definition.horizontal_flipped:
        horizontal_index = shape[plane_definition.horizontal_axis] - 1 - horizontal_index
    if plane_definition.vertical_flipped:
        vertical_index = shape[plane_definition.vertical_axis] - 1 - vertical_index
    return horizontal_index, vertical_index


def plane_shape_for_orientation(
    volume_shape: tuple[int, int, int], orientation: Orientation
) -> tuple[int, int]:
    plane_definition = plane_definition_for_orientation(orientation)
    return (
        volume_shape[plane_definition.horizontal_axis],
        volume_shape[plane_definition.vertical_axis],
    )


def compute_display_rect(
    image_size: tuple[int, int],
    viewport_size: tuple[int, int],
    base_scale: float,
    zoom_factor: float,
    pan_offset: tuple[float, float],
) -> DisplayRect | None:
    """
    Compute the image draw rectangle in viewport coordinates.

    The image size is scaled by a shared fit scale, then by the shared zoom
    factor, then translated by the per-view pan offset.
    """
    image_width, image_height = image_size
    if (
        image_width <= 0
        or image_height <= 0
        or viewport_size[0] <= 0
        or viewport_size[1] <= 0
        or base_scale <= 0
    ):
        return None

    viewport_width, viewport_height = viewport_size
    display_width = image_width * base_scale * zoom_factor
    display_height = image_height * base_scale * zoom_factor
    pan_x, pan_y = pan_offset

    return DisplayRect(
        left=((viewport_width - display_width) / 2.0) + pan_x,
        top=((viewport_height - display_height) / 2.0) + pan_y,
        width=display_width,
        height=display_height,
    )


def map_label_position_to_plane_fraction(
    label_position: tuple[float, float], display_rect: DisplayRect
) -> tuple[float, float] | None:
    """Map a viewport position back into normalized plane coordinates."""
    rect_x = label_position[0] - display_rect.left
    rect_y = label_position[1] - display_rect.top
    if (
        rect_x < 0
        or rect_y < 0
        or rect_x >= display_rect.width
        or rect_y >= display_rect.height
    ):
        return None

    return rect_x / display_rect.width, rect_y / display_rect.height


def compute_shared_base_scale(
    plane_sizes: list[tuple[int, int]],
    viewport_sizes: list[tuple[int, int]],
) -> float:
    """Compute one shared fit scale that allows every plane to fit its viewport."""
    fit_candidates: list[float] = []
    for plane_size, viewport_size in zip(plane_sizes, viewport_sizes, strict=True):
        plane_width, plane_height = plane_size
        viewport_width, viewport_height = viewport_size
        if (
            plane_width <= 0
            or plane_height <= 0
            or viewport_width <= 0
            or viewport_height <= 0
        ):
            continue
        fit_candidates.append(min(viewport_width / plane_width, viewport_height / plane_height))

    if not fit_candidates:
        return 1.0
    return min(fit_candidates)


def map_plane_indices_to_label_position(
    plane_indices: tuple[int, int],
    plane_shape: tuple[int, int],
    display_rect: DisplayRect,
) -> tuple[int, int]:
    """Map plane-local integer indices to viewport pixels."""
    horizontal_index, vertical_index = plane_indices
    plane_width, plane_height = plane_shape

    return (
        _index_to_display_pixel(horizontal_index, plane_width, display_rect.left, display_rect.width),
        _index_to_display_pixel(vertical_index, plane_height, display_rect.top, display_rect.height),
    )


def _fraction_to_index(
    fraction: float, axis_size: int
) -> int:
    clamped_fraction = min(max(fraction, 0.0), np.nextafter(1.0, 0.0))
    return int(clamped_fraction * axis_size)


def _index_to_display_pixel(
    index: int, axis_size: int, rect_origin: float, rect_size: float
) -> int:
    if axis_size <= 1 or rect_size <= 1:
        return int(rect_origin)

    centered_fraction = (index + 0.5) / axis_size
    return int(rect_origin + min(centered_fraction * rect_size, rect_size - 1))
