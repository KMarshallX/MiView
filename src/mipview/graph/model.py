from __future__ import annotations

from dataclasses import dataclass, field

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
        self.edges = {
            edge
            for edge in self.edges
            if normalized_id not in (edge.start_node_id, edge.end_node_id)
        }
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
        return edge

    def clear(self) -> None:
        self.nodes.clear()
        self.edges.clear()
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
