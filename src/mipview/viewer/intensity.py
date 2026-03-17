from __future__ import annotations

import numpy as np


def normalize_slice_to_uint8(slice_data: np.ndarray) -> np.ndarray:
    """Normalize a 2D slice to 8-bit grayscale for display."""
    float_slice = np.asarray(slice_data, dtype=np.float32)
    min_value = float(float_slice.min())
    max_value = float(float_slice.max())

    if max_value <= min_value:
        return np.zeros(float_slice.shape, dtype=np.uint8)

    scaled = (float_slice - min_value) / (max_value - min_value)
    return np.clip(scaled * 255.0, 0.0, 255.0).astype(np.uint8)


def window_slice_to_uint8(
    slice_data: np.ndarray, window_min: float, window_max: float
) -> np.ndarray:
    """Apply a fixed display window and convert to 8-bit grayscale."""
    float_slice = np.asarray(slice_data, dtype=np.float32)
    if window_max <= window_min:
        return np.zeros(float_slice.shape, dtype=np.uint8)

    scaled = (float_slice - window_min) / (window_max - window_min)
    return np.clip(scaled * 255.0, 0.0, 255.0).astype(np.uint8)


def volume_intensity_range(volume_data: np.ndarray) -> tuple[float, float]:
    """Return finite min/max for the loaded volume."""
    float_data = np.asarray(volume_data, dtype=np.float32)
    finite_values = float_data[np.isfinite(float_data)]
    if finite_values.size == 0:
        return (0.0, 1.0)

    range_min = float(finite_values.min())
    range_max = float(finite_values.max())
    if range_max < range_min:
        range_min, range_max = range_max, range_min
    return (range_min, range_max)


def robust_auto_window(
    volume_data: np.ndarray,
    lower_percentile: float = 1.0,
    upper_percentile: float = 99.0,
) -> tuple[float, float]:
    """
    Compute a robust display window by clipping histogram tails via percentiles.

    Rule:
    - Use the 1st percentile as lower bound and the 99th percentile as upper bound.
    - Ignore NaN/inf values.
    - If percentiles collapse, widen by +1.0 to keep a valid non-zero window.
    """
    float_data = np.asarray(volume_data, dtype=np.float32)
    finite_values = float_data[np.isfinite(float_data)]
    if finite_values.size == 0:
        return (0.0, 1.0)

    lower = float(np.percentile(finite_values, lower_percentile))
    upper = float(np.percentile(finite_values, upper_percentile))
    if not np.isfinite(lower) or not np.isfinite(upper):
        lower = float(finite_values.min())
        upper = float(finite_values.max())
    if upper <= lower:
        upper = lower + 1.0
    return (lower, upper)
