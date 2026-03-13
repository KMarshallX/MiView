from __future__ import annotations

import numpy as np

from miview.tools.processing import (
    invert_divide,
    invert_minus,
    local_normalize,
    normalize,
    standardize,
)
from miview.tools.registry import apply_tool


def test_normalize_maps_data_to_zero_one() -> None:
    data = np.array([0.0, 2.0, 4.0], dtype=np.float32).reshape(1, 1, 3)
    normalized = normalize(data)
    np.testing.assert_allclose(normalized, np.array([0.0, 0.5, 1.0]).reshape(1, 1, 3))


def test_standardize_handles_constant_input() -> None:
    data = np.ones((3, 3, 3), dtype=np.float32)
    standardized = standardize(data)
    np.testing.assert_allclose(standardized, np.zeros_like(data))


def test_local_normalize_rejects_even_window_size() -> None:
    data = np.ones((3, 3, 3), dtype=np.float32)
    try:
        local_normalize(data, window_size=4)
    except ValueError:
        return
    raise AssertionError("Expected ValueError for even local-normalization window size.")


def test_invert_minus_uses_reference_value() -> None:
    data = np.array([1.0, 2.0, 5.0], dtype=np.float32)
    inverted = invert_minus(data, reference_value=10.0)
    np.testing.assert_allclose(inverted, np.array([9.0, 8.0, 5.0], dtype=np.float32))


def test_invert_divide_has_safe_near_zero_handling() -> None:
    data = np.array([-1.0, 0.0, 2.0], dtype=np.float32)
    inverted = invert_divide(data, numerator=4.0, epsilon=1e-3)
    np.testing.assert_allclose(inverted, np.array([-4.0, 4000.0, 2.0], dtype=np.float32))


def test_registry_tool_application_matches_direct_function() -> None:
    data = np.array([2.0, 4.0, 6.0], dtype=np.float32)
    output = apply_tool("invert_minus", data, {"reference_value": 6.0})
    np.testing.assert_allclose(output, np.array([4.0, 2.0, 0.0], dtype=np.float32))
