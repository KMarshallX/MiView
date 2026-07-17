from __future__ import annotations

from dataclasses import dataclass, field
import math

from mipview.viewer.slice_geometry import Orientation


VoxelPoint = tuple[float, float, float]


@dataclass(frozen=True)
class GraphNode:
    """A graph node in patch-local source voxel coordinates."""

    id: int
    x: int
    y: int
    z: int

    def position(self) -> tuple[int, int, int]:
        return (self.x, self.y, self.z)


@dataclass(frozen=True)
class ProjectedGraphNode:
    """A read-only 2D projection of a shared graph node."""

    id: int
    horizontal_index: float
    vertical_index: float

    def position(self) -> tuple[float, float]:
        return (self.horizontal_index, self.vertical_index)


@dataclass(frozen=True, order=True)
class GraphEdge:
    start_node_id: int
    end_node_id: int

    @classmethod
    def between(cls, first_node_id: int, second_node_id: int) -> GraphEdge:
        first = int(first_node_id)
        second = int(second_node_id)
        if first == second:
            raise ValueError("A graph edge must connect two different nodes.")
        return cls(min(first, second), max(first, second))


@dataclass(frozen=True)
class ProjectionGraphLayer:
    """Read-only rendering geometry derived from one shared voxel graph."""

    orientation: Orientation
    plane_shape: tuple[int, int]
    nodes: dict[int, ProjectedGraphNode]
    edges: frozenset[GraphEdge]
    curve_control_points: dict[GraphEdge, tuple[float, float]]
    node_hit_priorities: dict[int, int] = field(default_factory=dict)


