from __future__ import annotations

import numpy as np

from mipview.nifti_io import NiftiLoadResult


def derive_volume(source: NiftiLoadResult, data: np.ndarray) -> NiftiLoadResult:
    """Create a derived NIfTI volume preserving affine and header metadata."""
    derived_data = np.asarray(data)
    if derived_data.shape != source.shape:
        raise ValueError(
            "Derived data shape must match source shape for direct viewer replacement."
        )

    affine = np.asarray(source.affine).copy()
    header = source.header.copy()
    header.set_data_shape(tuple(int(dim) for dim in derived_data.shape))
    header.set_data_dtype(derived_data.dtype)

    _, qform_code = header.get_qform(coded=True)
    _, sform_code = header.get_sform(coded=True)
    header.set_qform(affine, code=int(qform_code) if qform_code else 1)
    header.set_sform(affine, code=int(sform_code) if sform_code else 1)

    return NiftiLoadResult(
        data=derived_data.copy(),
        affine=affine,
        header=header,
        shape=tuple(int(dim) for dim in derived_data.shape),
        dtype=derived_data.dtype,
    )
