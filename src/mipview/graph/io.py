from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any

import numpy as np

from mipview.graph.measurement import (
    AngleMeasurement,
    calculate_unsigned_angle_degrees,
)
from mipview.graph.model import GraphEdge, GraphNode, VoxelGraph
from mipview.graph.state import ORIENTATIONS, ProjectionGraphState
from mipview.graph.vector import GraphVector, VECTOR_COLOR_PRESET
from mipview.patch.selector import PatchBounds
from mipview.viewer.slice_geometry import Orientation


GRAPH_STATE_FORMAT = "mipview-graph-state"
GRAPH_STATE_VERSION = 2
SUPPORTED_GRAPH_STATE_VERSIONS = (1, GRAPH_STATE_VERSION)
AFFINE_ABSOLUTE_TOLERANCE = 1e-5
ANGLE_ABSOLUTE_TOLERANCE = 1e-6

VectorGeometryProvider = Callable[
    [ProjectionGraphState, Orientation],
    tuple[Mapping[int, tuple[float, float]], tuple[float, float]],
]


@dataclass(frozen=True)
class GraphFileContext:
    source_image_path: Path | None
    patch_shape: tuple[int, int, int]
    patch_bounds: PatchBounds | None
    patch_affine: np.ndarray
    voxel_spacing: tuple[float, float, float]
    projection_mode: str = "MIP"
    enabled_orientations: tuple[Orientation, ...] = ()


@dataclass(frozen=True)
class GraphRestoreMetadata:
    version: int
    source_image_path: Path | None
    patch_shape: tuple[int, int, int]
    patch_bounds: PatchBounds | None
    patch_affine: np.ndarray
    voxel_spacing: tuple[float, float, float]
    projection_mode: str
    enabled_orientations: tuple[Orientation, ...]


@dataclass(frozen=True)
class GraphLoadResult:
    state: ProjectionGraphState
    warnings: tuple[str, ...]
    counts: dict[str, int]
    version: int
    projection_mode: str
    enabled_orientations: tuple[Orientation, ...]


def graph_state_counts(state: ProjectionGraphState) -> dict[str, int]:
    return {
        "nodes": len(state.graph.nodes),
        "edges": len(state.graph.edges),
        "curves": len(state.graph.curve_control_points),
        "vectors": len(state.vectors),
        "angles": len(state.angle_measurements),
        "construction_lines": sum(
            edge is not None
            for edge in (state.extension_line_edge, state.normal_line_edge)
        ),
    }


