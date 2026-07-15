from __future__ import annotations

import nibabel as nib
import numpy as np


_DIRECTION_RANGE_BY_AXIS_CODE = {
    "R": "L-R",
    "L": "R-L",
    "A": "P-A",
    "P": "A-P",
    "S": "I-S",
    "I": "S-I",
}


def physical_axis_direction_labels(affine: np.ndarray) -> tuple[str, str, str]:
    """Return increasing voxel-axis directions formatted as anatomical ranges."""
    affine_array = np.asarray(affine, dtype=np.float64)
    if affine_array.shape != (4, 4):
        raise ValueError(f"Expected a 4x4 affine, got shape {affine_array.shape}.")

    axis_codes = nib.aff2axcodes(affine_array)
    return tuple(
        _DIRECTION_RANGE_BY_AXIS_CODE.get(axis_code, "?")
        for axis_code in axis_codes
    )
