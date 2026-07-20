from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping

import numpy as np

from mipview.graph.vector import GraphVector, resolve_graph_vector


@dataclass(frozen=True)
class AngleMeasurement:
    id: int
    source_vector_id: int
    target_vector_id: int
    angle_degrees: float


def calculate_unsigned_angle_degrees(
    vector_1: GraphVector,
    vector_2: GraphVector,
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

    first = np.asarray(
        resolve_graph_vector(
            vector_1, node_positions, in_plane_spacing
        ).physical_direction,
        dtype=np.float64,
    )
    second = np.asarray(
        resolve_graph_vector(
            vector_2, node_positions, in_plane_spacing
        ).physical_direction,
        dtype=np.float64,
    )
    first_norm = float(np.linalg.norm(first))
    second_norm = float(np.linalg.norm(second))
    if first_norm <= 0.0 or second_norm <= 0.0:
        raise ValueError("Cannot calculate an angle from a zero-length vector.")

    cosine = float(np.dot(first, second) / (first_norm * second_norm))
    clamped_cosine = min(max(cosine, -1.0), 1.0)
    return float(np.degrees(np.arccos(clamped_cosine)))
