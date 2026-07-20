from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping

import numpy as np

from mipview.graph.measurement import (
    AngleMeasurement,
    calculate_unsigned_angle_degrees,
)
from mipview.graph.model import GraphEdge, ProjectionGraphLayer, VoxelGraph
from mipview.graph.spatial import build_projected_graph_layer
from mipview.graph.vector import GraphVector, GraphVectorKind, VECTOR_COLOR_PRESET
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
    pending_vector_orientation: Orientation | None = None
    pending_vector_source_node_id: int | None = None
    active_tool: GraphTool | None = None
    selected_node_id: int | None = None
    selected_edge_orientation: Orientation | None = None
    selected_edge: GraphEdge | None = None
    selected_vector_id: int | None = None
    normal_line_orientation: Orientation | None = None
    normal_line_edge: GraphEdge | None = None
    normal_line_thickness: int = 1
    extension_line_orientation: Orientation | None = None
    extension_line_edge: GraphEdge | None = None
    extension_line_thickness: int = 1
    curve_drag_active: bool = False
    angle_source_vector_id: int | None = None
    vectors: dict[int, GraphVector] = field(default_factory=dict)
    angle_measurements: dict[int, AngleMeasurement] = field(default_factory=dict)
    _next_vector_id: int = 1
    _next_measurement_id: int = 1
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
        self._ensure_node(node_id)
        self.cancel_active_tool()
        self.cancel_pending_vector()
        self.clear_selection()
        self.pending_edge_orientation = orientation
        self.pending_edge_node_id = int(node_id)
        self.active_orientation = orientation

    def cancel_pending_edge(self) -> None:
        self.pending_edge_orientation = None
        self.pending_edge_node_id = None

    def begin_vector(self, orientation: Orientation, source_node_id: int) -> None:
        self._ensure_node(source_node_id)
        self.cancel_active_tool()
        self.cancel_pending_edge()
        self.clear_selection()
        self.pending_vector_orientation = orientation
        self.pending_vector_source_node_id = int(source_node_id)
        self.active_orientation = orientation

    def cancel_pending_vector(self) -> None:
        self.pending_vector_orientation = None
        self.pending_vector_source_node_id = None

    def add_node_vector(
        self,
        orientation: Orientation,
        source_node_id: int,
        target_node_id: int,
    ) -> GraphVector:
        self._ensure_node(source_node_id)
        self._ensure_node(target_node_id)
        vector = self._new_vector(
            orientation=orientation,
            kind="node_pair",
            source_node_id=int(source_node_id),
            target_node_id=int(target_node_id),
        )
        self.cancel_pending_vector()
        self.selected_node_id = None
        self.selected_edge_orientation = None
        self.selected_edge = None
        self.selected_vector_id = vector.id
        self.active_orientation = orientation
        return vector

    def add_edge_vector(
        self,
        orientation: Orientation,
        edge: GraphEdge,
        kind: Literal["edge_tangent", "edge_normal"],
    ) -> GraphVector:
        if edge not in self.graph.edges:
            raise ValueError(
                f"Graph edge {edge.start_node_id}-{edge.end_node_id} does not exist."
            )
        if edge in self.graph.curve_control_points:
            raise ValueError("Tangent and normal vectors require a straight edge.")
        for existing in self.vectors.values():
            if (
                existing.orientation == orientation
                and existing.kind == kind
                and existing.edge == edge
            ):
                raise ValueError(
                    f"The {kind.removeprefix('edge_')} vector is already displayed "
                    f"for edge {edge.start_node_id}-{edge.end_node_id} in {orientation}."
                )
        vector = self._new_vector(orientation=orientation, kind=kind, edge=edge)
        self.selected_node_id = None
        self.selected_edge_orientation = None
        self.selected_edge = None
        self.selected_vector_id = vector.id
        self.active_orientation = orientation
        return vector

    def vector_for_edge(
        self,
        orientation: Orientation,
        edge: GraphEdge,
        kind: Literal["edge_tangent", "edge_normal"],
    ) -> GraphVector | None:
        return next(
            (
                vector
                for vector in self.vectors.values()
                if vector.orientation == orientation
                and vector.edge == edge
                and vector.kind == kind
            ),
            None,
        )

    def flip_vector(
        self,
        vector_id: int,
        node_positions: Mapping[int, tuple[float, float]],
        in_plane_spacing: tuple[float, float],
    ) -> GraphVector:
        vector = self._ensure_vector(vector_id)
        flipped = vector.flipped()
        self.vectors[flipped.id] = flipped
        self.selected_node_id = None
        self.selected_edge_orientation = None
        self.selected_edge = None
        self.selected_vector_id = flipped.id
        self._recalculate_measurements_for_vector(
            flipped.id,
            node_positions,
            in_plane_spacing,
        )
        return flipped

    def delete_vector(self, vector_id: int) -> GraphVector:
        vector = self._ensure_vector(vector_id)
        del self.vectors[vector.id]
        self._delete_measurements_for_vector(vector.id)
        if self.selected_vector_id == vector.id:
            self.selected_vector_id = None
        if self.angle_source_vector_id == vector.id:
            self.angle_source_vector_id = None
        return vector

    def activate_curve_tool(self) -> None:
        self.cancel_pending_edge()
        self.cancel_pending_vector()
        self.clear_selection()
        self.angle_source_vector_id = None
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
        self.invalidate_edge_vectors(edge)
        self.invalidate_construction_lines(edge)
        self.selected_node_id = None
        self.selected_vector_id = None
        self.active_tool = "curve_edge"
        self.selected_edge_orientation = orientation
        self.selected_edge = edge
        self.active_orientation = orientation
        self.curve_drag_active = False
        return edge

    def activate_angle_tool(self) -> None:
        self.cancel_pending_edge()
        self.cancel_pending_vector()
        self.clear_selection()
        self.curve_drag_active = False
        self.active_tool = "calculate_angle"
        self.angle_source_vector_id = None

    def select_angle_vector(
        self,
        vector_id: int,
        node_positions: Mapping[int, tuple[float, float]],
        in_plane_spacing: tuple[float, float],
    ) -> AngleMeasurement | None:
        if self.active_tool != "calculate_angle":
            raise ValueError("Calculate Angle tool is not active.")
        vector = self._ensure_vector(vector_id)
        self.selected_vector_id = vector.id
        self.active_orientation = vector.orientation
        if self.angle_source_vector_id is None:
            if any(
                vector.id
                in (measurement.source_vector_id, measurement.target_vector_id)
                for measurement in self.angle_measurements.values()
            ):
                raise ValueError(
                    f"Graph vector V{vector.id} already belongs to an angle pair. "
                    "Delete the existing angle before pairing again."
                )
            self.angle_source_vector_id = vector.id
            return None
        measurement = self.calculate_angle(
            self.angle_source_vector_id,
            vector.id,
            node_positions,
            in_plane_spacing,
        )
        self.angle_source_vector_id = None
        return measurement

    def calculate_angle(
        self,
        source_vector_id: int,
        target_vector_id: int,
        node_positions: Mapping[int, tuple[float, float]],
        in_plane_spacing: tuple[float, float],
    ) -> AngleMeasurement:
        source = self._ensure_vector(source_vector_id)
        target = self._ensure_vector(target_vector_id)
        if source.id == target.id:
            raise ValueError("Angle source and target vectors must be different.")
        if source.orientation != target.orientation:
            raise ValueError("Angle source and target vectors must share one projection.")
        paired_ids = {
            vector_id
            for measurement in self.angle_measurements.values()
            for vector_id in (
                measurement.source_vector_id,
                measurement.target_vector_id,
            )
        }
        already_paired = [
            vector_id
            for vector_id in (source.id, target.id)
            if vector_id in paired_ids
        ]
        if already_paired:
            labels = ", ".join(f"V{vector_id}" for vector_id in already_paired)
            raise ValueError(
                f"Graph vector(s) {labels} already belong to an angle pair. "
                "Delete the existing angle before pairing again."
            )
        angle = calculate_unsigned_angle_degrees(
            source,
            target,
            node_positions,
            in_plane_spacing,
        )
        measurement = AngleMeasurement(
            id=self._next_measurement_id,
            source_vector_id=source.id,
            target_vector_id=target.id,
            angle_degrees=angle,
        )
        self.angle_measurements[measurement.id] = measurement
        self._next_measurement_id += 1
        self.active_orientation = source.orientation
        return measurement

    def set_angle_label_position(
        self,
        measurement_id: int,
        x_fraction: float,
        y_fraction: float,
    ) -> AngleMeasurement:
        measurement = self._ensure_measurement(measurement_id)
        position = (float(x_fraction), float(y_fraction))
        if not all(np.isfinite(value) and 0.0 <= value <= 1.0 for value in position):
            raise ValueError(
                "Angle label position fractions must be finite values between 0.0 and 1.0."
            )
        updated = AngleMeasurement(
            id=measurement.id,
            source_vector_id=measurement.source_vector_id,
            target_vector_id=measurement.target_vector_id,
            angle_degrees=measurement.angle_degrees,
            label_position=position,
        )
        self.angle_measurements[updated.id] = updated
        return updated

    def effective_vector_color_index(self, vector_id: int) -> int:
        vector = self._ensure_vector(vector_id)
        for measurement in self.angle_measurements.values():
            if measurement.target_vector_id == vector.id:
                return self._ensure_vector(measurement.source_vector_id).color_index
        return vector.color_index

    def effective_vector_color(self, vector_id: int) -> str:
        return VECTOR_COLOR_PRESET[self.effective_vector_color_index(vector_id)]

    def delete_angle(self, measurement_id: int) -> AngleMeasurement:
        normalized = int(measurement_id)
        measurement = self.angle_measurements.get(normalized)
        if measurement is None:
            raise ValueError(f"Graph angle measurement A{normalized} does not exist.")
        del self.angle_measurements[normalized]
        return measurement

    def clear_angles(self) -> int:
        count = len(self.angle_measurements)
        self.angle_measurements.clear()
        self.angle_source_vector_id = None
        return count

    def cancel_active_tool(self) -> None:
        self.active_tool = None
        self.selected_edge_orientation = None
        self.selected_edge = None
        self.curve_drag_active = False
        self.angle_source_vector_id = None

    def select_node(self, orientation: Orientation, node_id: int) -> None:
        self._ensure_node(node_id)
        self.selected_node_id = int(node_id)
        self.selected_edge_orientation = None
        self.selected_edge = None
        self.selected_vector_id = None
        self.active_orientation = orientation

    def select_edge(self, orientation: Orientation, edge: GraphEdge) -> None:
        if edge not in self.graph.edges:
            raise ValueError(
                f"Graph edge {edge.start_node_id}-{edge.end_node_id} does not exist."
            )
        self.selected_node_id = None
        self.selected_edge_orientation = orientation
        self.selected_edge = edge
        self.selected_vector_id = None
        self.active_orientation = orientation

    def select_vector(self, vector_id: int) -> None:
        vector = self._ensure_vector(vector_id)
        self.selected_node_id = None
        self.selected_edge_orientation = None
        self.selected_edge = None
        self.selected_vector_id = vector.id
        self.active_orientation = vector.orientation

    def clear_selection(self) -> None:
        self.selected_node_id = None
        self.selected_edge_orientation = None
        self.selected_edge = None
        self.selected_vector_id = None

    def set_normal_line(
        self,
        orientation: Orientation,
        edge: GraphEdge,
        visible: bool,
    ) -> bool:
        self._validate_straight_edge(edge, "normal")
        if visible:
            self.normal_line_orientation = orientation
            self.normal_line_edge = edge
            return True
        if self.normal_line_orientation == orientation and self.normal_line_edge == edge:
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
        self._validate_straight_edge(edge, "extension")
        if visible:
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

    def invalidate_construction_lines(self, edge: GraphEdge) -> None:
        if self.normal_line_edge == edge:
            self.clear_normal_line()
        if self.extension_line_edge == edge:
            self.clear_extension_line()

    def clear_graph(self) -> tuple[int, int]:
        node_count = len(self.graph.nodes)
        edge_count = len(self.graph.edges)
        self.graph.clear()
        self.cancel_pending_edge()
        self.cancel_pending_vector()
        self.cancel_active_tool()
        self.clear_selection()
        self._clear_vectors_and_angles()
        self.clear_normal_line()
        self.clear_extension_line()
        return node_count, edge_count

    def invalidate_edge(self, edge: GraphEdge) -> None:
        if self.selected_edge == edge:
            self.selected_edge_orientation = None
            self.selected_edge = None
            self.curve_drag_active = False
        self.invalidate_edge_vectors(edge)
        self.invalidate_construction_lines(edge)

    def invalidate_edge_vectors(self, edge: GraphEdge) -> None:
        for vector_id in [
            vector.id for vector in self.vectors.values() if vector.references_edge(edge)
        ]:
            self.delete_vector(vector_id)

    def invalidate_node(self, node_id: int) -> None:
        normalized = int(node_id)
        if self.selected_node_id == normalized:
            self.selected_node_id = None
        if self.selected_edge is not None and normalized in (
            self.selected_edge.start_node_id,
            self.selected_edge.end_node_id,
        ):
            self.selected_edge_orientation = None
            self.selected_edge = None
            self.curve_drag_active = False
        if self.pending_edge_node_id == normalized:
            self.cancel_pending_edge()
        if self.pending_vector_source_node_id == normalized:
            self.cancel_pending_vector()
        for vector_id in [
            vector.id
            for vector in self.vectors.values()
            if vector.references_node(normalized)
        ]:
            self.delete_vector(vector_id)
        for edge in (self.normal_line_edge, self.extension_line_edge):
            if edge is not None and normalized in (
                edge.start_node_id,
                edge.end_node_id,
            ):
                self.invalidate_construction_lines(edge)

    def exit_editing(self) -> None:
        self.editing_enabled = False
        self.cancel_pending_edge()
        self.cancel_pending_vector()
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
            "selected_node_id": self.selected_node_id,
            "selected_edge": self._selected_edge_summary(),
            "selected_vector_id": self.selected_vector_id,
            "normal_line": self._construction_line_summary(
                self.normal_line_orientation,
                self.normal_line_edge,
                self.normal_line_thickness,
            ),
            "extension_line": self._construction_line_summary(
                self.extension_line_orientation,
                self.extension_line_edge,
                self.extension_line_thickness,
            ),
            "curve_drag_active": self.curve_drag_active,
            "pending_edge": (
                None
                if self.pending_edge_node_id is None
                else {
                    "orientation": self.pending_edge_orientation,
                    "start_node_id": self.pending_edge_node_id,
                }
            ),
            "pending_vector": (
                None
                if self.pending_vector_source_node_id is None
                else {
                    "orientation": self.pending_vector_orientation,
                    "source_node_id": self.pending_vector_source_node_id,
                }
            ),
            "angle_selection": {
                "source_vector_id": self.angle_source_vector_id,
                "orientation": (
                    None
                    if self.angle_source_vector_id is None
                    else self.vectors[self.angle_source_vector_id].orientation
                ),
            },
            "vectors": [
                self._vector_summary(vector)
                for vector in sorted(self.vectors.values(), key=lambda item: item.id)
            ],
            "angle_measurements": [
                {
                    "id": measurement.id,
                    "source_vector_id": measurement.source_vector_id,
                    "target_vector_id": measurement.target_vector_id,
                    "angle_degrees": measurement.angle_degrees,
                    "label_position": (
                        None
                        if measurement.label_position is None
                        else list(measurement.label_position)
                    ),
                    "color": self.effective_vector_color(
                        measurement.source_vector_id
                    ),
                }
                for measurement in sorted(
                    self.angle_measurements.values(), key=lambda item: item.id
                )
            ],
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

    def _new_vector(
        self,
        *,
        orientation: Orientation,
        kind: GraphVectorKind,
        source_node_id: int | None = None,
        target_node_id: int | None = None,
        edge: GraphEdge | None = None,
    ) -> GraphVector:
        vector = GraphVector(
            id=self._next_vector_id,
            orientation=orientation,
            kind=kind,
            color_index=(self._next_vector_id - 1) % len(VECTOR_COLOR_PRESET),
            source_node_id=source_node_id,
            target_node_id=target_node_id,
            edge=edge,
        )
        self.vectors[vector.id] = vector
        self._next_vector_id += 1
        return vector

    def _recalculate_measurements_for_vector(
        self,
        vector_id: int,
        node_positions: Mapping[int, tuple[float, float]],
        in_plane_spacing: tuple[float, float],
    ) -> None:
        for measurement_id, measurement in tuple(self.angle_measurements.items()):
            if vector_id not in (
                measurement.source_vector_id,
                measurement.target_vector_id,
            ):
                continue
            source = self.vectors[measurement.source_vector_id]
            target = self.vectors[measurement.target_vector_id]
            self.angle_measurements[measurement_id] = AngleMeasurement(
                id=measurement.id,
                source_vector_id=source.id,
                target_vector_id=target.id,
                angle_degrees=calculate_unsigned_angle_degrees(
                    source,
                    target,
                    node_positions,
                    in_plane_spacing,
                ),
                label_position=measurement.label_position,
            )

    def _delete_measurements_for_vector(self, vector_id: int) -> None:
        for measurement_id in [
            measurement.id
            for measurement in self.angle_measurements.values()
            if vector_id
            in (measurement.source_vector_id, measurement.target_vector_id)
        ]:
            del self.angle_measurements[measurement_id]

    def _clear_vectors_and_angles(self) -> None:
        self.vectors.clear()
        self.angle_measurements.clear()
        self.selected_vector_id = None
        self.angle_source_vector_id = None
        self._next_vector_id = 1
        self._next_measurement_id = 1

    def _clear_after_geometry_change(self) -> None:
        self.cancel_pending_edge()
        self.cancel_pending_vector()
        self.cancel_active_tool()
        self._clear_vectors_and_angles()
        self.clear_selection()
        self.clear_normal_line()
        self.clear_extension_line()

    def _ensure_node(self, node_id: int) -> None:
        normalized = int(node_id)
        if normalized not in self.graph.nodes:
            raise ValueError(f"Graph node {normalized} does not exist.")

    def _ensure_vector(self, vector_id: int) -> GraphVector:
        normalized = int(vector_id)
        vector = self.vectors.get(normalized)
        if vector is None:
            raise ValueError(f"Graph vector V{normalized} does not exist.")
        return vector

    def _ensure_measurement(self, measurement_id: int) -> AngleMeasurement:
        normalized = int(measurement_id)
        measurement = self.angle_measurements.get(normalized)
        if measurement is None:
            raise ValueError(f"Graph angle measurement A{normalized} does not exist.")
        return measurement

    def _validate_straight_edge(self, edge: GraphEdge, line_name: str) -> None:
        if edge not in self.graph.edges:
            raise ValueError(
                f"Graph edge {edge.start_node_id}-{edge.end_node_id} does not exist."
            )
        if edge in self.graph.curve_control_points:
            raise ValueError(
                f"A {line_name} line is available only for a straight edge."
            )

    def _selected_edge_summary(self) -> dict[str, object] | None:
        if self.selected_edge is None:
            return None
        return {
            "orientation": self.selected_edge_orientation,
            "start_node_id": self.selected_edge.start_node_id,
            "end_node_id": self.selected_edge.end_node_id,
        }

    @staticmethod
    def _construction_line_summary(
        orientation: Orientation | None,
        edge: GraphEdge | None,
        thickness: int,
    ) -> dict[str, object] | None:
        if edge is None:
            return None
        return {
            "orientation": orientation,
            "start_node_id": edge.start_node_id,
            "end_node_id": edge.end_node_id,
            "thickness": thickness,
        }

    def _vector_summary(self, vector: GraphVector) -> dict[str, object]:
        return {
            "id": vector.id,
            "orientation": vector.orientation,
            "kind": vector.kind,
            "source_node_id": vector.source_node_id,
            "target_node_id": vector.target_node_id,
            "edge": (
                None
                if vector.edge is None
                else {
                    "start_node_id": vector.edge.start_node_id,
                    "end_node_id": vector.edge.end_node_id,
                }
            ),
            "reversed": vector.reversed,
            "color_index": vector.color_index,
            "original_color": vector.color,
            "color": self.effective_vector_color(vector.id),
        }
