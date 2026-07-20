from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping

import numpy as np

from mipview.graph.model import GraphEdge
from mipview.viewer.slice_geometry import Orientation


GraphVectorKind = Literal["node_pair", "edge_tangent", "edge_normal"]

VECTOR_COLOR_PRESET: tuple[str, ...] = (
    "#00A6FB",
    "#FF7F0E",
    "#2ECC71",
    "#E83E8C",
    "#FFD60A",
    "#9B5DE5",
    "#F94144",
    "#00D9C0",
    "#F3722C",
    "#A7C957",
    "#4CC9F0",
    "#F15BB5",
    "#72EFDD",
    "#FFB000",
    "#90BE6D",
    "#C77DFF",
    "#FF8C69",
    "#43AA8B",
    "#D4E157",
    "#FF70A6",
)


@dataclass(frozen=True)
class GraphVector:
    id: int
    orientation: Orientation
    kind: GraphVectorKind
    color_index: int
    source_node_id: int | None = None
    target_node_id: int | None = None
    edge: GraphEdge | None = None
    reversed: bool = False

    def __post_init__(self) -> None:
        if self.kind == "node_pair":
            if self.source_node_id is None or self.target_node_id is None:
                raise ValueError("A node-pair vector requires source and target nodes.")
            if int(self.source_node_id) == int(self.target_node_id):
                raise ValueError("Vector source and target nodes must be different.")
            if self.edge is not None:
                raise ValueError("A node-pair vector cannot reference a graph edge.")
        elif self.edge is None:
            raise ValueError(f"A {self.kind} vector requires a graph edge.")
        if not 0 <= int(self.color_index) < len(VECTOR_COLOR_PRESET):
            raise ValueError("Vector color index is outside the preset palette.")

    @property
    def color(self) -> str:
        return VECTOR_COLOR_PRESET[self.color_index]

    def references_node(self, node_id: int) -> bool:
        normalized = int(node_id)
        if self.kind == "node_pair":
            return normalized in (self.source_node_id, self.target_node_id)
        assert self.edge is not None
        return normalized in (self.edge.start_node_id, self.edge.end_node_id)

    def references_edge(self, edge: GraphEdge) -> bool:
        return self.edge == edge

    def flipped(self) -> GraphVector:
        return GraphVector(
            id=self.id,
            orientation=self.orientation,
            kind=self.kind,
            color_index=self.color_index,
            source_node_id=self.source_node_id,
            target_node_id=self.target_node_id,
            edge=self.edge,
            reversed=not self.reversed,
        )


@dataclass(frozen=True)
class ResolvedGraphVector:
    """Projection anchor and directions for rendering and measurement."""

    anchor: tuple[float, float]
    plane_direction: tuple[float, float]
    physical_direction: tuple[float, float]
    endpoint: tuple[float, float] | None


def resolve_graph_vector(
    vector: GraphVector,
    node_positions: Mapping[int, tuple[int, int] | tuple[float, float]],
    in_plane_spacing: tuple[float, float],
) -> ResolvedGraphVector:
    horizontal_spacing, vertical_spacing = _validated_spacing(in_plane_spacing)

    if vector.kind == "node_pair":
        assert vector.source_node_id is not None
        assert vector.target_node_id is not None
        source = _node_position(node_positions, vector.source_node_id)
        target = _node_position(node_positions, vector.target_node_id)
    else:
        assert vector.edge is not None
        source = _node_position(node_positions, vector.edge.start_node_id)
        target = _node_position(node_positions, vector.edge.end_node_id)

    plane_delta = (target[0] - source[0], target[1] - source[1])
    physical_tangent = (
        plane_delta[0] * horizontal_spacing,
        plane_delta[1] * vertical_spacing,
    )
    if float(np.hypot(*physical_tangent)) <= 0.0:
        raise ValueError("Cannot resolve a zero-length projected graph vector.")

    if vector.kind == "edge_normal":
        anchor = ((source[0] + target[0]) / 2.0, (source[1] + target[1]) / 2.0)
        physical_direction = (-physical_tangent[1], physical_tangent[0])
        plane_direction = (
            physical_direction[0] / horizontal_spacing,
            physical_direction[1] / vertical_spacing,
        )
        endpoint = None
    else:
        anchor = source
        plane_direction = plane_delta
        physical_direction = physical_tangent
        endpoint = target

    if vector.reversed:
        plane_direction = (-plane_direction[0], -plane_direction[1])
        physical_direction = (-physical_direction[0], -physical_direction[1])
        if endpoint is not None:
            anchor, endpoint = endpoint, anchor

    return ResolvedGraphVector(
        anchor=anchor,
        plane_direction=plane_direction,
        physical_direction=physical_direction,
        endpoint=endpoint,
    )


def _validated_spacing(spacing: tuple[float, float]) -> tuple[float, float]:
    normalized = (float(spacing[0]), float(spacing[1]))
    if not all(np.isfinite(value) and value > 0.0 for value in normalized):
        raise ValueError("In-plane voxel spacing must contain two positive finite values.")
    return normalized


def _node_position(
    positions: Mapping[int, tuple[int, int] | tuple[float, float]],
    node_id: int,
) -> tuple[float, float]:
    try:
        position = positions[int(node_id)]
    except KeyError as exc:
        raise ValueError(f"Vector references missing graph node {node_id}.") from exc
    return (float(position[0]), float(position[1]))
