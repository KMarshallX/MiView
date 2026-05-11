from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np

from mipview.annotation.annotation_mask import AnnotationMask
from mipview.nifti_io import NiftiLoadResult
from mipview.nifti_io import load_nifti

RLE_LINEAR_ENCODING = "rle_linear"
INDEX_ORDER = "x_fastest_xyz"


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
    *,
    overwrite: bool = False,
) -> Path:
    """Save an annotation mask as NIfTI while preserving source-space metadata."""
    output_path = Path(destination_path)
    if not str(output_path).lower().endswith((".nii", ".nii.gz")):
        raise ValueError("Annotation mask path must end with .nii or .nii.gz.")
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"Annotation mask already exists: {output_path}")

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


def annotation_metadata_path(annotation_path: str | Path) -> Path:
    """Return the default JSON sidecar path for a NIfTI annotation mask."""
    output_path = Path(annotation_path)
    name = output_path.name
    if name.lower().endswith(".nii.gz"):
        return output_path.with_name(f"{name[:-7]}.json")
    if name.lower().endswith(".nii"):
        return output_path.with_name(f"{name[:-4]}.json")
    return output_path.with_suffix(".json")


def _validate_shape(shape_value: Any) -> tuple[int, int, int]:
    if not isinstance(shape_value, list | tuple):
        raise ValueError("Annotation metadata shape must be a flat array.")
    if len(shape_value) != 3:
        raise ValueError(
            f"Annotation metadata shape must contain exactly 3 values, got {len(shape_value)}."
        )

    shape: list[int] = []
    for dim in shape_value:
        if not isinstance(dim, int) or isinstance(dim, bool):
            raise ValueError("Annotation metadata shape must contain integer values.")
        if dim <= 0:
            raise ValueError("Annotation metadata shape must contain positive integers.")
        shape.append(int(dim))
    return (shape[0], shape[1], shape[2])


def _num_voxels(shape: tuple[int, int, int]) -> int:
    return int(shape[0]) * int(shape[1]) * int(shape[2])


def _require_int(value: Any, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"Annotation metadata {field_name} must be an integer.")
    return int(value)


def encode_rle_linear_indices(
    indices: np.ndarray | list[int] | tuple[int, ...],
) -> list[list[int]]:
    """Encode sorted voxel linear indices as contiguous ``[start, length]`` runs."""
    index_array = np.asarray(indices, dtype=np.int64).reshape(-1)
    if index_array.size == 0:
        return []

    index_array = np.unique(index_array)
    if np.any(index_array < 0):
        raise ValueError("RLE-linear indices must be non-negative.")

    breaks = np.flatnonzero(np.diff(index_array) != 1) + 1
    starts = np.concatenate(([0], breaks))
    stops = np.concatenate((breaks, [index_array.size]))
    return [
        [int(index_array[start]), int(stop - start)]
        for start, stop in zip(starts, stops, strict=True)
    ]


def linear_indices_from_mask(mask: np.ndarray) -> np.ndarray:
    """Return foreground voxel indices using x-fastest XYZ flattening."""
    mask_array = np.asarray(mask)
    if mask_array.ndim != 3:
        raise ValueError(
            f"Annotation mask must be 3D to encode RLE-linear metadata, got {mask_array.ndim}D."
        )
    return np.flatnonzero(mask_array.ravel(order="F")).astype(np.int64, copy=False)


def encode_rle_linear_mask(mask: np.ndarray) -> list[list[int]]:
    """Encode a binary annotation mask as RLE-linear runs."""
    return encode_rle_linear_indices(linear_indices_from_mask(mask))


def build_annotation_metadata(
    annotation_mask: AnnotationMask,
    annotation_path: str | Path,
    *,
    source_image_path: str | Path | None = None,
    notes: str = "",
) -> dict[str, Any]:
    """Build RLE-linear JSON metadata describing annotated voxels."""
    labels: dict[str, dict[str, Any]] = {}
    data = np.asarray(annotation_mask.data)
    label_values = {
        int(label)
        for label in np.unique(data)
        if int(label) != 0
    } | {int(label) for label in annotation_mask.labels if int(label) != 0}
    for label_value in sorted(label_values):
        label_indices = linear_indices_from_mask(data == label_value)
        labels[str(label_value)] = {
            "name": annotation_mask.labels.get(label_value, f"label {label_value}"),
            "encoding": RLE_LINEAR_ENCODING,
            "runs": encode_rle_linear_indices(label_indices),
        }

    return {
        "source_image": "" if source_image_path is None else str(source_image_path),
        "annotation_mask": str(annotation_path),
        "index_order": INDEX_ORDER,
        "labels": labels,
        "shape": [int(dim) for dim in annotation_mask.shape],
        "notes": notes,
    }


