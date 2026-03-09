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

