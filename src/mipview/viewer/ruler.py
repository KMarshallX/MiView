from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class RulerScale:
    """A physical ruler length and its rendered label."""

    length_mm: float
    label: str


@dataclass(frozen=True)
class RulerGeometry:
    """Selected physical scale and its current on-screen length."""

    scale: RulerScale
    pixel_length: float


RULER_SCALES = (
    RulerScale(10.0, "1 cm"),
    RulerScale(1.0, "1 mm"),
    RulerScale(0.1, "100 µm"),
    RulerScale(0.01, "10 µm"),
)

_SPATIAL_UNIT_TO_MM = {
    "meter": 1000.0,
    "mm": 1.0,
    "micron": 0.001,
    "unknown": 1.0,
}


def select_ruler_geometry(
    pixels_per_mm: float,
    viewport_width: int,
    *,
    maximum_width_fraction: float = 0.25,
) -> RulerGeometry | None:
    """Choose the largest supported scale that fits the allowed viewport width."""
    if (
        not np.isfinite(pixels_per_mm)
        or pixels_per_mm <= 0.0
        or viewport_width <= 0
        or not 0.0 < maximum_width_fraction <= 1.0
    ):
        return None

    maximum_pixel_length = float(viewport_width) * maximum_width_fraction
    for scale in RULER_SCALES:
        pixel_length = scale.length_mm * pixels_per_mm
        if pixel_length <= maximum_pixel_length:
            return RulerGeometry(scale=scale, pixel_length=pixel_length)

    smallest_scale = RULER_SCALES[-1]
    return RulerGeometry(
        scale=smallest_scale,
        pixel_length=smallest_scale.length_mm * pixels_per_mm,
    )


def display_voxel_spacing_mm(
    source_affine: np.ndarray,
    display_to_source_affine: np.ndarray,
    spatial_unit_to_mm: float = 1.0,
) -> tuple[float, float, float]:
    """Return voxel spacing along canonical display axes in millimetres."""
    display_affine = np.asarray(source_affine) @ np.asarray(display_to_source_affine)
    spacings = np.linalg.norm(display_affine[:3, :3], axis=0) * spatial_unit_to_mm
    return tuple(float(spacing) for spacing in spacings)


def spatial_unit_to_mm(spatial_unit: str) -> float:
    """Return the millimetre conversion for a NIfTI spatial unit."""
    return _SPATIAL_UNIT_TO_MM.get(str(spatial_unit), 1.0)