def save_graph_state_file(
    path: str | Path,
    state: ProjectionGraphState,
    context: GraphFileContext,
    *,
    overwrite: bool = False,
) -> Path:
    output_path = Path(path)
    if not str(output_path).strip():
        raise ValueError("Graph state path is required.")
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"Graph state file already exists: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    document = graph_state_document(state, context)

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output_path.name}.",
        suffix=".tmp",
        dir=output_path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(
                document,
                stream,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if output_path.exists() and not overwrite:
            raise FileExistsError(f"Graph state file already exists: {output_path}")
        os.replace(temporary_path, output_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    return output_path


def load_graph_state_file(
    path: str | Path,
    context: GraphFileContext,
    geometry_provider: VectorGeometryProvider,
) -> GraphLoadResult:
    document = _read_graph_document(path)
    return graph_state_from_document(document, context, geometry_provider)


def read_graph_restore_metadata(path: str | Path) -> GraphRestoreMetadata:
    """Read the spatial and projection metadata needed to recreate a patch window."""

    root = _validated_root(_read_graph_document(path))
    version = _graph_document_version(root)
    source = _parse_source_metadata(_require_object(root.get("source"), "source"))
    projection_mode, enabled_orientations = _parse_projection_settings(root, version)
    return GraphRestoreMetadata(
        version=version,
        source_image_path=source[0],
        patch_shape=source[1],
        patch_bounds=source[2],
        patch_affine=source[3],
        voxel_spacing=source[4],
        projection_mode=projection_mode,
        enabled_orientations=enabled_orientations,
    )


def graph_state_document(
    state: ProjectionGraphState,
    context: GraphFileContext,
) -> dict[str, object]:
    graph = state.graph
    if graph.volume_shape != context.patch_shape:
        raise ValueError(
            "Graph volume shape does not match the patch context being saved."
        )
    affine = np.asarray(context.patch_affine, dtype=np.float64)
    if affine.shape != (4, 4) or not np.all(np.isfinite(affine)):
        raise ValueError("Patch affine must be a finite 4x4 matrix.")
    if len(context.voxel_spacing) != 3 or not all(
        math.isfinite(value) and value > 0.0 for value in context.voxel_spacing
    ):
        raise ValueError("Patch voxel spacing must contain three positive finite values.")
    return {
        "format": GRAPH_STATE_FORMAT,
        "version": GRAPH_STATE_VERSION,
        "source": {
            "image_path": (
                None
                if context.source_image_path is None
                else str(context.source_image_path.resolve(strict=False))
            ),
            "patch_shape": list(context.patch_shape),
            "patch_bounds": _bounds_payload(context.patch_bounds),
            "patch_affine": affine.tolist(),
            "voxel_spacing": [float(value) for value in context.voxel_spacing],
        },
        "projection": _projection_payload(context),
        "display": {
            "visible": state.visible,
            "opacity": state.opacity,
            "node_size": state.node_size,
            "edge_thickness": state.edge_thickness,
        },
        "graph": {
            "nodes": [
                {"id": node.id, "patch_voxel": list(node.position())}
                for node in sorted(graph.nodes.values(), key=lambda item: item.id)
            ],
            "edges": [
                {
                    "start_node_id": edge.start_node_id,
                    "end_node_id": edge.end_node_id,
                    "control_patch_voxel": (
                        None
                        if edge not in graph.curve_control_points
                        else list(graph.curve_control_points[edge])
                    ),
                }
                for edge in sorted(graph.edges)
            ],
        },
        "vectors": [
            {
                "id": vector.id,
                "orientation": vector.orientation,
                "kind": vector.kind,
                "source_node_id": vector.source_node_id,
                "target_node_id": vector.target_node_id,
                "edge": _edge_payload(vector.edge),
                "reversed": vector.reversed,
                "color_index": vector.color_index,
                "color": vector.color,
            }
            for vector in sorted(state.vectors.values(), key=lambda item: item.id)
        ],
        "angles": [
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
            }
            for measurement in sorted(
                state.angle_measurements.values(), key=lambda item: item.id
            )
        ],
        "construction_lines": {
            "extension": _line_payload(
                state.extension_line_orientation,
                state.extension_line_edge,
                state.extension_line_thickness,
            ),
            "normal": _line_payload(
                state.normal_line_orientation,
                state.normal_line_edge,
                state.normal_line_thickness,
            ),
        },
    }


def graph_state_from_document(
    document: object,
    context: GraphFileContext,
    geometry_provider: VectorGeometryProvider,
) -> GraphLoadResult:
    root = _validated_root(document)
    version = _graph_document_version(root)
    projection_mode, enabled_orientations = _parse_projection_settings(root, version)

    warnings = _validate_source_context(
        _require_object(root.get("source"), "source"), context
    )
    display = _require_object(root.get("display"), "display")
    visible = _require_bool(display.get("visible"), "display.visible")
    opacity = _require_float(
        display.get("opacity"), "display.opacity", minimum=0.0, maximum=1.0
    )
    node_size = _require_int(
        display.get("node_size"), "display.node_size", minimum=1, maximum=10
    )
    edge_thickness = _require_int(
        display.get("edge_thickness"),
        "display.edge_thickness",
        minimum=1,
        maximum=10,
    )

    graph_payload = _require_object(root.get("graph"), "graph")
    nodes: dict[int, GraphNode] = {}
    for index, item in enumerate(_require_list(graph_payload.get("nodes"), "graph.nodes")):
        payload = _require_object(item, f"graph.nodes[{index}]")
        node_id = _require_int(payload.get("id"), f"graph.nodes[{index}].id", minimum=1)
        if node_id in nodes:
            raise ValueError(f"Duplicate graph node ID {node_id}.")
        position_values = _require_list(
            payload.get("patch_voxel"), f"graph.nodes[{index}].patch_voxel", length=3
        )
        position = tuple(
            _require_int(value, f"graph.nodes[{index}].patch_voxel[{axis}]")
            for axis, value in enumerate(position_values)
        )
        if any(
            coordinate < 0 or coordinate >= context.patch_shape[axis]
            for axis, coordinate in enumerate(position)
        ):
            raise ValueError(
                f"Graph node {node_id} patch voxel {position} is outside shape "
                f"{context.patch_shape}."
            )
        if any(node.position() == position for node in nodes.values()):
            raise ValueError(f"Duplicate graph node voxel {position}.")
        nodes[node_id] = GraphNode(node_id, *position)

    edges: set[GraphEdge] = set()
    curve_controls: dict[GraphEdge, tuple[float, float, float]] = {}
    for index, item in enumerate(_require_list(graph_payload.get("edges"), "graph.edges")):
        payload = _require_object(item, f"graph.edges[{index}]")
        edge = _parse_edge(payload, f"graph.edges[{index}]")
        if edge in edges:
            raise ValueError(
                f"Duplicate graph edge {edge.start_node_id}-{edge.end_node_id}."
            )
        missing = [
            node_id
            for node_id in (edge.start_node_id, edge.end_node_id)
            if node_id not in nodes
        ]
        if missing:
            raise ValueError(f"Graph edge references missing node(s): {missing}.")
        edges.add(edge)
        control_payload = payload.get("control_patch_voxel")
        if control_payload is not None:
            values = _require_list(
                control_payload,
                f"graph.edges[{index}].control_patch_voxel",
                length=3,
            )
            control = tuple(
                _require_float(
                    value,
                    f"graph.edges[{index}].control_patch_voxel[{axis}]",
                )
                for axis, value in enumerate(values)
            )
            if any(
                coordinate < 0.0 or coordinate > context.patch_shape[axis] - 1
                for axis, coordinate in enumerate(control)
            ):
                raise ValueError(
                    f"Curve control point {control} is outside shape {context.patch_shape}."
                )
            curve_controls[edge] = control  # type: ignore[assignment]

    voxel_graph = VoxelGraph(
        volume_shape=context.patch_shape,
        nodes=nodes,
        edges=edges,
        curve_control_points=curve_controls,
        _next_node_id=max(nodes, default=0) + 1,
    )
    state = ProjectionGraphState(
        graph=voxel_graph,
        visible=visible,
        opacity=opacity,
        node_size=node_size,
        edge_thickness=edge_thickness,
    )

    for index, item in enumerate(_require_list(root.get("vectors"), "vectors")):
        payload = _require_object(item, f"vectors[{index}]")
        vector_id = _require_int(payload.get("id"), f"vectors[{index}].id", minimum=1)
        if vector_id in state.vectors:
            raise ValueError(f"Duplicate graph vector ID {vector_id}.")
        orientation = _require_orientation(
            payload.get("orientation"), f"vectors[{index}].orientation"
        )
        kind = payload.get("kind")
        if kind not in ("node_pair", "edge_tangent", "edge_normal"):
            raise ValueError(f"vectors[{index}].kind is invalid: {kind!r}.")
        color_index = _require_int(
            payload.get("color_index"),
            f"vectors[{index}].color_index",
            minimum=0,
            maximum=len(VECTOR_COLOR_PRESET) - 1,
        )
        if payload.get("color") != VECTOR_COLOR_PRESET[color_index]:
            raise ValueError(f"vectors[{index}].color does not match its palette index.")
        reversed_value = _require_bool(
            payload.get("reversed"), f"vectors[{index}].reversed"
        )
        edge_payload = payload.get("edge")
        edge = None if edge_payload is None else _parse_edge(
            _require_object(edge_payload, f"vectors[{index}].edge"),
            f"vectors[{index}].edge",
        )
        source_node_id = _optional_int(
            payload.get("source_node_id"), f"vectors[{index}].source_node_id"
        )
        target_node_id = _optional_int(
            payload.get("target_node_id"), f"vectors[{index}].target_node_id"
        )
        try:
            vector = GraphVector(
                id=vector_id,
                orientation=orientation,
                kind=kind,  # type: ignore[arg-type]
                color_index=color_index,
                source_node_id=source_node_id,
                target_node_id=target_node_id,
                edge=edge,
                reversed=reversed_value,
            )
        except ValueError as exc:
            raise ValueError(f"Invalid vectors[{index}]: {exc}") from exc
        if vector.kind == "node_pair":
            referenced_nodes = (vector.source_node_id, vector.target_node_id)
        else:
            if vector.edge not in edges:
                raise ValueError(f"Vector V{vector.id} references a missing graph edge.")
            if vector.edge in curve_controls:
                raise ValueError(f"Vector V{vector.id} requires a straight graph edge.")
            assert vector.edge is not None
            referenced_nodes = (vector.edge.start_node_id, vector.edge.end_node_id)
        if any(node_id not in nodes for node_id in referenced_nodes):
            raise ValueError(f"Vector V{vector.id} references a missing graph node.")
        state.vectors[vector.id] = vector
    state._next_vector_id = max(state.vectors, default=0) + 1

    paired_vector_ids: set[int] = set()
    for index, item in enumerate(_require_list(root.get("angles"), "angles")):
        payload = _require_object(item, f"angles[{index}]")
        measurement_id = _require_int(
            payload.get("id"), f"angles[{index}].id", minimum=1
        )
        if measurement_id in state.angle_measurements:
            raise ValueError(f"Duplicate graph angle ID {measurement_id}.")
        source_id = _require_int(
            payload.get("source_vector_id"),
            f"angles[{index}].source_vector_id",
            minimum=1,
        )
        target_id = _require_int(
            payload.get("target_vector_id"),
            f"angles[{index}].target_vector_id",
            minimum=1,
        )
        if source_id == target_id:
            raise ValueError(f"Angle A{measurement_id} pairs one vector with itself.")
        if source_id not in state.vectors or target_id not in state.vectors:
            raise ValueError(f"Angle A{measurement_id} references a missing vector.")
        reused = paired_vector_ids.intersection((source_id, target_id))
        if reused:
            labels = ", ".join(f"V{value}" for value in sorted(reused))
            raise ValueError(f"Angle A{measurement_id} reuses paired vector(s) {labels}.")
        source_vector = state.vectors[source_id]
        target_vector = state.vectors[target_id]
        if source_vector.orientation != target_vector.orientation:
            raise ValueError(f"Angle A{measurement_id} crosses projection orientations.")
        saved_angle = _require_float(
            payload.get("angle_degrees"),
            f"angles[{index}].angle_degrees",
            minimum=0.0,
            maximum=180.0,
        )
        positions, spacing = geometry_provider(state, source_vector.orientation)
        calculated_angle = calculate_unsigned_angle_degrees(
            source_vector, target_vector, positions, spacing
        )
        if not math.isclose(
            saved_angle,
            calculated_angle,
            rel_tol=0.0,
            abs_tol=ANGLE_ABSOLUTE_TOLERANCE,
        ):
            raise ValueError(
                f"Angle A{measurement_id} does not match the current patch geometry."
            )
        label_payload = payload.get("label_position")
        label_position = None
        if label_payload is not None:
            values = _require_list(
                label_payload, f"angles[{index}].label_position", length=2
            )
            label_position = tuple(
                _require_float(
                    value,
                    f"angles[{index}].label_position[{axis}]",
                    minimum=0.0,
                    maximum=1.0,
                )
                for axis, value in enumerate(values)
            )
        state.angle_measurements[measurement_id] = AngleMeasurement(
            id=measurement_id,
            source_vector_id=source_id,
            target_vector_id=target_id,
            angle_degrees=calculated_angle,
            label_position=label_position,  # type: ignore[arg-type]
        )
        paired_vector_ids.update((source_id, target_id))
    state._next_measurement_id = max(state.angle_measurements, default=0) + 1

    lines = _require_object(root.get("construction_lines"), "construction_lines")
    (
        state.extension_line_orientation,
        state.extension_line_edge,
        state.extension_line_thickness,
    ) = _parse_line(lines.get("extension"), "construction_lines.extension", state)
    (
        state.normal_line_orientation,
        state.normal_line_edge,
        state.normal_line_thickness,
    ) = _parse_line(lines.get("normal"), "construction_lines.normal", state)

    counts = graph_state_counts(state)
    return GraphLoadResult(
        state=state,
        warnings=tuple(warnings),
        counts=counts,
        version=version,
        projection_mode=projection_mode,
        enabled_orientations=enabled_orientations,
    )


def _read_graph_document(path: str | Path) -> object:
    input_path = Path(path)
    if not input_path.exists():
        raise FileNotFoundError(f"Graph state file not found: {input_path}")
    if not input_path.is_file():
        raise ValueError(f"Expected a graph state file, got: {input_path}")
    try:
        with input_path.open("r", encoding="utf-8") as stream:
            return json.load(stream)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Invalid graph state JSON at line {exc.lineno}, column {exc.colno}."
        ) from exc


