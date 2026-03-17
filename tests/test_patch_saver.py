from __future__ import annotations

import nibabel as nib
import numpy as np

from mipview.nifti_io import NiftiLoadResult
from mipview.patch_saver import build_patch_default_filename, save_patch_nifti


def test_build_patch_default_filename_includes_source_center_size() -> None:
    filename = build_patch_default_filename(
        source_image_name="brain_scan.nii.gz",
        patch_center=(12, 34, 56),
        patch_size=(64, 64, 10),
        extension=".nii",
    )
    assert filename == "brain_scan_patch_center-12-34-56_size-64x64x10.nii"


def test_save_patch_nifti_round_trip_preserves_data_and_affine(tmp_path) -> None:
    data = np.arange(4 * 5 * 6, dtype=np.float32).reshape((4, 5, 6))
    affine = np.array(
        [
            [2.0, 0.0, 0.0, 100.0],
            [0.0, 2.5, 0.0, 200.0],
            [0.0, 0.0, 3.0, 300.0],
            [0.0, 0.0, 0.0, 1.0],
        ]
    )
    header = nib.Nifti1Image(data, affine).header
    volume = NiftiLoadResult(
        data=data,
        affine=affine,
        header=header,
        shape=data.shape,
        dtype=data.dtype,
    )
    out_path = tmp_path / "saved_patch.nii.gz"

    save_patch_nifti(volume, out_path)
    reloaded = nib.load(str(out_path))

    np.testing.assert_array_equal(np.asanyarray(reloaded.dataobj), data)
    np.testing.assert_array_equal(reloaded.affine, affine)
    assert tuple(int(v) for v in reloaded.shape) == data.shape
    _, qform_code = reloaded.header.get_qform(coded=True)
    _, sform_code = reloaded.header.get_sform(coded=True)
    assert int(qform_code) > 0
    assert int(sform_code) > 0
