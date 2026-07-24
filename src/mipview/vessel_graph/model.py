from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from mipview.viewer.slice_geometry import Orientation


VESSEL_NODE_COLOR = (255, 0, 0)
VESSEL_EDGE_COLOR = (57, 255, 20)
PROJECTED_INTERCEPT_COLOR = (30, 144, 255)


@dataclass(frozen=True)
class VesselGraphData:
    """Immutable full-volume vessel graph loaded from GraphML."""

    node_ids: tuple[str, ...]
    node_source_voxels: np.ndarray
    node_world_positions: np.ndarray
    node_radii: np.ndarray
    node_components: np.ndarray
    edge_node_indices: np.ndarray
    edge_centerline_source_voxels: np.ndarray
    edge_centerline_offsets: np.ndarray
    edge_components: np.ndarray
    original_shape: tuple[int, int, int]
    original_affine: np.ndarray
    original_to_loaded_voxel_affine: np.ndarray
    loaded_shape: tuple[int, int, int]

    @property
    def node_count(self) -> int:
        return int(self.node_world_positions.shape[0])

    @property
    def edge_count(self) -> int:
        return int(self.edge_node_indices.shape[0])

    @property
    def centerline_point_count(self) -> int:
        return int(self.edge_centerline_source_voxels.shape[0])

    @property
    def component_count(self) -> int:
        components = np.concatenate(
            (
                self.node_components[self.node_components >= 0],
                self.edge_components[self.edge_components >= 0],
            )
        )
        return int(np.unique(components).size) if components.size else 0

    def edge_centerline(self, edge_index: int) -> np.ndarray:
        start = int(self.edge_centerline_offsets[edge_index])
        end = int(self.edge_centerline_offsets[edge_index + 1])
        return self.edge_centerline_source_voxels[start:end]


@dataclass
class VesselGraphDisplaySettings:
    """One viewer's display settings for a loaded GraphML layer."""

    visible: bool = False
    opacity: float = 1.0
    node_size: int = 4
    edge_thickness: int = 2

    def set_opacity(self, opacity: float) -> None:
        self.opacity = min(max(float(opacity), 0.0), 1.0)

    def set_node_size(self, node_size: int) -> None:
        self.node_size = min(max(int(node_size), 1), 10)

    def set_edge_thickness(self, edge_thickness: int) -> None:
        self.edge_thickness = min(max(int(edge_thickness), 1), 10)


@dataclass
class VesselGraphLayer:
    """Main-session GraphML layer with immutable data and main-view settings."""

    id: str
    path: Path
    data: VesselGraphData
    warnings: tuple[str, ...] = ()
    projection_safe: bool = True
    settings: VesselGraphDisplaySettings = field(
        default_factory=VesselGraphDisplaySettings
    )

    @property
    def display_name(self) -> str:
        prefix = "⚠ " if self.warnings else ""
        return f"{prefix}{self.path.name}"

    def status(self) -> dict[str, object]:
        return {
            "id": self.id,
            "path": str(self.path),
            "display_name": self.display_name,
            "node_count": self.data.node_count,
            "edge_count": self.data.edge_count,
            "centerline_point_count": self.data.centerline_point_count,
            "component_count": self.data.component_count,
            "projection_safe": self.projection_safe,
            "warnings": list(self.warnings),
            "visible": self.settings.visible,
            "opacity": self.settings.opacity,
            "node_size": self.settings.node_size,
            "edge_thickness": self.settings.edge_thickness,
        }


@dataclass(frozen=True)
class ClippedVesselGraph:
    """Patch-clipped vessel geometry in patch-local loaded voxel and world space."""

    patch_shape: tuple[int, int, int]
    patch_affine: np.ndarray
    polylines_patch_voxel: tuple[np.ndarray, ...]
    polylines_world: tuple[np.ndarray, ...]
    node_patch_voxels: np.ndarray
    node_world_positions: np.ndarray
    intercept_patch_voxels: np.ndarray
    intercept_world_positions: np.ndarray

    @property
    def is_empty(self) -> bool:
        return (
            not self.polylines_patch_voxel
            and self.node_patch_voxels.size == 0
            and self.intercept_patch_voxels.size == 0
        )


@dataclass(frozen=True)
class ProjectedVesselGraphLayer:
    """Read-only 2D projection derived from one patch-clipped GraphML layer."""

    orientation: Orientation
    plane_shape: tuple[int, int]
    polylines: tuple[np.ndarray, ...]
    node_positions: np.ndarray
    intercept_positions: np.ndarray


@dataclass(frozen=True)
class VesselGraphRenderGeometry:
    """World-space data consumed by one standalone 3D graph layer."""

    polylines_world: tuple[np.ndarray, ...]
    node_world_positions: np.ndarray
    intercept_world_positions: np.ndarray = field(
        default_factory=lambda: np.empty((0, 3), dtype=np.float64)
    )