def _validated_root(document: object) -> dict[str, Any]:
    root = _require_object(document, "root")
    if root.get("format") != GRAPH_STATE_FORMAT:
        raise ValueError("The file is not a MipView graph state document.")
    return root


def _graph_document_version(root: dict[str, Any]) -> int:
    version = _require_int(root.get("version"), "version", minimum=1)
    if version not in SUPPORTED_GRAPH_STATE_VERSIONS:
        supported = ", ".join(str(value) for value in SUPPORTED_GRAPH_STATE_VERSIONS)
        raise ValueError(
            f"Unsupported graph state version {version}; supported versions are "
            f"{supported}."
        )
    return version


def _projection_payload(context: GraphFileContext) -> dict[str, object]:
    mode = context.projection_mode.strip().upper()
    if mode not in {"MIP", "MINIP"}:
        raise ValueError("Projection mode must be MIP or MinIP.")
    orientations: list[Orientation] = []
    for orientation in context.enabled_orientations:
        if orientation not in ORIENTATIONS:
            raise ValueError(
                "Enabled projection orientations must be axial, coronal, or sagittal."
            )
        if orientation in orientations:
            raise ValueError(f"Duplicate enabled projection orientation: {orientation}.")
        orientations.append(orientation)
    return {
        "mode": mode,
        "enabled_orientations": orientations,
    }


