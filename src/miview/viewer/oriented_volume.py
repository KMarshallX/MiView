from __future__ import annotations

from dataclasses import dataclass

import nibabel as nib
import numpy as np


@dataclass(frozen=True)
class OrientedVolume:
    """Volume reoriented to canonical RAS display space with explicit index mapping."""

    source_data: np.ndarray
    display_data: np.ndarray
    affine: np.ndarray
    source_shape: tuple[int, int, int]
    display_shape: tuple[int, int, int]
    source_to_display_ornt: np.ndarray
    display_to_source_ornt: np.ndarray
    source_to_display_affine: np.ndarray
    display_to_source_affine: np.ndarray

    def source_to_display(self, source_index: tuple[int, int, int]) -> tuple[int, int, int]:
        return _map_index(source_index, self.source_to_display_affine)

    def display_to_source(self, display_index: tuple[int, int, int]) -> tuple[int, int, int]:
        return _map_index(display_index, self.display_to_source_affine)


def build_oriented_volume(data: np.ndarray, affine: np.ndarray) -> OrientedVolume:
    """Reorient raw NIfTI data into canonical RAS display space."""
    if data.ndim != 3:
        raise ValueError(f"Expected 3D NIfTI data, got {data.ndim}D.")

    source_shape = tuple(int(size) for size in data.shape)
    source_orientation = nib.orientations.io_orientation(affine)
    ras_orientation = nib.orientations.axcodes2ornt(("R", "A", "S"))
    source_to_display = nib.orientations.ornt_transform(source_orientation, ras_orientation)
    display_to_source = nib.orientations.ornt_transform(ras_orientation, source_orientation)
    display_data = nib.orientations.apply_orientation(data, source_to_display)
    display_to_source_affine = nib.orientations.inv_ornt_aff(source_to_display, source_shape)
    source_to_display_affine = np.linalg.inv(display_to_source_affine)

    return OrientedVolume(
        source_data=np.asarray(data),
        display_data=np.asarray(display_data),
        affine=np.asarray(affine),
        source_shape=source_shape,
        display_shape=tuple(int(size) for size in display_data.shape),
        source_to_display_ornt=source_to_display,
        display_to_source_ornt=display_to_source,
        source_to_display_affine=source_to_display_affine,
        display_to_source_affine=display_to_source_affine,
    )


def _map_index(
    index: tuple[int, int, int],
    affine: np.ndarray,
) -> tuple[int, int, int]:
    homogeneous_index = np.array([index[0], index[1], index[2], 1.0], dtype=np.float64)
    mapped = affine @ homogeneous_index
    return (int(round(mapped[0])), int(round(mapped[1])), int(round(mapped[2])))
