from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from mipview.graph.measurement import (
    DirectedGraphVector,
    calculate_unsigned_angle_degrees,
)
from mipview.graph.model import GraphEdge, ProjectionGraphLayer
from mipview.viewer.slice_geometry import Orientation


ORIENTATIONS: tuple[Orientation, ...] = ("axial", "coronal", "sagittal")
GraphTool = Literal["curve_edge", "calculate_angle"]


@dataclass
class ProjectionGraphState:
    layers: dict[Orientation, ProjectionGraphLayer] = field(
        default_factory=lambda: {
            orientation: ProjectionGraphLayer(orientation)
            for orientation in ORIENTATIONS
        }
    )
    editing_enabled: bool = False
    visible: bool = True
    opacity: float = 1.0
    node_size: int = 4
    edge_thickness: int = 2
    active_orientation: Orientation | None = None
    pending_edge_orientation: Orientation | None = None
    pending_edge_node_id: int | None = None
    active_tool: GraphTool | None = None
    selected_edge_orientation: Orientation | None = None
    selected_edge: GraphEdge | None = None
    curve_drag_active: bool = False
    angle_selection_step: int = 0
    angle_draft_nodes: list[tuple[Orientation, int]] = field(default_factory=list)
    angle_vector_1: DirectedGraphVector | None = None
    angle_vector_2: DirectedGraphVector | None = None
    calculated_angle_degrees: float | None = None

    def layer(self, orientation: Orientation) -> ProjectionGraphLayer:
        if orientation not in self.layers:
            raise ValueError(f"Unsupported graph orientation: {orientation}.")
        return self.layers[orientation]

    def set_opacity(self, opacity: float) -> None:
        self.opacity = min(max(float(opacity), 0.0), 1.0)

    def set_node_size(self, node_size: int) -> None:
        self.node_size = min(max(int(node_size), 1), 10)

    def set_edge_thickness(self, edge_thickness: int) -> None:
        self.edge_thickness = min(max(int(edge_thickness), 1), 10)

    def begin_edge(self, orientation: Orientation, node_id: int) -> None:
        layer = self.layer(orientation)
        if int(node_id) not in layer.nodes:
            raise ValueError(f"Graph node {node_id} does not exist in {orientation}.")
        self.cancel_active_tool()
        self.pending_edge_orientation = orientation
        self.pending_edge_node_id = int(node_id)
        self.active_orientation = orientation

    def cancel_pending_edge(self) -> None:
        self.pending_edge_orientation = None
        self.pending_edge_node_id = None

    def activate_curve_tool(self) -> None:
        self.cancel_pending_edge()
        self._clear_angle_draft()
        self.active_tool = "curve_edge"
        self.curve_drag_active = False

    def select_curve_edge(
        self,
        orientation: Orientation,
        first_node_id: int,
        second_node_id: int,
    ) -> GraphEdge:
        layer = self.layer(orientation)
        edge = GraphEdge.between(first_node_id, second_node_id)
        layer.ensure_curve_control_point(edge)
        self.active_tool = "curve_edge"
        self.selected_edge_orientation = orientation
        self.selected_edge = edge
        self.active_orientation = orientation
        self.curve_drag_active = False
        return edge

    def activate_angle_tool(self) -> None:
        self.cancel_pending_edge()
        self.selected_edge_orientation = None
        self.selected_edge = None
        self.curve_drag_active = False
        self.active_tool = "calculate_angle"
        self._clear_angle_draft()

    def select_angle_node(
        self,
        orientation: Orientation,
        node_id: int,
        in_plane_spacing: tuple[float, float],
    ) -> float | None:
        if self.active_tool != "calculate_angle":
            raise ValueError("Calculate Angle tool is not active.")
        layer = self.layer(orientation)
        normalized_id = int(node_id)
        if normalized_id not in layer.nodes:
            raise ValueError(f"Graph node {normalized_id} does not exist in {orientation}.")
        if self.angle_draft_nodes and orientation != self.angle_draft_nodes[0][0]:
            raise ValueError("Both vectors must use the same projection orientation.")
        if self.angle_selection_step in (1, 3):
            source_id = self.angle_draft_nodes[-1][1]
            if normalized_id == source_id:
                raise ValueError("Vector source and target nodes must be different.")

        self.angle_draft_nodes.append((orientation, normalized_id))
        self.angle_selection_step = len(self.angle_draft_nodes)
        self.active_orientation = orientation
        if self.angle_selection_step < 4:
            return None

        first = DirectedGraphVector(
            orientation,
            self.angle_draft_nodes[0][1],
            self.angle_draft_nodes[1][1],
        )
        second = DirectedGraphVector(
            orientation,
            self.angle_draft_nodes[2][1],
            self.angle_draft_nodes[3][1],
        )
        positions = {node.id: node.position() for node in layer.nodes.values()}
        angle = calculate_unsigned_angle_degrees(
            first,
            second,
            positions,
            in_plane_spacing,
        )
        self.angle_vector_1 = first
        self.angle_vector_2 = second
        self.calculated_angle_degrees = angle
        self._clear_angle_draft()
        self.active_tool = None
        return angle

    def calculate_angle(
        self,
        orientation: Orientation,
        vector_1_source: int,
        vector_1_target: int,
        vector_2_source: int,
        vector_2_target: int,
        in_plane_spacing: tuple[float, float],
    ) -> float:
        """Validate and replace the committed measurement atomically."""
        layer = self.layer(orientation)
        first = DirectedGraphVector(
            orientation,
            int(vector_1_source),
            int(vector_1_target),
        )
        second = DirectedGraphVector(
            orientation,
            int(vector_2_source),
            int(vector_2_target),
        )
        positions = {node.id: node.position() for node in layer.nodes.values()}
        angle = calculate_unsigned_angle_degrees(
            first,
            second,
            positions,
            in_plane_spacing,
        )
        self.angle_vector_1 = first
        self.angle_vector_2 = second
        self.calculated_angle_degrees = angle
        self._clear_angle_draft()
        if self.active_tool == "calculate_angle":
            self.active_tool = None
        return angle

    def draft_angle_vectors(self) -> tuple[DirectedGraphVector, ...]:
        if len(self.angle_draft_nodes) < 2:
            return ()
        first = DirectedGraphVector(
            self.angle_draft_nodes[0][0],
            self.angle_draft_nodes[0][1],
            self.angle_draft_nodes[1][1],
        )
        if len(self.angle_draft_nodes) < 4:
            return (first,)
        second = DirectedGraphVector(
            self.angle_draft_nodes[2][0],
            self.angle_draft_nodes[2][1],
            self.angle_draft_nodes[3][1],
        )
        return (first, second)

    def cancel_active_tool(self) -> None:
        self.active_tool = None
        self.selected_edge_orientation = None
        self.selected_edge = None
        self.curve_drag_active = False
        self._clear_angle_draft()

    def clear_angle(self) -> None:
        self._clear_angle_draft()
        self.angle_vector_1 = None
        self.angle_vector_2 = None
        self.calculated_angle_degrees = None
        if self.active_tool == "calculate_angle":
            self.active_tool = None

    def invalidate_node(self, orientation: Orientation, node_id: int) -> None:
        normalized_id = int(node_id)
        if (
            self.selected_edge_orientation == orientation
            and self.selected_edge is not None
            and normalized_id
            in (self.selected_edge.start_node_id, self.selected_edge.end_node_id)
        ):
            self.selected_edge_orientation = None
            self.selected_edge = None
            self.curve_drag_active = False
        invalidated_measurement = False
        if self.angle_vector_1 is not None and self.angle_vector_1.references_node(
            orientation, normalized_id
        ):
            self.angle_vector_1 = None
            invalidated_measurement = True
        if self.angle_vector_2 is not None and self.angle_vector_2.references_node(
            orientation, normalized_id
        ):
            self.angle_vector_2 = None
            invalidated_measurement = True
        if invalidated_measurement:
            self.calculated_angle_degrees = None
        if (orientation, normalized_id) in self.angle_draft_nodes:
            self._clear_angle_draft()

    def invalidate_orientations(self, orientations: tuple[Orientation, ...]) -> None:
        cleared = set(orientations)
        if not cleared:
            return
        if self.pending_edge_orientation in cleared:
            self.cancel_pending_edge()
        if self.selected_edge_orientation in cleared:
            self.selected_edge_orientation = None
            self.selected_edge = None
            self.curve_drag_active = False
        measurement_invalidated = False
        if self.angle_vector_1 is not None and self.angle_vector_1.orientation in cleared:
            self.angle_vector_1 = None
            measurement_invalidated = True
        if self.angle_vector_2 is not None and self.angle_vector_2.orientation in cleared:
            self.angle_vector_2 = None
            measurement_invalidated = True
        if measurement_invalidated:
            self.calculated_angle_degrees = None
        self.cancel_active_tool()

    def exit_editing(self) -> None:
        self.editing_enabled = False
        self.cancel_pending_edge()
        self.cancel_active_tool()

    def summary(self) -> dict[str, object]:
        return {
            "editing_enabled": self.editing_enabled,
            "visible": self.visible,
            "opacity": self.opacity,
            "node_size": self.node_size,
            "edge_thickness": self.edge_thickness,
            "active_orientation": self.active_orientation,
            "active_tool": self.active_tool,
            "selected_edge": self._selected_edge_summary(),
            "curve_drag_active": self.curve_drag_active,
            "pending_edge": (
                None
                if self.pending_edge_orientation is None
                or self.pending_edge_node_id is None
                else {
                    "orientation": self.pending_edge_orientation,
                    "start_node_id": self.pending_edge_node_id,
                }
            ),
            "angle_selection": {
                "step": self.angle_selection_step,
                "node_ids": [node_id for _, node_id in self.angle_draft_nodes],
                "orientation": (
                    None
                    if not self.angle_draft_nodes
                    else self.angle_draft_nodes[0][0]
                ),
            },
            "angle_vector_1": _vector_summary(self.angle_vector_1),
            "angle_vector_2": _vector_summary(self.angle_vector_2),
            "angle_degrees": self.calculated_angle_degrees,
            "layers": {
                orientation: {
                    "plane_shape": (
                        None if layer.plane_shape is None else list(layer.plane_shape)
                    ),
                    "num_nodes": len(layer.nodes),
                    "num_edges": len(layer.edges),
                    "num_curved_edges": len(layer.curve_control_points),
                }
                for orientation, layer in self.layers.items()
            },
        }

    def _clear_angle_draft(self) -> None:
        self.angle_draft_nodes.clear()
        self.angle_selection_step = 0

    def _selected_edge_summary(self) -> dict[str, object] | None:
        if self.selected_edge_orientation is None or self.selected_edge is None:
            return None
        return {
            "orientation": self.selected_edge_orientation,
            "start_node_id": self.selected_edge.start_node_id,
            "end_node_id": self.selected_edge.end_node_id,
        }


def _vector_summary(vector: DirectedGraphVector | None) -> dict[str, object] | None:
    if vector is None:
        return None
    return {
        "orientation": vector.orientation,
        "source_node_id": vector.source_node_id,
        "target_node_id": vector.target_node_id,
    }