def _parse_projection_settings(
    root: dict[str, Any], version: int
) -> tuple[str, tuple[Orientation, ...]]:
    if version == 1:
        # Version 1 did not persist projection state. Keep every orientation off.
        return ("MIP", ())
    payload = _require_object(root.get("projection"), "projection")
    mode_value = payload.get("mode")
    if not isinstance(mode_value, str) or mode_value.strip().upper() not in {
        "MIP",
        "MINIP",
    }:
        raise ValueError("projection.mode must be MIP or MinIP.")
    mode = mode_value.strip().upper()
    orientations: list[Orientation] = []
    for index, value in enumerate(
        _require_list(
            payload.get("enabled_orientations"),
            "projection.enabled_orientations",
        )
    ):
        orientation = _require_orientation(
            value, f"projection.enabled_orientations[{index}]"
        )
        if orientation in orientations:
            raise ValueError(
                f"Duplicate enabled projection orientation: {orientation}."
            )
        orientations.append(orientation)
    return (mode, tuple(orientations))


def _parse_source_metadata(payload: dict[str, Any]) -> tuple[
    Path | None,
    tuple[int, int, int],
    PatchBounds | None,
    np.ndarray,
    tuple[float, float, float],
]:
    shape = tuple(
        _require_int(value, f"source.patch_shape[{axis}]", minimum=1)
        for axis, value in enumerate(
            _require_list(payload.get("patch_shape"), "source.patch_shape", length=3)
        )
    )
    saved_bounds = _parse_bounds(payload.get("patch_bounds"))
    affine_values = _require_list(
        payload.get("patch_affine"), "source.patch_affine", length=4
    )
    affine = np.asarray(
        [
            [
                _require_float(value, f"source.patch_affine[{row}][{column}]")
                for column, value in enumerate(
                    _require_list(row_values, f"source.patch_affine[{row}]", length=4)
                )
            ]
            for row, row_values in enumerate(affine_values)
        ],
        dtype=np.float64,
    )
    spacing_values = _require_list(
        payload.get("voxel_spacing"), "source.voxel_spacing", length=3
    )
    spacing = tuple(
        _require_float(
            value, f"source.voxel_spacing[{axis}]", minimum=0.0, exclusive_minimum=True
        )
        for axis, value in enumerate(spacing_values)
    )
    saved_path_value = payload.get("image_path")
    if saved_path_value is not None and not isinstance(saved_path_value, str):
        raise ValueError("source.image_path must be a string or null.")
    saved_path = None if saved_path_value is None else Path(saved_path_value)
    return (saved_path, shape, saved_bounds, affine, spacing)


