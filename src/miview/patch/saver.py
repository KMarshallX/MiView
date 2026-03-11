from __future__ import annotations

from pathlib import Path

import nibabel as nib
import numpy as np

from miview.io.nifti_loader import NiftiLoadResult


def build_patch_default_filename(
    source_image_name: str,
    patch_center: tuple[int, int, int],
    patch_size: tuple[int, int, int],
    extension: str = ".nii.gz",
) -> str:
    """Build an informative default patch filename for the save dialog."""
    if extension not in (".nii", ".nii.gz"):
        raise ValueError(f"Unsupported extension '{extension}'. Use .nii or .nii.gz.")

    source_stem = _strip_nifti_suffix(Path(source_image_name).name) or "image"
    cx, cy, cz = patch_center
    sx, sy, sz = patch_size
    return (
        f"{source_stem}_patch_center-{cx}-{cy}-{cz}_size-{sx}x{sy}x{sz}{extension}"
    )


def save_patch_nifti(
    patch_volume: NiftiLoadResult,
    destination_path: str | Path,
) -> Path:
    """Save an extracted patch as NIfTI with spatial metadata aligned to source space."""
    output_path = Path(destination_path)
    if not str(output_path).lower().endswith((".nii", ".nii.gz")):
        raise ValueError("Patch path must end with .nii or .nii.gz.")

    header = patch_volume.header.copy()
    header.set_data_shape(patch_volume.data.shape)

    # Preserve qform/sform codes where available, but always write patch affine
    # so voxel (0,0,0) maps to the cropped patch origin in world space.
    _, qform_code = header.get_qform(coded=True)
    _, sform_code = header.get_sform(coded=True)
    q_code = int(qform_code) if qform_code else 1
    s_code = int(sform_code) if sform_code else 1

    affine = np.asarray(patch_volume.affine, dtype=np.float64)
    data = np.asarray(patch_volume.data)
    image = nib.Nifti1Image(data, affine, header=header)
    image.header.set_qform(affine, code=q_code)
    image.header.set_sform(affine, code=s_code)
    nib.save(image, str(output_path))
    return output_path


def _strip_nifti_suffix(filename: str) -> str:
    lower = filename.lower()
    if lower.endswith(".nii.gz"):
        return filename[:-7]
    if lower.endswith(".nii"):
        return filename[:-4]
    return Path(filename).stem
