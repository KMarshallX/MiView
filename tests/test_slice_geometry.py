from __future__ import annotations

import numpy as np

from miview.viewer.slice_geometry import (
    center_cursor_for_volume,
    extract_oriented_slice,
    map_cursor_to_plane_indices,
    map_plane_fraction_to_cursor,
)


def test_center_cursor_for_volume_uses_logical_center() -> None:
    assert center_cursor_for_volume((7, 9, 11)) == (4, 3, 5)


def test_extract_oriented_slice_returns_expected_planes() -> None:
    volume = np.arange(3 * 4 * 5).reshape((3, 4, 5))
    cursor = (2, 1, 3)

    axial = extract_oriented_slice(volume, "axial", cursor)
    coronal = extract_oriented_slice(volume, "coronal", cursor)
    sagittal = extract_oriented_slice(volume, "sagittal", cursor)

    np.testing.assert_array_equal(axial, volume[:, :, 3])
    np.testing.assert_array_equal(coronal, volume[1, :, :].T)
    np.testing.assert_array_equal(sagittal, volume[:, 2, :].T)


def test_map_plane_fraction_to_cursor_updates_orientation_axes_only() -> None:
    current_cursor = (2, 1, 4)
    shape = (6, 8, 10)

    assert map_plane_fraction_to_cursor("axial", shape, current_cursor, 0.5, 0.25) == (
        4,
        1,
        4,
    )
    assert map_plane_fraction_to_cursor("coronal", shape, current_cursor, 0.5, 0.25) == (
        4,
        1,
        2,
    )
    assert map_plane_fraction_to_cursor(
        "sagittal", shape, current_cursor, 0.5, 0.25
    ) == (2, 3, 2)


def test_map_cursor_to_plane_indices_returns_explicit_plane_coordinates() -> None:
    cursor = (4, 3, 2)

    assert map_cursor_to_plane_indices("axial", cursor) == (4, 3)
    assert map_cursor_to_plane_indices("coronal", cursor) == (4, 2)
    assert map_cursor_to_plane_indices("sagittal", cursor) == (3, 2)
