from __future__ import annotations

import numpy as np


def normalize(
    data: np.ndarray,
    output_min: float = 0.0,
    output_max: float = 1.0,
) -> np.ndarray:
    """Linearly rescale intensities to a target range."""
    if output_max <= output_min:
        raise ValueError("Normalization output_max must be greater than output_min.")

    source = np.asarray(data, dtype=np.float32)
    source_min = float(np.min(source))
    source_max = float(np.max(source))
    span = source_max - source_min
    if span <= 0.0:
        return np.full(source.shape, output_min, dtype=np.float32)

    scaled = (source - source_min) / span
    return scaled * (output_max - output_min) + output_min


def standardize(data: np.ndarray, epsilon: float = 1e-6) -> np.ndarray:
    """Global z-score standardization."""
    source = np.asarray(data, dtype=np.float32)
    mean = float(np.mean(source))
    std = float(np.std(source))
    safe_std = max(std, float(epsilon))
    return (source - mean) / safe_std


def local_normalize(
    data: np.ndarray,
    window_size: int = 9,
    epsilon: float = 1e-6,
) -> np.ndarray:
    """Local z-score normalization using a 3D box window."""
    if window_size < 1 or window_size % 2 == 0:
        raise ValueError("Local normalization window_size must be an odd integer >= 1.")

    source = np.asarray(data, dtype=np.float32)
    radius = window_size // 2
    padded = np.pad(source, radius, mode="reflect")
    padded_squared = np.square(padded, dtype=np.float32)

    local_mean = _box_filter_mean_3d(padded, window_size)
    local_mean_sq = _box_filter_mean_3d(padded_squared, window_size)
    local_var = np.maximum(local_mean_sq - np.square(local_mean, dtype=np.float32), 0.0)
    local_std = np.sqrt(local_var, dtype=np.float32)
    safe_std = np.maximum(local_std, np.float32(epsilon))
    return (source - local_mean) / safe_std


def invert_minus(data: np.ndarray, reference_value: float) -> np.ndarray:
    """Contrast inversion by subtraction from a reference value."""
    source = np.asarray(data, dtype=np.float32)
    return np.float32(reference_value) - source


def invert_divide(
    data: np.ndarray,
    numerator: float,
    epsilon: float = 1e-6,
) -> np.ndarray:
    """Contrast inversion by division with explicit near-zero handling."""
    source = np.asarray(data, dtype=np.float32)
    epsilon32 = np.float32(epsilon)
    safe_denominator = np.where(
        np.abs(source) < epsilon32,
        np.where(source < 0.0, -epsilon32, epsilon32),
        source,
    )
    return np.float32(numerator) / safe_denominator


def _box_filter_mean_3d(padded: np.ndarray, window_size: int) -> np.ndarray:
    summed = _moving_sum_axis(_moving_sum_axis(_moving_sum_axis(
        padded,
        window_size,
        axis=0,
    ), window_size, axis=1), window_size, axis=2)
    return summed / np.float32(window_size**3)


def _moving_sum_axis(values: np.ndarray, window_size: int, axis: int) -> np.ndarray:
    cumsum = np.cumsum(values, axis=axis, dtype=np.float64)
    pad_shape = list(cumsum.shape)
    pad_shape[axis] = 1
    zero_pad = np.zeros(pad_shape, dtype=np.float64)
    cumsum = np.concatenate((zero_pad, cumsum), axis=axis)

    upper = [slice(None)] * cumsum.ndim
    lower = [slice(None)] * cumsum.ndim
    upper[axis] = slice(window_size, None)
    lower[axis] = slice(None, -window_size)
    return cumsum[tuple(upper)] - cumsum[tuple(lower)]
