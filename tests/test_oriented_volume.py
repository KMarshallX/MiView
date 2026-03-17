from __future__ import annotations

import numpy as np

from mipview.viewer.oriented_volume import build_oriented_volume


def test_build_oriented_volume_reorients_to_canonical_ras() -> None:
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

    assert oriented.display_shape == (3, 2, 4)
    np.testing.assert_array_equal(oriented.display_data, np.transpose(data, (1, 0, 2))[::-1, :, :])


def test_oriented_volume_index_mapping_round_trips() -> None:
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
    source_index = (1, 2, 3)

    display_index = oriented.source_to_display(source_index)

    assert display_index == (0, 1, 3)
    assert oriented.display_to_source(display_index) == source_index
