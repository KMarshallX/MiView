from __future__ import annotations

import numpy as np

from miview.viewer.intensity import (
    normalize_slice_to_uint8,
    robust_auto_window,
    volume_intensity_range,
    window_slice_to_uint8,
)


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


def test_window_slice_to_uint8_uses_fixed_window() -> None:
    slice_data = np.array([[0.0, 10.0], [20.0, 30.0]], dtype=np.float32)

    windowed = window_slice_to_uint8(slice_data, 10.0, 20.0)

    expected = np.array([[0, 0], [255, 255]], dtype=np.uint8)
    np.testing.assert_array_equal(windowed, expected)


def test_volume_intensity_range_ignores_nonfinite_values() -> None:
    volume_data = np.array([0.0, 5.0, np.nan, np.inf, -3.0], dtype=np.float32)

    range_min, range_max = volume_intensity_range(volume_data)

    assert range_min == -3.0
    assert range_max == 5.0


def test_robust_auto_window_clips_tail_outliers() -> None:
    volume_data = np.array([0.0] * 1000 + [10000.0], dtype=np.float32)

    window_min, window_max = robust_auto_window(volume_data)

    assert window_min == 0.0
    assert window_max == 1.0
