from __future__ import annotations

from dataclasses import dataclass, field
import math

from mipview.graph.curve import (
    nearest_quadratic_bezier_parameter,
    split_quadratic_bezier,
)
from mipview.viewer.slice_geometry import Orientation


@dataclass(frozen=True)
class GraphNode:
    id: int
    horizontal_index: int
    vertical_index: int

    def position(self) -> tuple[int, int]:
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


@dataclass
class ProjectionGraphLayer:
    orientation: Orientation
    plane_shape: tuple[int, int] | None = None
    nodes: dict[int, GraphNode] = field(default_factory=dict)
    edges: set[GraphEdge] = field(default_factory=set)
    curve_control_points: dict[GraphEdge, tuple[float, float]] = field(
        default_factory=dict
    )
    _next_node_id: int = 1

    def set_plane_shape(self, plane_shape: tuple[int, int]) -> bool:
        width, height = (int(plane_shape[0]), int(plane_shape[1]))
        if width <= 0 or height <= 0:
            raise ValueError(f"Graph projection shape must be positive, got {(width, height)}.")
        normalized_shape = (width, height)
        if self.plane_shape == normalized_shape:
            return False
        cleared = bool(self.nodes or self.edges)
        self.clear()
        self.plane_shape = normalized_shape
        return cleared

    def add_node(self, horizontal_index: int, vertical_index: int) -> GraphNode:
        horizontal = int(horizontal_index)
        vertical = int(vertical_index)
        self._validate_position(horizontal, vertical)
        if any(node.position() == (horizontal, vertical) for node in self.nodes.values()):
            raise ValueError(
                f"A graph node already exists at projection coordinate {(horizontal, vertical)}."
            )
        node = GraphNode(self._next_node_id, horizontal, vertical)
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
        self.edges = {
            edge
            for edge in self.edges
            if normalized_id not in (edge.start_node_id, edge.end_node_id)
        }
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
        control_point: tuple[float, float],
    ) -> GraphEdge:
        edge = GraphEdge.between(first_node_id, second_node_id)
        if edge not in self.edges:
            raise ValueError(
                f"Graph edge {edge.start_node_id}-{edge.end_node_id} does not exist."
            )
        horizontal, vertical = (float(control_point[0]), float(control_point[1]))
        self._validate_control_point(horizontal, vertical)
        self.curve_control_points[edge] = (horizontal, vertical)
        return edge

    def straighten_edge(self, first_node_id: int, second_node_id: int) -> GraphEdge:
        edge = GraphEdge.between(first_node_id, second_node_id)
        if edge not in self.edges:
            raise ValueError(
                f"Graph edge {edge.start_node_id}-{edge.end_node_id} does not exist."
            )
        self.curve_control_points.pop(edge, None)
        return edge

    def ensure_curve_control_point(self, edge: GraphEdge) -> tuple[float, float]:
        if edge not in self.edges:
            raise ValueError(
                f"Graph edge {edge.start_node_id}-{edge.end_node_id} does not exist."
            )
        existing = self.curve_control_points.get(edge)
        if existing is not None:
            return existing
        start = self.nodes[edge.start_node_id]
        end = self.nodes[edge.end_node_id]
        midpoint = (
            (start.horizontal_index + end.horizontal_index) / 2.0,
            (start.vertical_index + end.vertical_index) / 2.0,
        )
        self.curve_control_points[edge] = midpoint
        return midpoint

    def split_edge(
        self,
        first_node_id: int,
        second_node_id: int,
        near_position: tuple[int, int] | tuple[float, float],
    ) -> tuple[GraphNode, GraphEdge, GraphEdge]:
        """Insert a node at the nearest edge point and replace the edge in two."""
        edge = GraphEdge.between(first_node_id, second_node_id)
        if edge not in self.edges:
            raise ValueError(
                f"Graph edge {edge.start_node_id}-{edge.end_node_id} does not exist."
            )
        start_node = self.nodes[edge.start_node_id]
        end_node = self.nodes[edge.end_node_id]
        start = (float(start_node.horizontal_index), float(start_node.vertical_index))
        end = (float(end_node.horizontal_index), float(end_node.vertical_index))
        point = (float(near_position[0]), float(near_position[1]))
        control = self.curve_control_points.get(edge)
        if control is None:
            parameter = _nearest_segment_parameter(point, start, end)
            split_point = (
                start[0] + ((end[0] - start[0]) * parameter),
                start[1] + ((end[1] - start[1]) * parameter),
            )
            left_control = None
            right_control = None
        else:
            parameter = nearest_quadratic_bezier_parameter(
                point,
                start,
                control,
                end,
            )
            split_point, left_control, right_control = split_quadratic_bezier(
                start,
                control,
                end,
                parameter,
            )

        horizontal = int(round(split_point[0]))
        vertical = int(round(split_point[1]))
        new_node = self.add_node(horizontal, vertical)
        self.delete_edge(edge.start_node_id, edge.end_node_id)
        first_edge = self.add_edge(edge.start_node_id, new_node.id)
        second_edge = self.add_edge(new_node.id, edge.end_node_id)
        if left_control is not None and right_control is not None:
            self.curve_control_points[first_edge] = left_control
            self.curve_control_points[second_edge] = right_control
        return new_node, first_edge, second_edge

    def clear(self) -> None:
        self.nodes.clear()
        self.edges.clear()
        self.curve_control_points.clear()
        self._next_node_id = 1

    def _validate_position(self, horizontal_index: int, vertical_index: int) -> None:
        if self.plane_shape is None:
            raise ValueError("Graph projection shape is not available.")
        width, height = self.plane_shape
        if not (0 <= horizontal_index < width and 0 <= vertical_index < height):
            raise ValueError(
                "Graph node projection coordinate "
                f"{(horizontal_index, vertical_index)} is outside shape {self.plane_shape}."
            )

    def _validate_edge_endpoints(self, edge: GraphEdge) -> None:
        missing = [
            node_id
            for node_id in (edge.start_node_id, edge.end_node_id)
            if node_id not in self.nodes
        ]
        if missing:
            raise ValueError(f"Graph edge references missing node(s): {missing}.")

    def _validate_control_point(self, horizontal: float, vertical: float) -> None:
        if self.plane_shape is None:
            raise ValueError("Graph projection shape is not available.")
        if not math.isfinite(horizontal) or not math.isfinite(vertical):
            raise ValueError("Curve control point coordinates must be finite.")
        width, height = self.plane_shape
        if not (0.0 <= horizontal <= width - 1 and 0.0 <= vertical <= height - 1):
            raise ValueError(
                "Curve control point "
                f"{(horizontal, vertical)} is outside shape {self.plane_shape}."
            )


def _nearest_segment_parameter(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    delta_x = end[0] - start[0]
    delta_y = end[1] - start[1]
    squared_length = (delta_x * delta_x) + (delta_y * delta_y)
    if squared_length <= 0.0:
        return 0.0
    parameter = (
        ((point[0] - start[0]) * delta_x)
        + ((point[1] - start[1]) * delta_y)
    ) / squared_length
    return min(max(parameter, 0.0), 1.0)