def _validate_source_context(
    payload: dict[str, Any], context: GraphFileContext
) -> list[str]:
    saved_path, shape, saved_bounds, affine, spacing = _parse_source_metadata(payload)
    if shape != context.patch_shape:
        raise ValueError(
            f"Graph patch shape {shape} does not match current patch shape "
            f"{context.patch_shape}."
        )
    if saved_bounds != context.patch_bounds:
        raise ValueError("Graph patch bounds do not match the current patch bounds.")
    current_affine = np.asarray(context.patch_affine, dtype=np.float64)
    if current_affine.shape != (4, 4) or not np.all(np.isfinite(current_affine)):
        raise ValueError("Current patch affine is invalid.")
    if not np.allclose(
        affine,
        current_affine,
        rtol=0.0,
        atol=AFFINE_ABSOLUTE_TOLERANCE,
    ):
        raise ValueError("Graph patch affine does not match the current patch affine.")
    current_spacing = tuple(float(value) for value in context.voxel_spacing)
    if len(current_spacing) != 3 or not all(
        math.isfinite(value) and value > 0.0 for value in current_spacing
    ):
        raise ValueError("Current patch voxel spacing is invalid.")
    if not np.allclose(spacing, current_spacing, rtol=1e-6, atol=1e-6):
        raise ValueError(
            "Graph patch voxel spacing does not match the current patch spacing."
        )

    current_path = (
        None
        if context.source_image_path is None
        else str(context.source_image_path.resolve(strict=False))
    )
    saved_path_value = (
        None if saved_path is None else str(saved_path.resolve(strict=False))
    )
    warnings: list[str] = []
    if saved_path_value != current_path:
        warnings.append(
            "The source image path differs from the saved graph; compatible patch "
            "geometry was used."
        )
    return warnings


