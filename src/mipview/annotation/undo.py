from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field

import numpy as np

from mipview.annotation.annotation_mask import AnnotationMask
from mipview.viewer.slice_geometry import Orientation
from mipview.viewer.slice_geometry import plane_axes_for_orientation

Voxel = tuple[int, int, int]


@dataclass(frozen=True)
class AnnotationUndoEntry:
    coordinates: np.ndarray
    old_values: np.ndarray

    @property
    def num_voxels(self) -> int:
        return int(self.coordinates.shape[0])


@dataclass
class PendingAnnotationSnapshot:
    coordinates: np.ndarray
    old_values: np.ndarray


@dataclass
class AnnotationUndoStack:
    _entries: list[AnnotationUndoEntry] = field(default_factory=list)

    def can_undo(self) -> bool:
        return bool(self._entries)

    def clear(self) -> None:
        self._entries.clear()

    def snapshot_disk(
        self,
        mask: AnnotationMask,
        view: Orientation,
        center_voxel: Voxel,
        radius: int,
    ) -> PendingAnnotationSnapshot:
        coordinates = _disk_coordinates(mask.shape, view, center_voxel, radius)
        old_values = mask.data[
            coordinates[:, 0],
            coordinates[:, 1],
            coordinates[:, 2],
        ].copy()
        return PendingAnnotationSnapshot(coordinates=coordinates, old_values=old_values)

    def commit_snapshot(
        self,
        snapshot: PendingAnnotationSnapshot,
        mask: AnnotationMask,
    ) -> AnnotationUndoEntry | None:
        coordinates = snapshot.coordinates
        current_values = mask.data[
            coordinates[:, 0],
            coordinates[:, 1],
            coordinates[:, 2],
        ]
        changed = current_values != snapshot.old_values
        if not np.any(changed):
            return None

        entry = AnnotationUndoEntry(
            coordinates=coordinates[changed].copy(),
            old_values=snapshot.old_values[changed].copy(),
        )
        self._entries.append(entry)
        return entry

    def undo(self, mask: AnnotationMask) -> int:
        if not self._entries:
            return 0

        entry = self._entries.pop()
        coordinates = entry.coordinates
        mask.data[
            coordinates[:, 0],
            coordinates[:, 1],
            coordinates[:, 2],
        ] = entry.old_values
        return entry.num_voxels


def _disk_coordinates(
    shape: tuple[int, int, int],
    view: Orientation,
    center_voxel: Voxel,
    radius: int,
) -> np.ndarray:
    center = _validate_voxel(center_voxel, shape)
    radius_value = _validate_radius(radius)
    plane_axis_a, plane_axis_b, fixed_axis = plane_axes_for_orientation(view)

    ranges = [range(index, index + 1) for index in center]
    ranges[plane_axis_a] = _clipped_axis_range(
        center[plane_axis_a], radius_value, shape[plane_axis_a]
    )
    ranges[plane_axis_b] = _clipped_axis_range(
        center[plane_axis_b], radius_value, shape[plane_axis_b]
    )
    ranges[fixed_axis] = range(center[fixed_axis], center[fixed_axis] + 1)

    radius_squared = radius_value * radius_value
    coordinates: list[Voxel] = []
    for axis_a_index in ranges[plane_axis_a]:
        delta_a = axis_a_index - center[plane_axis_a]
        for axis_b_index in ranges[plane_axis_b]:
            delta_b = axis_b_index - center[plane_axis_b]
            if delta_a * delta_a + delta_b * delta_b > radius_squared:
                continue
            voxel = list(center)
            voxel[plane_axis_a] = axis_a_index
            voxel[plane_axis_b] = axis_b_index
            coordinates.append(tuple(voxel))
    return np.asarray(coordinates, dtype=np.intp)


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


def _validate_radius(radius: int) -> int:
    radius_value = int(radius)
    if radius_value < 0:
        raise ValueError("Brush radius must be non-negative.")
    return radius_value
