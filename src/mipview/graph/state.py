from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping

import numpy as np

from mipview.graph.measurement import (
    DirectedGraphVector,
    calculate_unsigned_angle_degrees,
)
from mipview.graph.model import GraphEdge, ProjectionGraphLayer, VoxelGraph
from mipview.graph.spatial import build_projected_graph_layer
from mipview.viewer.oriented_volume import OrientedVolume
from mipview.viewer.slice_geometry import Orientation


ORIENTATIONS: tuple[Orientation, ...] = ("axial", "coronal", "sagittal")
GraphTool = Literal["curve_edge", "calculate_angle"]


@dataclass
class ProjectionGraphState:
    graph: VoxelGraph = field(default_factory=VoxelGraph)
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
    normal_line_orientation: Orientation | None = None
    normal_line_edge: GraphEdge | None = None
    normal_line_thickness: int = 1
    extension_line_orientation: Orientation | None = None
    extension_line_edge: GraphEdge | None = None
    extension_line_thickness: int = 1
    _orientation_signature: tuple[float, ...] | None = field(
        default=None,
        repr=False,
    )

    def projected_layer(
        self,
        orientation: Orientation,
        oriented_volume: OrientedVolume,
    ) -> ProjectionGraphLayer:
        return build_projected_graph_layer(self.graph, oriented_volume, orientation)

    def set_volume_shape(self, volume_shape: tuple[int, int, int]) -> bool:
        cleared = self.graph.set_volume_shape(volume_shape)
        if cleared:
            self._clear_after_geometry_change()
        return cleared

    def set_volume_geometry(
        self,
        volume_shape: tuple[int, int, int],
        source_to_display_affine: np.ndarray,
    ) -> bool:
        signature = tuple(
            float(value)
            for value in np.asarray(source_to_display_affine, dtype=np.float64).ravel()
        )
        orientation_changed = (
            self._orientation_signature is not None
            and signature != self._orientation_signature
        )
        cleared = self.graph.set_volume_shape(volume_shape)
        if orientation_changed and not cleared:
            cleared = bool(self.graph.nodes or self.graph.edges)
            self.graph.clear()
        self._orientation_signature = signature
        if cleared:
            self._clear_after_geometry_change()
        return cleared

    def set_opacity(self, opacity: float) -> None:
        self.opacity = min(max(float(opacity), 0.0), 1.0)

    def set_node_size(self, node_size: int) -> None:
        self.node_size = min(max(int(node_size), 1), 10)

    def set_edge_thickness(self, edge_thickness: int) -> None:
        self.edge_thickness = min(max(int(edge_thickness), 1), 10)

    def begin_edge(self, orientation: Orientation, node_id: int) -> None:
        if int(node_id) not in self.graph.nodes:
            raise ValueError(f"Graph node {node_id} does not exist.")
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
        edge = GraphEdge.between(first_node_id, second_node_id)
        self.graph.ensure_curve_control_point(edge)
        self.invalidate_construction_lines(edge)
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
        node_positions: Mapping[int, tuple[float, float]],
        in_plane_spacing: tuple[float, float],
    ) -> float | None:
        if self.active_tool != "calculate_angle":
            raise ValueError("Calculate Angle tool is not active.")
        normalized_id = int(node_id)
        if normalized_id not in self.graph.nodes:
            raise ValueError(f"Graph node {normalized_id} does not exist.")
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
        angle = calculate_unsigned_angle_degrees(
            first,
            second,
            node_positions,
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
        node_positions: Mapping[int, tuple[float, float]],
        in_plane_spacing: tuple[float, float],
    ) -> float:
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
        angle = calculate_unsigned_angle_degrees(
            first,
            second,
            node_positions,
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

    def clear_graph(self) -> tuple[int, int]:
        """Clear completed geometry and all interactions derived from it."""
        node_count = len(self.graph.nodes)
        edge_count = len(self.graph.edges)
        self.graph.clear()
        self.cancel_pending_edge()
        self.cancel_active_tool()
        self.clear_angle()
        self.clear_normal_line()
        self.clear_extension_line()
        return node_count, edge_count

    def set_normal_line(
        self,
        orientation: Orientation,
        edge: GraphEdge,
        visible: bool,
    ) -> bool:
        if visible:
            if edge not in self.graph.edges:
                raise ValueError(
                    f"Graph edge {edge.start_node_id}-{edge.end_node_id} does not exist."
                )
            if edge in self.graph.curve_control_points:
                raise ValueError("A normal line is available only for a straight edge.")
            self.normal_line_orientation = orientation
            self.normal_line_edge = edge
            return True
        if (
            self.normal_line_orientation == orientation
            and self.normal_line_edge == edge
        ):
            self.clear_normal_line()
        return False

    def clear_normal_line(self) -> None:
        self.normal_line_orientation = None
        self.normal_line_edge = None

    def set_extension_line(
        self,
        orientation: Orientation,
        edge: GraphEdge,
        visible: bool,
    ) -> bool:
        if visible:
            if edge not in self.graph.edges:
                raise ValueError(
                    f"Graph edge {edge.start_node_id}-{edge.end_node_id} does not exist."
                )
            if edge in self.graph.curve_control_points:
                raise ValueError(
                    "An extension line is available only for a straight edge."
                )
            self.extension_line_orientation = orientation
            self.extension_line_edge = edge
            return True
        if (
            self.extension_line_orientation == orientation
            and self.extension_line_edge == edge
        ):
            self.clear_extension_line()
        return False

    def clear_extension_line(self) -> None:
        self.extension_line_orientation = None
        self.extension_line_edge = None

    def invalidate_edge(self, edge: GraphEdge) -> None:
        if self.selected_edge == edge:
            self.selected_edge_orientation = None
            self.selected_edge = None
            self.curve_drag_active = False
        self.invalidate_construction_lines(edge)

    def invalidate_construction_lines(self, edge: GraphEdge) -> None:
        self.invalidate_normal_line(edge)
        self.invalidate_extension_line(edge)

    def invalidate_normal_line(self, edge: GraphEdge) -> None:
        if self.normal_line_edge == edge:
            self.clear_normal_line()

    def invalidate_extension_line(self, edge: GraphEdge) -> None:
        if self.extension_line_edge == edge:
            self.clear_extension_line()

    def invalidate_node(self, node_id: int) -> None:
        normalized_id = int(node_id)
        if self.selected_edge is not None and normalized_id in (
            self.selected_edge.start_node_id,
            self.selected_edge.end_node_id,
        ):
            self.selected_edge_orientation = None
            self.selected_edge = None
            self.curve_drag_active = False
        if self.pending_edge_node_id == normalized_id:
            self.cancel_pending_edge()
        if self.normal_line_edge is not None and normalized_id in (
            self.normal_line_edge.start_node_id,
            self.normal_line_edge.end_node_id,
        ):
            self.clear_normal_line()
        if self.extension_line_edge is not None and normalized_id in (
            self.extension_line_edge.start_node_id,
            self.extension_line_edge.end_node_id,
        ):
            self.clear_extension_line()
        measurement_invalidated = False
        for vector_name in ("angle_vector_1", "angle_vector_2"):
            vector = getattr(self, vector_name)
            if vector is not None and normalized_id in (
                vector.source_node_id,
                vector.target_node_id,
            ):
                setattr(self, vector_name, None)
                measurement_invalidated = True
        if measurement_invalidated:
            self.calculated_angle_degrees = None
        if any(draft_id == normalized_id for _, draft_id in self.angle_draft_nodes):
            self._clear_angle_draft()

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
                if self.pending_edge_node_id is None
                else {
                    "orientation": self.pending_edge_orientation,
                    "start_node_id": self.pending_edge_node_id,
                }
            ),
            "angle_selection": {
                "step": self.angle_selection_step,
                "node_ids": [node_id for _, node_id in self.angle_draft_nodes],
                "orientation": (
                    None if not self.angle_draft_nodes else self.angle_draft_nodes[0][0]
                ),
            },
            "angle_vector_1": _vector_summary(self.angle_vector_1),
            "angle_vector_2": _vector_summary(self.angle_vector_2),
            "angle_degrees": self.calculated_angle_degrees,
            "normal_line": (
                None
                if self.normal_line_edge is None
                else {
                    "orientation": self.normal_line_orientation,
                    "start_node_id": self.normal_line_edge.start_node_id,
                    "end_node_id": self.normal_line_edge.end_node_id,
                    "thickness": self.normal_line_thickness,
                }
            ),
            "extension_line": (
                None
                if self.extension_line_edge is None
                else {
                    "orientation": self.extension_line_orientation,
                    "start_node_id": self.extension_line_edge.start_node_id,
                    "end_node_id": self.extension_line_edge.end_node_id,
                    "thickness": self.extension_line_thickness,
                }
            ),
            "voxel_graph": {
                "volume_shape": (
                    None
                    if self.graph.volume_shape is None
                    else list(self.graph.volume_shape)
                ),
                "num_nodes": len(self.graph.nodes),
                "num_edges": len(self.graph.edges),
                "num_curved_edges": len(self.graph.curve_control_points),
            },
        }

    def _clear_angle_draft(self) -> None:
        self.angle_draft_nodes.clear()
        self.angle_selection_step = 0

    def _clear_after_geometry_change(self) -> None:
        self.cancel_pending_edge()
        self.cancel_active_tool()
        self.clear_angle()
        self.clear_normal_line()
        self.clear_extension_line()

    def _selected_edge_summary(self) -> dict[str, object] | None:
        if self.selected_edge is None:
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
