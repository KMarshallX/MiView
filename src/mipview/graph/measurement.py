from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping

import numpy as np

from mipview.viewer.slice_geometry import Orientation


@dataclass(frozen=True)
class DirectedGraphVector:
    orientation: Orientation
    source_node_id: int
    target_node_id: int

    def __post_init__(self) -> None:
        if int(self.source_node_id) == int(self.target_node_id):
            raise ValueError("Vector source and target nodes must be different.")

    def references_node(self, orientation: Orientation, node_id: int) -> bool:
        return self.orientation == orientation and int(node_id) in (
            int(self.source_node_id),
            int(self.target_node_id),
        )


def calculate_unsigned_angle_degrees(
    vector_1: DirectedGraphVector,
    vector_2: DirectedGraphVector,
    node_positions: Mapping[int, tuple[int, int] | tuple[float, float]],
    in_plane_spacing: tuple[float, float],
) -> float:
    """Calculate a spacing-aware unsigned angle between two directed vectors."""
    if vector_1.orientation != vector_2.orientation:
        raise ValueError("Both vectors must use the same projection orientation.")

    horizontal_spacing, vertical_spacing = (
        float(in_plane_spacing[0]),
        float(in_plane_spacing[1]),
    )
    if not all(
        math.isfinite(value) and value > 0.0
        for value in (horizontal_spacing, vertical_spacing)
    ):
        raise ValueError("In-plane voxel spacing must contain two positive finite values.")

    first = _physical_components(vector_1, node_positions, in_plane_spacing)
    second = _physical_components(vector_2, node_positions, in_plane_spacing)
    first_norm = float(np.linalg.norm(first))
    second_norm = float(np.linalg.norm(second))
    if first_norm <= 0.0 or second_norm <= 0.0:
        raise ValueError("Cannot calculate an angle from a zero-length vector.")

    cosine = float(np.dot(first, second) / (first_norm * second_norm))
    clamped_cosine = min(max(cosine, -1.0), 1.0)
    return float(np.degrees(np.arccos(clamped_cosine)))


def _physical_components(
    vector: DirectedGraphVector,
    node_positions: Mapping[int, tuple[int, int] | tuple[float, float]],
    in_plane_spacing: tuple[float, float],
) -> np.ndarray:
    try:
        source = node_positions[int(vector.source_node_id)]
        target = node_positions[int(vector.target_node_id)]
    except KeyError as exc:
        raise ValueError(f"Vector references missing graph node {exc.args[0]}.") from exc
    return np.asarray(
        (
            (float(target[0]) - float(source[0])) * float(in_plane_spacing[0]),
            (float(target[1]) - float(source[1])) * float(in_plane_spacing[1]),
        ),
        dtype=np.float64,
    )
