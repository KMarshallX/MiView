from __future__ import annotations

import nibabel as nib
import numpy as np

from miview.nifti_io import NiftiLoadResult
from miview.segmentation_validation import validate_segmentation_compatibility


def _make_volume(
    data: np.ndarray,
    affine: np.ndarray,
    *,
    zooms: tuple[float, float, float] = (1.0, 1.0, 1.0),
) -> NiftiLoadResult:
    header = nib.Nifti1Image(data, affine).header.copy()
    header.set_zooms(zooms)
    return NiftiLoadResult(
        data=data,
        affine=affine,
        header=header,
        shape=tuple(int(dim) for dim in data.shape),
        dtype=data.dtype,
    )


def test_validate_segmentation_compatibility_accepts_matching_metadata() -> None:
    image_data = np.zeros((6, 7, 8), dtype=np.float32)
    segmentation_data = np.ones((6, 7, 8), dtype=np.uint8)
    affine = np.array(
        [
            [1.0, 0.0, 0.0, 10.0],
            [0.0, 1.0, 0.0, 20.0],
            [0.0, 0.0, 1.0, 30.0],
            [0.0, 0.0, 0.0, 1.0],
        ]
    )
    image_volume = _make_volume(image_data, affine)
    segmentation_volume = _make_volume(segmentation_data, affine)

    result = validate_segmentation_compatibility(image_volume, segmentation_volume)

    assert result.is_valid


def test_validate_segmentation_compatibility_rejects_shape_mismatch() -> None:
    image_data = np.zeros((6, 7, 8), dtype=np.float32)
    segmentation_data = np.ones((6, 7, 7), dtype=np.uint8)
    affine = np.eye(4)
    image_volume = _make_volume(image_data, affine)
    segmentation_volume = _make_volume(segmentation_data, affine)

    result = validate_segmentation_compatibility(image_volume, segmentation_volume)

    assert not result.is_valid
    assert "Shape mismatch" in result.message


def test_validate_segmentation_compatibility_rejects_orientation_mismatch() -> None:
    image_data = np.zeros((6, 7, 8), dtype=np.float32)
    segmentation_data = np.ones((6, 7, 8), dtype=np.uint8)
    image_affine = np.eye(4)
    segmentation_affine = np.diag([-1.0, 1.0, 1.0, 1.0])
    segmentation_affine[0, 3] = 5.0
    image_volume = _make_volume(image_data, image_affine)
    segmentation_volume = _make_volume(segmentation_data, segmentation_affine)

    result = validate_segmentation_compatibility(image_volume, segmentation_volume)

    assert not result.is_valid
    assert "Orientation mismatch" in result.message


def test_validate_segmentation_compatibility_rejects_voxel_spacing_mismatch() -> None:
    image_data = np.zeros((6, 7, 8), dtype=np.float32)
    segmentation_data = np.ones((6, 7, 8), dtype=np.uint8)
    affine = np.eye(4)
    image_volume = _make_volume(image_data, affine, zooms=(1.0, 1.0, 1.0))
    segmentation_volume = _make_volume(segmentation_data, affine, zooms=(1.0, 1.0, 2.0))

    result = validate_segmentation_compatibility(image_volume, segmentation_volume)

    assert not result.is_valid
    assert "Voxel spacing mismatch" in result.message


def test_validate_segmentation_compatibility_rejects_affine_mismatch() -> None:
    image_data = np.zeros((6, 7, 8), dtype=np.float32)
    segmentation_data = np.ones((6, 7, 8), dtype=np.uint8)
    image_affine = np.eye(4)
    segmentation_affine = np.eye(4)
    segmentation_affine[0, 3] = 1.0
    image_volume = _make_volume(image_data, image_affine)
    segmentation_volume = _make_volume(segmentation_data, segmentation_affine)

    result = validate_segmentation_compatibility(image_volume, segmentation_volume)

    assert not result.is_valid
    assert "Affine mismatch" in result.message