def _parse_line(
    value: object,
    label: str,
    state: ProjectionGraphState,
) -> tuple[Orientation | None, GraphEdge | None, int]:
    payload = _require_object(value, label)
    visible = _require_bool(payload.get("visible"), f"{label}.visible")
    thickness = _require_int(
        payload.get("thickness"), f"{label}.thickness", minimum=1, maximum=10
    )
    if not visible:
        if payload.get("orientation") is not None or payload.get("edge") is not None:
            raise ValueError(
                f"{label} must not reference an orientation or edge while hidden."
            )
        return (None, None, thickness)
    orientation = _require_orientation(payload.get("orientation"), f"{label}.orientation")
    edge = _parse_edge(
        _require_object(payload.get("edge"), f"{label}.edge"), f"{label}.edge"
    )
    state._validate_straight_edge(edge, label.rsplit(".", 1)[-1])
    return (orientation, edge, thickness)


def _parse_edge(payload: dict[str, Any], label: str) -> GraphEdge:
    start = _require_int(payload.get("start_node_id"), f"{label}.start_node_id", minimum=1)
    end = _require_int(payload.get("end_node_id"), f"{label}.end_node_id", minimum=1)
    try:
        return GraphEdge.between(start, end)
    except ValueError as exc:
        raise ValueError(f"Invalid {label}: {exc}") from exc