@dataclass
class VoxelGraph:
    """Session graph whose authoritative coordinates are patch-local voxels."""

    volume_shape: tuple[int, int, int] | None = None
    nodes: dict[int, GraphNode] = field(default_factory=dict)
    edges: set[GraphEdge] = field(default_factory=set)
    curve_control_points: dict[GraphEdge, VoxelPoint] = field(default_factory=dict)
    _next_node_id: int = 1

    def set_volume_shape(self, volume_shape: tuple[int, int, int]) -> bool:
        normalized = tuple(int(value) for value in volume_shape)
        if len(normalized) != 3 or any(value <= 0 for value in normalized):
            raise ValueError(f"Graph volume shape must be positive 3D, got {normalized}.")
        if self.volume_shape == normalized:
            return False
        cleared = bool(self.nodes or self.edges)
        self.clear()
        self.volume_shape = normalized
        return cleared

    def add_node(self, x: int, y: int, z: int) -> GraphNode:
        position = (int(x), int(y), int(z))
        self._validate_node_position(position)
        if any(node.position() == position for node in self.nodes.values()):
            raise ValueError(f"A graph node already exists at patch voxel {position}.")
        node = GraphNode(self._next_node_id, *position)
        self.nodes[node.id] = node
        self._next_node_id += 1
        return node

    def delete_node(self, node_id: int) -> GraphNode:
        normalized_id = int(node_id)
        node = self.nodes.get(normalized_id)
        if node is None:
            raise ValueError(f"Graph node {normalized_id} does not exist.")
        del self.nodes[normalized_id]
        removed_edges = {
            edge
            for edge in self.edges
            if normalized_id in (edge.start_node_id, edge.end_node_id)
        }
        self.edges.difference_update(removed_edges)
        for edge in removed_edges:
            self.curve_control_points.pop(edge, None)
        return node

    def add_edge(self, first_node_id: int, second_node_id: int) -> GraphEdge:
        edge = GraphEdge.between(first_node_id, second_node_id)
        self._validate_edge_endpoints(edge)
        if edge in self.edges:
            raise ValueError(
                f"Graph edge {edge.start_node_id}-{edge.end_node_id} already exists."
            )
        self.edges.add(edge)
        return edge

    def delete_edge(self, first_node_id: int, second_node_id: int) -> GraphEdge:
        edge = GraphEdge.between(first_node_id, second_node_id)
        if edge not in self.edges:
            raise ValueError(
                f"Graph edge {edge.start_node_id}-{edge.end_node_id} does not exist."
            )
        self.edges.remove(edge)
        self.curve_control_points.pop(edge, None)
        return edge

    def set_curve_control_point(
        self,
        first_node_id: int,
        second_node_id: int,
        control_point: VoxelPoint,
    ) -> GraphEdge:
        edge = GraphEdge.between(first_node_id, second_node_id)
        if edge not in self.edges:
            raise ValueError(
                f"Graph edge {edge.start_node_id}-{edge.end_node_id} does not exist."
            )
        normalized = tuple(float(value) for value in control_point)
        self._validate_control_point(normalized)
        self.curve_control_points[edge] = normalized
        return edge

    def straighten_edge(self, first_node_id: int, second_node_id: int) -> GraphEdge:
        edge = GraphEdge.between(first_node_id, second_node_id)
        if edge not in self.edges:
            raise ValueError(
                f"Graph edge {edge.start_node_id}-{edge.end_node_id} does not exist."
            )
        self.curve_control_points.pop(edge, None)
        return edge

    def ensure_curve_control_point(self, edge: GraphEdge) -> VoxelPoint:
        control_point = self.curve_control_point_or_midpoint(edge)
        self.curve_control_points[edge] = control_point
        return control_point

    def curve_control_point_or_midpoint(self, edge: GraphEdge) -> VoxelPoint:
        if edge not in self.edges:
            raise ValueError(
                f"Graph edge {edge.start_node_id}-{edge.end_node_id} does not exist."
            )
        existing = self.curve_control_points.get(edge)
        if existing is not None:
            return existing
        start = self.nodes[edge.start_node_id].position()
        end = self.nodes[edge.end_node_id].position()
        midpoint = tuple((start[index] + end[index]) / 2.0 for index in range(3))
        return midpoint  # type: ignore[return-value]

    def split_edge_at_parameter(
        self,
        first_node_id: int,
        second_node_id: int,
        parameter: float,
    ) -> tuple[GraphNode, GraphEdge, GraphEdge]:
        """Split an edge transactionally at a parameter derived from a projection."""
        edge = GraphEdge.between(first_node_id, second_node_id)
        if edge not in self.edges:
            raise ValueError(
                f"Graph edge {edge.start_node_id}-{edge.end_node_id} does not exist."
            )
        t = min(max(float(parameter), 0.0), 1.0)
        start = tuple(float(v) for v in self.nodes[edge.start_node_id].position())
        end = tuple(float(v) for v in self.nodes[edge.end_node_id].position())
        control = self.curve_control_points.get(edge)
        if control is None:
            split_point = _interpolate_3d(start, end, t)
            left_control = None
            right_control = None
        else:
            left_control = _interpolate_3d(start, control, t)
            right_control = _interpolate_3d(control, end, t)
            split_point = _interpolate_3d(left_control, right_control, t)

        rounded = tuple(int(round(value)) for value in split_point)
        self._validate_node_position(rounded)
        endpoint_positions = {
            self.nodes[edge.start_node_id].position(),
            self.nodes[edge.end_node_id].position(),
        }
        if rounded in endpoint_positions:
            raise ValueError("Graph edge split is too close to an endpoint voxel.")
        if any(node.position() == rounded for node in self.nodes.values()):
            raise ValueError(f"A graph node already exists at patch voxel {rounded}.")

        new_node = GraphNode(self._next_node_id, *rounded)
        first_edge = GraphEdge.between(edge.start_node_id, new_node.id)
        second_edge = GraphEdge.between(new_node.id, edge.end_node_id)

        self.edges.remove(edge)
        self.curve_control_points.pop(edge, None)
        self.nodes[new_node.id] = new_node
        self._next_node_id += 1
        self.edges.update((first_edge, second_edge))
        if left_control is not None and right_control is not None:
            self.curve_control_points[first_edge] = left_control
            self.curve_control_points[second_edge] = right_control
        return new_node, first_edge, second_edge

    def clear(self) -> None:
        self.nodes.clear()
        self.edges.clear()
        self.curve_control_points.clear()
        self._next_node_id = 1

    def _validate_node_position(self, position: tuple[int, int, int]) -> None:
        if self.volume_shape is None:
            raise ValueError("Graph volume shape is not available.")
        if any(
            coordinate < 0 or coordinate >= self.volume_shape[axis]
            for axis, coordinate in enumerate(position)
        ):
            raise ValueError(
                f"Graph node patch voxel {position} is outside shape {self.volume_shape}."
            )

    def _validate_edge_endpoints(self, edge: GraphEdge) -> None:
        missing = [
            node_id
            for node_id in (edge.start_node_id, edge.end_node_id)
            if node_id not in self.nodes
        ]
        if missing:
            raise ValueError(f"Graph edge references missing node(s): {missing}.")

    def _validate_control_point(self, point: VoxelPoint) -> None:
        if self.volume_shape is None:
            raise ValueError("Graph volume shape is not available.")
        if not all(math.isfinite(value) for value in point):
            raise ValueError("Curve control point coordinates must be finite.")
        if any(
            coordinate < 0.0 or coordinate > self.volume_shape[axis] - 1
            for axis, coordinate in enumerate(point)
        ):
            raise ValueError(
                f"Curve control point {point} is outside shape {self.volume_shape}."
            )


def _interpolate_3d(start: VoxelPoint, end: VoxelPoint, t: float) -> VoxelPoint:
    return tuple(
        start[index] + ((end[index] - start[index]) * t)
        for index in range(3)
    )  # type: ignore[return-value]
