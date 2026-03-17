from __future__ import annotations

import numpy as np
import pytest

from mipview.tools.processing import (
    frangi_filter,
    gaussian_filter,
    hessian_filter,
    invert_divide,
    invert_minus,
    local_normalize,
    normalize,
    standardize,
)
from mipview.tools.registry import all_tools, apply_tool


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


def test_gaussian_filter_accepts_scalar_or_sequence_sigma(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_gaussian(data: np.ndarray, **kwargs: object) -> np.ndarray:
        captured.update(kwargs)
        return np.asarray(data, dtype=np.float32) + np.float32(1.0)

    monkeypatch.setattr(
        "mipview.tools.processing._require_skimage_filters",
        lambda: (fake_gaussian, None, None),
    )

    data = np.ones((3, 3, 3), dtype=np.float32)
    output_sequence = gaussian_filter(data, sigma="1.0,2.0,3.0", mode="mirror")
    np.testing.assert_allclose(output_sequence, np.full_like(data, 2.0))
    assert captured["sigma"] == (1.0, 2.0, 3.0)
    assert captured["mode"] == "mirror"
    assert captured["preserve_range"] is True

    captured.clear()
    _ = gaussian_filter(data, sigma=1.5, mode="reflect")
    assert captured["sigma"] == 1.5


def test_gaussian_filter_rejects_invalid_inputs() -> None:
    data = np.ones((3, 3, 3), dtype=np.float32)
    with pytest.raises(ValueError):
        gaussian_filter(data, sigma="a,b", mode="reflect")
    with pytest.raises(ValueError):
        gaussian_filter(data, sigma="1.0", mode="invalid")


def test_hessian_and_frangi_filters_use_expected_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hessian_captured: dict[str, object] = {}
    frangi_captured: dict[str, object] = {}

    def fake_hessian(data: np.ndarray, **kwargs: object) -> np.ndarray:
        hessian_captured.update(kwargs)
        return np.asarray(data, dtype=np.float32) + np.float32(2.0)

    def fake_frangi(data: np.ndarray, **kwargs: object) -> np.ndarray:
        frangi_captured.update(kwargs)
        return np.asarray(data, dtype=np.float32) + np.float32(3.0)

    monkeypatch.setattr(
        "mipview.tools.processing._require_skimage_filters",
        lambda: (None, fake_hessian, fake_frangi),
    )

    data = np.ones((2, 2, 2), dtype=np.float32)
    hessian_out = hessian_filter(data, sigma=2.0, gamma=8.0, black_ridges=False)
    frangi_out = frangi_filter(data, sigma=1.5, gamma=4.0, black_ridges=True)
    np.testing.assert_allclose(hessian_out, np.full_like(data, 3.0))
    np.testing.assert_allclose(frangi_out, np.full_like(data, 4.0))
    assert hessian_captured["sigmas"] == [2.0]
    assert hessian_captured["gamma"] == 8.0
    assert hessian_captured["black_ridges"] is False
    assert frangi_captured["sigmas"] == [1.5]
    assert frangi_captured["gamma"] == 4.0
    assert frangi_captured["black_ridges"] is True


def test_new_filters_are_exposed_in_tool_registry() -> None:
    tool_ids = {tool.id for tool in all_tools()}
    assert "gaussian_filter" in tool_ids
    assert "hessian_filter" in tool_ids
    assert "frangi_filter" in tool_ids