def _parse_bounds(value: object) -> PatchBounds | None:
    if value is None:
        return None
    payload = _require_object(value, "source.patch_bounds")
    values = {
        name: _require_int(payload.get(name), f"source.patch_bounds.{name}")
        for name in (
            "x_start",
            "x_end",
            "y_start",
            "y_end",
            "z_start",
            "z_end",
        )
    }
    bounds = PatchBounds(**values)
    if not (
        bounds.x_start < bounds.x_end
        and bounds.y_start < bounds.y_end
        and bounds.z_start < bounds.z_end
    ):
        raise ValueError("source.patch_bounds must contain increasing half-open bounds.")
    return bounds


def _bounds_payload(bounds: PatchBounds | None) -> dict[str, int] | None:
    if bounds is None:
        return None
    return {
        "x_start": bounds.x_start,
        "x_end": bounds.x_end,
        "y_start": bounds.y_start,
        "y_end": bounds.y_end,
        "z_start": bounds.z_start,
        "z_end": bounds.z_end,
    }


def _edge_payload(edge: GraphEdge | None) -> dict[str, int] | None:
    if edge is None:
        return None
    return {
        "start_node_id": edge.start_node_id,
        "end_node_id": edge.end_node_id,
    }


def _line_payload(
    orientation: Orientation | None,
    edge: GraphEdge | None,
    thickness: int,
) -> dict[str, object]:
    visible = orientation is not None and edge is not None
    return {
        "visible": visible,
        "orientation": orientation if visible else None,
        "edge": _edge_payload(edge) if visible else None,
        "thickness": thickness,
    }


def _require_object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object.")
    return value


def _require_list(
    value: object, label: str, *, length: int | None = None
) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array.")
    if length is not None and len(value) != length:
        raise ValueError(f"{label} must contain {length} values.")
    return value


def _require_bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be true or false.")
    return value


def _require_int(
    value: object,
    label: str,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer.")
    if minimum is not None and value < minimum:
        raise ValueError(f"{label} must be at least {minimum}.")
    if maximum is not None and value > maximum:
        raise ValueError(f"{label} must be at most {maximum}.")
    return value


def _optional_int(value: object, label: str) -> int | None:
    if value is None:
        return None
    return _require_int(value, label, minimum=1)


def _require_float(
    value: object,
    label: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
    exclusive_minimum: bool = False,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number.")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{label} must be finite.")
    if minimum is not None:
        invalid = normalized <= minimum if exclusive_minimum else normalized < minimum
        if invalid:
            relation = "greater than" if exclusive_minimum else "at least"
            raise ValueError(f"{label} must be {relation} {minimum}.")
    if maximum is not None and normalized > maximum:
        raise ValueError(f"{label} must be at most {maximum}.")
    return normalized


def _require_orientation(value: object, label: str) -> Orientation:
    if value not in ORIENTATIONS:
        raise ValueError(f"{label} must be axial, coronal, or sagittal.")
    return value  # type: ignore[return-value]
