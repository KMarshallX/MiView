from __future__ import annotations

import numpy as np

from miview.io.nifti_loader import NiftiLoadResult
from miview.patch.selector import PatchBounds


def extract_patch(volume: NiftiLoadResult, bounds: PatchBounds) -> NiftiLoadResult:
    """Extract a clipped 3D patch using source-space half-open bounds."""
    patch_data = np.asarray(volume.data[bounds.as_slices()]).copy()

    patch_affine = np.asarray(volume.affine).copy()
    origin_shift = np.array([bounds.x_start, bounds.y_start, bounds.z_start, 1.0], dtype=np.float64)
    patch_affine[:3, 3] = (volume.affine @ origin_shift)[:3]

    patch_header = volume.header.copy()
    patch_header.set_data_shape(patch_data.shape)

    return NiftiLoadResult(
        data=patch_data,
        affine=patch_affine,
        header=patch_header,
        shape=tuple(int(dim) for dim in patch_data.shape),
        dtype=patch_data.dtype,
    )
