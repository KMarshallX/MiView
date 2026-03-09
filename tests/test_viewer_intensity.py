from __future__ import annotations

import numpy as np

from miview.viewer.intensity import normalize_slice_to_uint8


def test_normalize_slice_to_uint8_scales_range() -> None:
    slice_data = np.array([[0.0, 5.0], [10.0, 15.0]], dtype=np.float32)

    normalized = normalize_slice_to_uint8(slice_data)

    assert normalized.dtype == np.uint8
    assert normalized.min() == 0
    assert normalized.max() == 255


def test_normalize_slice_to_uint8_handles_constant_input() -> None:
    slice_data = np.full((3, 3), 7.0, dtype=np.float32)

    normalized = normalize_slice_to_uint8(slice_data)

    np.testing.assert_array_equal(normalized, np.zeros((3, 3), dtype=np.uint8))

