from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import nibabel as nib
import numpy as np
from nibabel.filebasedimages import ImageFileError

_CANONICAL_AXCODES = ("R", "P", "I")


@dataclass(frozen=True)
class NiftiLoadResult:
    data: np.ndarray
    affine: np.ndarray
    header: nib.nifti1.Nifti1Header | nib.nifti2.Nifti2Header
    shape: tuple[int, ...]
    dtype: np.dtype


def load_nifti(path: str | Path) -> NiftiLoadResult:
    """Load a .nii or .nii.gz file canonicalized to RPI anatomical axes."""
    file_path = Path(path)

    if not file_path.exists():
        raise FileNotFoundError(f"NIfTI file not found: {file_path}")
    if not file_path.is_file():
        raise ValueError(f"Expected a file path, got: {file_path}")

    name = file_path.name.lower()
    if not (name.endswith(".nii") or name.endswith(".nii.gz")):
        raise ValueError(
            f"Unsupported file type for '{file_path}'. Expected .nii or .nii.gz."
        )

    try:
        image = nib.load(str(file_path))
    except (ImageFileError, OSError) as exc:
        raise ValueError(f"Invalid NIfTI file: {file_path}") from exc

    source_data = np.asanyarray(image.dataobj)
    source_affine = np.asarray(image.affine)
    source_orientation = nib.orientations.io_orientation(source_affine)
    canonical_orientation = nib.orientations.axcodes2ornt(_CANONICAL_AXCODES)
    source_to_canonical = nib.orientations.ornt_transform(
        source_orientation, canonical_orientation
    )
    data = np.asanyarray(
        nib.orientations.apply_orientation(source_data, source_to_canonical)
    )
    affine = source_affine @ nib.orientations.inv_ornt_aff(
        source_to_canonical, source_data.shape[:3]
    )
    header = image.header.copy()
    header.set_data_shape(data.shape)
    _, qform_code = header.get_qform(coded=True)
    _, sform_code = header.get_sform(coded=True)
    header.set_qform(affine, code=int(qform_code))
    header.set_sform(affine, code=int(sform_code))
    shape = tuple(data.shape)
    dtype = data.dtype

    return NiftiLoadResult(
        data=data,
        affine=affine,
        header=header,
        shape=shape,
        dtype=dtype,
    )
