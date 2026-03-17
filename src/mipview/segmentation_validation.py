from __future__ import annotations

from dataclasses import dataclass

import nibabel as nib
import numpy as np

from mipview.nifti_io import NiftiLoadResult


@dataclass(frozen=True)
class SegmentationValidationResult:
    is_valid: bool
    message: str


def validate_segmentation_compatibility(
    image_volume: NiftiLoadResult,
    segmentation_volume: NiftiLoadResult,
    *,
    affine_atol: float = 1e-4,
    zoom_atol: float = 1e-4,
) -> SegmentationValidationResult:
    image_data = np.asarray(image_volume.data)
    segmentation_data = np.asarray(segmentation_volume.data)

    if image_data.ndim != 3:
        return SegmentationValidationResult(
            False,
            f"Loaded image is {image_data.ndim}D; segmentation overlay expects a 3D image volume.",
        )

    if segmentation_data.ndim != 3:
        return SegmentationValidationResult(
            False,
            f"Segmentation is {segmentation_data.ndim}D; expected a 3D segmentation volume.",
        )

    if image_volume.shape != segmentation_volume.shape:
        return SegmentationValidationResult(
            False,
            (
                "Shape mismatch between image and segmentation. "
                f"Image shape={image_volume.shape}, segmentation shape={segmentation_volume.shape}."
            ),
        )

    if image_volume.affine.shape != (4, 4) or segmentation_volume.affine.shape != (4, 4):
        return SegmentationValidationResult(
            False,
            "Affine metadata is not 4x4 for image or segmentation; cannot validate spatial compatibility.",
        )

    image_axcodes = nib.orientations.aff2axcodes(image_volume.affine)
    segmentation_axcodes = nib.orientations.aff2axcodes(segmentation_volume.affine)
    if image_axcodes != segmentation_axcodes:
        return SegmentationValidationResult(
            False,
            (
                "Orientation mismatch between image and segmentation. "
                f"Image orientation={image_axcodes}, segmentation orientation={segmentation_axcodes}."
            ),
        )

    image_zooms = np.asarray(image_volume.header.get_zooms()[:3], dtype=np.float64)
    segmentation_zooms = np.asarray(
        segmentation_volume.header.get_zooms()[:3], dtype=np.float64
    )
    if not np.allclose(image_zooms, segmentation_zooms, atol=zoom_atol, rtol=0.0):
        return SegmentationValidationResult(
            False,
            (
                "Voxel spacing mismatch between image and segmentation. "
                f"Image spacing={tuple(image_zooms)}, segmentation spacing={tuple(segmentation_zooms)}."
            ),
        )

    if not np.allclose(
        image_volume.affine,
        segmentation_volume.affine,
        atol=affine_atol,
        rtol=0.0,
    ):
        return SegmentationValidationResult(
            False,
            "Affine mismatch between image and segmentation; voxel-to-world mapping is not equivalent.",
        )

    return SegmentationValidationResult(True, "Segmentation metadata is compatible.")