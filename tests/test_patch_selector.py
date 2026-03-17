from __future__ import annotations

import numpy as np

from mipview.patch_selector import (
    PatchBounds,
    PatchSelector,
    axis_for_resize_edge,
    compute_patch_bounds,
    orientation_slice_intersects_bounds,
    project_bounds_to_orientation,
    resized_axis_size_from_edge,
    source_bounds_to_display_bounds,
)
from mipview.viewer.oriented_volume import build_oriented_volume


def test_compute_patch_bounds_uses_centered_clipped_half_open_intervals() -> None:
    bounds = compute_patch_bounds((2, 1, 0), (6, 6, 4), (8, 8, 8))

    assert bounds == PatchBounds(
        x_start=0,
        x_end=5,
        y_start=0,
        y_end=4,
        z_start=0,
        z_end=2,
    )


def test_source_bounds_to_display_bounds_respects_axis_mapping() -> None:
    data = np.arange(2 * 3 * 4).reshape((2, 3, 4))
    affine = np.array(
        [
            [0.0, -2.0, 0.0, 0.0],
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 3.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ]
    )
    oriented = build_oriented_volume(data, affine)

    source_bounds = PatchBounds(0, 2, 1, 3, 1, 4)

    assert source_bounds_to_display_bounds(source_bounds, oriented) == PatchBounds(
        x_start=0,
        x_end=2,
        y_start=0,
        y_end=2,
        z_start=1,
        z_end=4,
    )


def test_project_bounds_to_orientation_matches_expected_view_sizes() -> None:
    bounds = PatchBounds(10, 74, 20, 84, 5, 15)
    display_shape = (100, 100, 40)

    axial = project_bounds_to_orientation(bounds, "axial", display_shape)
    coronal = project_bounds_to_orientation(bounds, "coronal", display_shape)
    sagittal = project_bounds_to_orientation(bounds, "sagittal", display_shape)

    assert (axial.horizontal_end - axial.horizontal_start, axial.vertical_end - axial.vertical_start) == (64, 64)
    assert (coronal.horizontal_end - coronal.horizontal_start, coronal.vertical_end - coronal.vertical_start) == (64, 10)
    assert (sagittal.horizontal_end - sagittal.horizontal_start, sagittal.vertical_end - sagittal.vertical_start) == (64, 10)
    assert (axial.horizontal_start, axial.vertical_start) == (26, 16)
    assert (coronal.horizontal_start, coronal.vertical_start) == (26, 25)
    assert (sagittal.horizontal_start, sagittal.vertical_start) == (16, 25)


def test_orientation_slice_intersects_bounds_checks_fixed_axis_interval() -> None:
    bounds = PatchBounds(10, 20, 11, 21, 12, 22)

    assert orientation_slice_intersects_bounds(bounds, "axial", (15, 18, 12))
    assert not orientation_slice_intersects_bounds(bounds, "axial", (15, 18, 22))


def test_resized_axis_size_from_edge_preserves_even_or_odd_parity() -> None:
    assert resized_axis_size_from_edge(50, 18, "left", 64) == 64
    assert resized_axis_size_from_edge(50, 81, "right", 64) == 64
    assert resized_axis_size_from_edge(50, 20, "left", 65) == 61
    assert resized_axis_size_from_edge(50, 80, "right", 65) == 61


def test_patch_selector_updates_size_by_axis() -> None:
    selector = PatchSelector((64, 64, 10))
    selector.set_volume_shape((100, 100, 40))
    selector.set_center((50, 50, 20))

    changed = selector.set_size_axis(2, 12)

    assert changed
    assert selector.size_xyz() == (64, 64, 12)


def test_axis_for_resize_edge_matches_requested_rules() -> None:
    assert axis_for_resize_edge("axial", "left") == 0
    assert axis_for_resize_edge("axial", "top") == 1
    assert axis_for_resize_edge("sagittal", "top") == 2
    assert axis_for_resize_edge("coronal", "bottom") == 2
    assert axis_for_resize_edge("sagittal", "left") is None
