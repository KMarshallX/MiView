from __future__ import annotations

import nibabel as nib
import numpy as np

from miview.nifti_io import NiftiLoadResult
from miview.patch_extractor import extract_patch
from miview.patch_selector import PatchBounds


def test_extract_patch_returns_data_and_shifted_affine() -> None:
    data = np.arange(7 * 8 * 9, dtype=np.int32).reshape((7, 8, 9))
    affine = np.array(
        [
            [2.0, 0.0, 0.0, 10.0],
            [0.0, 3.0, 0.0, 20.0],
            [0.0, 0.0, 4.0, 30.0],
            [0.0, 0.0, 0.0, 1.0],
        ]
    )
    volume = NiftiLoadResult(
        data=data,
        affine=affine,
        header=nib.Nifti1Image(data, affine).header,
        shape=data.shape,
        dtype=data.dtype,
    )
    bounds = PatchBounds(2, 6, 1, 5, 3, 7)

    patch = extract_patch(volume, bounds)

    np.testing.assert_array_equal(patch.data, data[2:6, 1:5, 3:7])
    assert patch.shape == (4, 4, 4)
    np.testing.assert_array_equal(
        patch.affine,
        np.array(
            [
                [2.0, 0.0, 0.0, 14.0],
                [0.0, 3.0, 0.0, 23.0],
                [0.0, 0.0, 4.0, 42.0],
                [0.0, 0.0, 0.0, 1.0],
            ]
        ),
    )
