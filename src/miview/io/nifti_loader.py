from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import nibabel as nib
import numpy as np
from nibabel.filebasedimages import ImageFileError


@dataclass(frozen=True)
class NiftiLoadResult:
    data: np.ndarray
    affine: np.ndarray
    header: nib.nifti1.Nifti1Header | nib.nifti2.Nifti2Header
    shape: tuple[int, ...]
    dtype: np.dtype


def load_nifti(path: str | Path) -> NiftiLoadResult:
    """Load a .nii or .nii.gz file and return core image metadata."""
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

    data = np.asanyarray(image.dataobj)
    affine = np.asarray(image.affine)
    header = image.header.copy()
    shape = tuple(data.shape)
    dtype = data.dtype

    return NiftiLoadResult(
        data=data,
        affine=affine,
        header=header,
        shape=shape,
        dtype=dtype,
    )

