from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field

import nibabel as nib
import numpy as np

from mipview.io.nifti_io import NiftiLoadResult


NiftiHeader = nib.nifti1.Nifti1Header | nib.nifti2.Nifti2Header


@dataclass
class AnnotationMask:
    """Voxel-space integer label mask aligned to a source image volume."""

    data: np.ndarray
    affine: np.ndarray
    header: NiftiHeader
    labels: dict[int, str] = field(default_factory=lambda: {0: "background"})

    def __post_init__(self) -> None:
        data = np.asarray(self.data)
        if data.ndim != 3:
            raise ValueError(
                f"Annotation mask must be 3D, got {data.ndim}D with shape {data.shape}."
            )
        if not np.issubdtype(data.dtype, np.integer):
            raise ValueError(
                f"Annotation mask must use an integer dtype, got {data.dtype}."
            )

        affine = np.asarray(self.affine, dtype=np.float64)
        if affine.shape != (4, 4):
            raise ValueError(
                f"Annotation affine must be 4x4, got shape {affine.shape}."
            )

        labels = {int(label): str(name) for label, name in self.labels.items()}
        if 0 in labels and labels[0] != "background":
            raise ValueError("Annotation label 0 is reserved for background.")
        labels[0] = "background"

        self.data = data.copy()
        self.affine = affine.copy()
        self.header = self.header.copy()
        self.header.set_data_shape(self.data.shape)
        self.header.set_data_dtype(self.data.dtype)
        self.labels = labels

    @property
    def shape(self) -> tuple[int, int, int]:
        return tuple(int(dim) for dim in self.data.shape)

    @property
    def dtype(self) -> np.dtype:
        return self.data.dtype


def create_empty_annotation_mask(
    source_volume: NiftiLoadResult,
    *,
    dtype: np.dtype | type[np.integer] = np.uint8,
    labels: dict[int, str] | None = None,
) -> AnnotationMask:
    """Create a zero-filled voxel-space annotation mask from a loaded image."""
    source_data = np.asarray(source_volume.data)
    if source_data.ndim != 3:
        raise ValueError(
            f"Source image must be 3D to create an annotation mask, got {source_data.ndim}D."
        )

    data_dtype = np.dtype(dtype)
    if not np.issubdtype(data_dtype, np.integer):
        raise ValueError(f"Annotation dtype must be an integer dtype, got {data_dtype}.")

    data = np.zeros(tuple(int(dim) for dim in source_data.shape), dtype=data_dtype)
    return AnnotationMask(
        data=data,
        affine=np.asarray(source_volume.affine, dtype=np.float64),
        header=source_volume.header,
        labels=labels if labels is not None else {0: "background", 1: "label 1"},
    )
