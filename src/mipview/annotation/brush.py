from __future__ import annotations

from collections.abc import Iterable

import numpy as np

from mipview.annotation.annotation_mask import AnnotationMask
from mipview.viewer.slice_geometry import Orientation
from mipview.viewer.slice_geometry import plane_axes_for_orientation

Voxel = tuple[int, int, int]


def paint_voxel(mask: AnnotationMask, x: int, y: int, z: int, label: int) -> int:
    """Set one voxel to a positive annotation label."""
    label_value = _validate_label(mask, label)
    voxel = _validate_voxel((x, y, z), mask.shape)
    return _set_voxel(mask.data, voxel, label_value)


def erase_voxel(mask: AnnotationMask, x: int, y: int, z: int) -> int:
    """Set one voxel to background label 0."""
    voxel = _validate_voxel((x, y, z), mask.shape)
    return _set_voxel(mask.data, voxel, 0)


def paint_disk(
    mask: AnnotationMask,
    view: Orientation,
    center_voxel: Voxel,
    radius: int,
    label: int,
) -> int:
    """Paint a circular disk on the requested voxel-space slice plane."""
    label_value = _validate_label(mask, label)
    return _apply_disk(mask, view, center_voxel, radius, label_value)


def erase_disk(
    mask: AnnotationMask,
    view: Orientation,
    center_voxel: Voxel,
    radius: int,
) -> int:
    """Erase a circular disk on the requested voxel-space slice plane."""
    return _apply_disk(mask, view, center_voxel, radius, 0)


def paint_stroke(
    mask: AnnotationMask,
    view: Orientation,
    points: Iterable[Voxel],
    radius: int,
    label: int,
) -> int:
    """Paint disks along a voxel-space stroke."""
    label_value = _validate_label(mask, label)
    return _apply_stroke(mask, view, points, radius, label_value)


def erase_stroke(
    mask: AnnotationMask,
    view: Orientation,
    points: Iterable[Voxel],
    radius: int,
) -> int:
    """Erase disks along a voxel-space stroke."""
    return _apply_stroke(mask, view, points, radius, 0)


def _apply_stroke(
    mask: AnnotationMask,
    view: Orientation,
    points: Iterable[Voxel],
    radius: int,
    value: int,
) -> int:
    _validate_radius(radius)
    stroke_points = [_validate_voxel(point, mask.shape) for point in points]
    if not stroke_points:
        return 0

    changed = 0
    for point in _interpolated_stroke_points(stroke_points):
        changed += _apply_disk(mask, view, point, radius, value)
    return changed


def _apply_disk(
    mask: AnnotationMask,
    view: Orientation,
    center_voxel: Voxel,
    radius: int,
    value: int,
) -> int:
    center = _validate_voxel(center_voxel, mask.shape)
    radius_value = _validate_radius(radius)
    plane_axis_a, plane_axis_b, fixed_axis = plane_axes_for_orientation(view)

    ranges = [range(index, index + 1) for index in center]
    ranges[plane_axis_a] = _clipped_axis_range(
        center[plane_axis_a], radius_value, mask.shape[plane_axis_a]
    )
    ranges[plane_axis_b] = _clipped_axis_range(
        center[plane_axis_b], radius_value, mask.shape[plane_axis_b]
    )
    ranges[fixed_axis] = range(center[fixed_axis], center[fixed_axis] + 1)

    radius_squared = radius_value * radius_value
    changed = 0
    for axis_a_index in ranges[plane_axis_a]:
        delta_a = axis_a_index - center[plane_axis_a]
        for axis_b_index in ranges[plane_axis_b]:
            delta_b = axis_b_index - center[plane_axis_b]
            if delta_a * delta_a + delta_b * delta_b > radius_squared:
                continue

            voxel = list(center)
            voxel[plane_axis_a] = axis_a_index
            voxel[plane_axis_b] = axis_b_index
            changed += _set_voxel(mask.data, tuple(voxel), value)
    return changed


def _set_voxel(data: np.ndarray, voxel: Voxel, value: int) -> int:
    if int(data[voxel]) == value:
        return 0
    data[voxel] = value
    return 1


def _interpolated_stroke_points(points: list[Voxel]) -> list[Voxel]:
    if len(points) == 1:
        return points

    interpolated: list[Voxel] = []
    seen: set[Voxel] = set()
    for start, end in zip(points, points[1:]):
        deltas = [end[axis] - start[axis] for axis in range(3)]
        steps = max(abs(delta) for delta in deltas)
        if steps == 0:
            candidates = [start]
        else:
            candidates = [
                tuple(
                    int(round(start[axis] + deltas[axis] * step / steps))
                    for axis in range(3)
                )
                for step in range(steps + 1)
            ]

        for candidate in candidates:
            if candidate not in seen:
                interpolated.append(candidate)
                seen.add(candidate)
    return interpolated


def _clipped_axis_range(center_index: int, radius: int, axis_size: int) -> range:
    start = max(center_index - radius, 0)
    end = min(center_index + radius + 1, axis_size)
    return range(start, end)


def _validate_voxel(voxel: Voxel, shape: tuple[int, int, int]) -> Voxel:
    if len(voxel) != 3:
        raise ValueError(f"Expected a 3D voxel coordinate, got {voxel}.")

    validated = tuple(int(index) for index in voxel)
    if any(index < 0 or index >= shape[axis] for axis, index in enumerate(validated)):
        raise ValueError(
            f"Voxel coordinate {validated} is outside annotation mask shape {shape}."
        )
    return validated


def _validate_label(mask: AnnotationMask, label: int) -> int:
    label_value = int(label)
    if label_value <= 0:
        raise ValueError("Paint label must be greater than 0; use erase for background.")
    dtype_info = np.iinfo(mask.data.dtype)
    if label_value > dtype_info.max:
        raise ValueError(
            f"Paint label {label_value} is too large for annotation dtype {mask.data.dtype}."
        )
    return label_value


def _validate_radius(radius: int) -> int:
    radius_value = int(radius)
    if radius_value < 0:
        raise ValueError("Brush radius must be non-negative.")
    return radius_value
