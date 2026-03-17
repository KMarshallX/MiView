from __future__ import annotations

import numpy as np

from mipview.viewer.slice_geometry import (
    compute_display_rect,
    compute_shared_base_scale,
    center_cursor_for_volume,
    extract_oriented_slice,
    map_label_position_to_plane_fraction,
    map_plane_indices_to_label_position,
    map_cursor_to_plane_indices,
    map_plane_fraction_to_cursor,
    orientation_indicators_for_orientation,
    step_cursor_slice,
)


def test_center_cursor_for_volume_uses_logical_center() -> None:
    assert center_cursor_for_volume((7, 9, 11)) == (3, 4, 5)


def test_extract_oriented_slice_returns_expected_planes() -> None:
    volume = np.arange(3 * 4 * 5).reshape((3, 4, 5))
    cursor = (2, 1, 3)

    axial = extract_oriented_slice(volume, "axial", cursor)
    coronal = extract_oriented_slice(volume, "coronal", cursor)
    sagittal = extract_oriented_slice(volume, "sagittal", cursor)

    np.testing.assert_array_equal(axial, volume[:, :, 3].T[::-1, ::-1])
    np.testing.assert_array_equal(coronal, volume[:, 1, :].T[::-1, ::-1])
    np.testing.assert_array_equal(sagittal, volume[2, :, :].T[::-1, ::-1])


def test_map_plane_fraction_to_cursor_updates_orientation_axes_only() -> None:
    current_cursor = (2, 1, 4)
    shape = (6, 8, 10)

    assert map_plane_fraction_to_cursor("axial", shape, current_cursor, 0.5, 0.25) == (
        2,
        5,
        4,
    )
    assert map_plane_fraction_to_cursor("coronal", shape, current_cursor, 0.5, 0.25) == (
        2,
        1,
        7,
    )
    assert map_plane_fraction_to_cursor(
        "sagittal", shape, current_cursor, 0.5, 0.25
    ) == (2, 3, 7)


def test_map_cursor_to_plane_indices_returns_explicit_plane_coordinates() -> None:
    cursor = (4, 3, 2)
    shape = (6, 8, 10)

    assert map_cursor_to_plane_indices("axial", cursor, shape) == (1, 4)
    assert map_cursor_to_plane_indices("coronal", cursor, shape) == (1, 7)
    assert map_cursor_to_plane_indices("sagittal", cursor, shape) == (4, 7)


def test_orientation_indicators_match_displayed_anatomical_directions() -> None:
    axial = orientation_indicators_for_orientation("axial")
    coronal = orientation_indicators_for_orientation("coronal")
    sagittal = orientation_indicators_for_orientation("sagittal")

    assert (axial.left, axial.right) == ("R", "L")
    assert (axial.top, axial.bottom) == ("A", "P")
    assert (coronal.left, coronal.right) == ("R", "L")
    assert (sagittal.left, sagittal.right) == ("A", "P")
    assert (coronal.top, coronal.bottom) == ("S", "I")
    assert (sagittal.top, sagittal.bottom) == ("S", "I")


def test_step_cursor_slice_moves_along_fixed_axis_and_clamps() -> None:
    shape = (6, 8, 10)
    cursor = (3, 4, 5)

    assert step_cursor_slice("axial", shape, cursor, -2) == (3, 4, 3)
    assert step_cursor_slice("coronal", shape, cursor, 10) == (3, 7, 5)
    assert step_cursor_slice("sagittal", shape, cursor, -10) == (0, 4, 5)


def test_compute_display_rect_applies_zoom_and_pan() -> None:
    display_rect = compute_display_rect((100, 50), (200, 200), 2.0, 1.5, (10.0, -5.0))

    assert display_rect is not None
    assert display_rect.width == 300.0
    assert display_rect.height == 150.0
    assert display_rect.left == -40.0
    assert display_rect.top == 20.0


def test_plane_fraction_and_label_position_mapping_stay_consistent() -> None:
    display_rect = compute_display_rect((10, 10), (100, 100), 10.0, 1.0, (0.0, 0.0))
    assert display_rect is not None

    plane_fraction = map_label_position_to_plane_fraction((55.0, 35.0), display_rect)

    assert plane_fraction == (0.55, 0.35)
    assert map_plane_indices_to_label_position((5, 3), (10, 10), display_rect) == (55, 35)


def test_compute_shared_base_scale_uses_smallest_fit_candidate() -> None:
    assert compute_shared_base_scale([(200, 100), (150, 80)], [(300, 300), (300, 300)]) == 1.5