def save_annotation_metadata(
    annotation_mask: AnnotationMask,
    annotation_path: str | Path,
    metadata_path: str | Path | None = None,
    *,
    source_image_path: str | Path | None = None,
    notes: str = "",
    overwrite: bool = False,
) -> Path:
    """Save a small JSON sidecar for a NIfTI annotation mask."""
    output_path = (
        annotation_metadata_path(annotation_path)
        if metadata_path is None
        else Path(metadata_path)
    )
    if output_path.suffix.lower() != ".json":
        raise ValueError("Annotation metadata path must end with .json.")
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"Annotation metadata already exists: {output_path}")

    metadata = build_annotation_metadata(
        annotation_mask,
        annotation_path,
        source_image_path=source_image_path,
        notes=notes,
    )
    output_path.write_text(
        json.dumps(metadata, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return output_path


def _load_annotation_metadata(metadata: str | Path | dict[str, Any]) -> dict[str, Any]:
    if isinstance(metadata, str | Path):
        metadata_path = Path(metadata)
        loaded_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if not isinstance(loaded_metadata, dict):
            raise ValueError("Annotation metadata JSON must contain an object.")
        return loaded_metadata
    if isinstance(metadata, dict):
        return metadata
    raise TypeError("Annotation metadata must be a JSON path or loaded dictionary.")


def _decode_rle_linear_runs(
    runs: Any,
    *,
    shape: tuple[int, int, int],
    label_value: int,
    flat_mask: np.ndarray,
) -> None:
    if not isinstance(runs, list):
        raise ValueError("RLE-linear runs must be a list of [start, length] pairs.")

    total_voxels = _num_voxels(shape)
    for run in runs:
        if not isinstance(run, list | tuple) or len(run) != 2:
            raise ValueError("Each RLE-linear run must be a pair of integers.")

        start = _require_int(run[0], "run start")
        length = _require_int(run[1], "run length")
        if start < 0:
            raise ValueError("RLE-linear run start must be >= 0.")
        if length <= 0:
            raise ValueError("RLE-linear run length must be > 0.")
        if start + length > total_voxels:
            raise ValueError(
                "RLE-linear run exceeds the annotation mask size for the stored shape."
            )

        flat_mask[start : start + length] = label_value


def decode_annotation_metadata(metadata: str | Path | dict[str, Any]) -> np.ndarray:
    """Decode RLE-linear annotation metadata into a voxel-space integer mask."""
    loaded_metadata = _load_annotation_metadata(metadata)
    shape = _validate_shape(loaded_metadata.get("shape"))

    index_order = loaded_metadata.get("index_order", INDEX_ORDER)
    if index_order != INDEX_ORDER:
        raise ValueError(
            f"Unsupported annotation index_order {index_order!r}; expected {INDEX_ORDER!r}."
        )

    labels = loaded_metadata.get("labels")
    if not isinstance(labels, dict):
        raise ValueError("Annotation metadata must contain a labels object.")

    flat_mask = np.zeros(_num_voxels(shape), dtype=np.uint8)
    for label_key, label_metadata in labels.items():
        try:
            label_value = int(label_key)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Annotation label key {label_key!r} must be parseable as an integer."
            ) from exc

        if label_value < 0 or label_value > np.iinfo(np.uint8).max:
            raise ValueError("Annotation label values must fit in uint8 for decoding.")
        if not isinstance(label_metadata, dict):
            raise ValueError("Annotation label metadata must be an object.")

        encoding = label_metadata.get("encoding")
        if encoding != RLE_LINEAR_ENCODING:
            raise ValueError(
                f"Unsupported annotation encoding {encoding!r}; expected {RLE_LINEAR_ENCODING!r}."
            )

        _decode_rle_linear_runs(
            label_metadata.get("runs"),
            shape=shape,
            label_value=label_value,
            flat_mask=flat_mask,
        )

    return flat_mask.reshape(shape, order="F")


def recon_annotation_metadata(
    metadata_path: str | Path,
    output_path: str | Path,
    source_image_path: str | Path | None = None,
) -> Path:
    """Reconstruct RLE-linear metadata as a NIfTI mask aligned to the source image."""
    metadata = _load_annotation_metadata(metadata_path)
    decoded_mask = decode_annotation_metadata(metadata)

    resolved_source_path = source_image_path
    if resolved_source_path is None:
        metadata_source_path = metadata.get("source_image")
        if isinstance(metadata_source_path, str) and metadata_source_path:
            resolved_source_path = metadata_source_path
    if resolved_source_path is None:
        raise ValueError(
            "A source image path is required, either as an argument or metadata['source_image']."
        )

    try:
        source_volume = load_nifti(resolved_source_path)
    except (FileNotFoundError, ValueError) as exc:
        raise ValueError(
            f"Could not load source NIfTI image: {resolved_source_path}"
        ) from exc

    source_shape = tuple(int(dim) for dim in source_volume.shape)
    if len(source_shape) != 3:
        raise ValueError(f"Source NIfTI image must be 3D, got shape {source_shape}.")
    if decoded_mask.shape != source_shape:
        raise ValueError(
            "Decoded annotation shape does not match source image shape. "
            f"Annotation shape={decoded_mask.shape}, source shape={source_shape}."
        )

    destination = Path(output_path)
    if not str(destination).lower().endswith((".nii", ".nii.gz")):
        raise ValueError("Reconstructed annotation path must end with .nii or .nii.gz.")

    affine = source_volume.affine
    header = source_volume.header.copy()
    header.set_data_dtype(np.uint8)
    header.set_data_shape(decoded_mask.shape)

    image = nib.Nifti1Image(
        decoded_mask.astype(np.uint8, copy=False),
        affine,
        header=header,
    )
    nib.save(image, str(destination))
    return destination
