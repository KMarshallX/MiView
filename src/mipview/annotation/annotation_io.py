from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import nibabel as nib
import numpy as np

from mipview.annotation.annotation_mask import AnnotationMask
from mipview.nifti_io import NiftiLoadResult
from mipview.nifti_io import load_nifti


@dataclass(frozen=True)
class AnnotationCompatibilityResult:
    is_valid: bool
    message: str


def validate_annotation_compatibility(
    source_volume: NiftiLoadResult,
    annotation_volume: NiftiLoadResult,
    *,
    affine_atol: float = 1e-4,
    zoom_atol: float = 1e-4,
) -> AnnotationCompatibilityResult:
    source_data = np.asarray(source_volume.data)
    annotation_data = np.asarray(annotation_volume.data)

    if source_data.ndim != 3:
        return AnnotationCompatibilityResult(
            False,
            f"Source image is {source_data.ndim}D; annotation masks require a 3D source image.",
        )

    if annotation_data.ndim != 3:
        return AnnotationCompatibilityResult(
            False,
            f"Annotation mask is {annotation_data.ndim}D; expected a 3D mask volume.",
        )

    if not np.issubdtype(annotation_data.dtype, np.integer):
        return AnnotationCompatibilityResult(
            False,
            f"Annotation mask dtype must be integer, got {annotation_data.dtype}.",
        )

    if source_volume.shape != annotation_volume.shape:
        return AnnotationCompatibilityResult(
            False,
            (
                "Shape mismatch between source image and annotation mask. "
                f"Source shape={source_volume.shape}, annotation shape={annotation_volume.shape}."
            ),
        )

    if source_volume.affine.shape != (4, 4) or annotation_volume.affine.shape != (4, 4):
        return AnnotationCompatibilityResult(
            False,
            "Affine metadata is not 4x4 for source image or annotation mask.",
        )

    source_axcodes = nib.orientations.aff2axcodes(source_volume.affine)
    annotation_axcodes = nib.orientations.aff2axcodes(annotation_volume.affine)
    if source_axcodes != annotation_axcodes:
        return AnnotationCompatibilityResult(
            False,
            (
                "Orientation mismatch between source image and annotation mask. "
                f"Source orientation={source_axcodes}, annotation orientation={annotation_axcodes}."
            ),
        )

    source_zooms = np.asarray(source_volume.header.get_zooms()[:3], dtype=np.float64)
    annotation_zooms = np.asarray(
        annotation_volume.header.get_zooms()[:3], dtype=np.float64
    )
    if not np.allclose(source_zooms, annotation_zooms, atol=zoom_atol, rtol=0.0):
        return AnnotationCompatibilityResult(
            False,
            (
                "Voxel spacing mismatch between source image and annotation mask. "
                f"Source spacing={tuple(source_zooms)}, annotation spacing={tuple(annotation_zooms)}."
            ),
        )

    if not np.allclose(
        source_volume.affine,
        annotation_volume.affine,
        atol=affine_atol,
        rtol=0.0,
    ):
        return AnnotationCompatibilityResult(
            False,
            "Affine mismatch between source image and annotation mask; voxel-to-world mapping is not equivalent.",
        )

    return AnnotationCompatibilityResult(True, "Annotation metadata is compatible.")


def load_annotation_mask(
    path: str | Path,
    source_volume: NiftiLoadResult,
    *,
    labels: dict[int, str] | None = None,
) -> AnnotationMask:
    """Load and validate a voxel-space annotation mask against a source image."""
    annotation_volume = load_nifti(path)
    result = validate_annotation_compatibility(source_volume, annotation_volume)
    if not result.is_valid:
        raise ValueError(result.message)

    return AnnotationMask(
        data=annotation_volume.data,
        affine=annotation_volume.affine,
        header=annotation_volume.header,
        labels=labels if labels is not None else {0: "background", 1: "label 1"},
    )


def save_annotation_mask(
    annotation_mask: AnnotationMask,
    destination_path: str | Path,
) -> Path:
    """Save an annotation mask as NIfTI while preserving source-space metadata."""
    output_path = Path(destination_path)
    if not str(output_path).lower().endswith((".nii", ".nii.gz")):
        raise ValueError("Annotation mask path must end with .nii or .nii.gz.")

    header = annotation_mask.header.copy()
    header.set_data_shape(annotation_mask.data.shape)
    header.set_data_dtype(annotation_mask.data.dtype)

    _, qform_code = header.get_qform(coded=True)
    _, sform_code = header.get_sform(coded=True)
    q_code = int(qform_code) if qform_code else 1
    s_code = int(sform_code) if sform_code else 1

    affine = np.asarray(annotation_mask.affine, dtype=np.float64)
    data = np.asarray(annotation_mask.data)
    image = nib.Nifti1Image(data, affine, header=header)
    image.header.set_qform(affine, code=q_code)
    image.header.set_sform(affine, code=s_code)
    nib.save(image, str(output_path))
    return output_path
