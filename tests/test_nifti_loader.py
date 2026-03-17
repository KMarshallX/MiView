from __future__ import annotations

import nibabel as nib
import numpy as np
import pytest

from mipview.nifti_io import load_nifti


def test_load_nifti_returns_expected_fields(tmp_path) -> None:
    data = np.arange(24, dtype=np.int16).reshape(2, 3, 4)
    affine = np.array(
        [
            [1.0, 0.0, 0.0, 10.0],
            [0.0, 1.0, 0.0, 20.0],
            [0.0, 0.0, 1.0, 30.0],
            [0.0, 0.0, 0.0, 1.0],
        ]
    )
    image = nib.Nifti1Image(data, affine)
    file_path = tmp_path / "sample.nii.gz"
    nib.save(image, str(file_path))

    loaded = load_nifti(file_path)
    source_orientation = nib.orientations.io_orientation(affine)
    canonical_orientation = nib.orientations.axcodes2ornt(("R", "P", "I"))
    source_to_canonical = nib.orientations.ornt_transform(
        source_orientation, canonical_orientation
    )
    expected_data = nib.orientations.apply_orientation(data, source_to_canonical)
    expected_affine = affine @ nib.orientations.inv_ornt_aff(
        source_to_canonical, data.shape
    )

    assert loaded.shape == data.shape
    assert loaded.dtype == data.dtype
    np.testing.assert_array_equal(loaded.data, expected_data)
    np.testing.assert_array_equal(loaded.affine, expected_affine)
    assert nib.orientations.aff2axcodes(loaded.affine) == ("R", "P", "I")
    assert loaded.header["dim"][0] == 3


def test_load_nifti_rejects_non_nifti_extension(tmp_path) -> None:
    file_path = tmp_path / "not_nifti.txt"
    file_path.write_text("test", encoding="utf-8")

    with pytest.raises(ValueError, match=r"Expected \.nii or \.nii\.gz"):
        load_nifti(file_path)


def test_load_nifti_rejects_corrupted_nifti_file(tmp_path) -> None:
    file_path = tmp_path / "broken.nii"
    file_path.write_text("not-a-real-nifti", encoding="utf-8")

    with pytest.raises(ValueError, match=r"Invalid NIfTI file"):
        load_nifti(file_path)
