from __future__ import annotations

from dataclasses import dataclass, field

from mipview.graph.model import ProjectionGraphLayer
from mipview.viewer.slice_geometry import Orientation


ORIENTATIONS: tuple[Orientation, ...] = ("axial", "coronal", "sagittal")


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
        self.pending_edge_orientation = orientation
        self.pending_edge_node_id = int(node_id)
        self.active_orientation = orientation

    def cancel_pending_edge(self) -> None:
        self.pending_edge_orientation = None
        self.pending_edge_node_id = None

    def exit_editing(self) -> None:
        self.editing_enabled = False
        self.cancel_pending_edge()

    def summary(self) -> dict[str, object]:
        return {
            "editing_enabled": self.editing_enabled,
            "visible": self.visible,
            "opacity": self.opacity,
            "node_size": self.node_size,
            "edge_thickness": self.edge_thickness,
            "active_orientation": self.active_orientation,
            "pending_edge": (
                None
                if self.pending_edge_orientation is None
                or self.pending_edge_node_id is None
                else {
                    "orientation": self.pending_edge_orientation,
                    "start_node_id": self.pending_edge_node_id,
                }
            ),
            "layers": {
                orientation: {
                    "plane_shape": (
                        None if layer.plane_shape is None else list(layer.plane_shape)
                    ),
                    "num_nodes": len(layer.nodes),
                    "num_edges": len(layer.edges),
                }
                for orientation, layer in self.layers.items()
            },
        }
