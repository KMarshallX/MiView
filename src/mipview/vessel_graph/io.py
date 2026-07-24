from __future__ import annotations

import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET
from uuid import uuid4

import numpy as np
from nibabel.affines import apply_affine

from mipview.io.nifti_io import NiftiLoadResult
from mipview.vessel_graph.model import VesselGraphData, VesselGraphLayer


WORLD_COORDINATE_TOLERANCE = 1.0e-4
MAX_GRAPHML_BYTES = 512 * 1024 * 1024


def load_vessel_graphml(
    path: str | Path,
    source_volume: NiftiLoadResult,
) -> VesselGraphLayer:
    """Load the supported SkelHub GraphML profile against one source NIfTI."""

    graph_path = Path(path)
    if not graph_path.is_file():
        raise FileNotFoundError(f"GraphML file not found: {graph_path}")
    if graph_path.suffix.lower() != ".graphml":
        raise ValueError(f"Expected a .graphml file, got: {graph_path}")
    if graph_path.stat().st_size > MAX_GRAPHML_BYTES:
        raise ValueError(
            f"GraphML file exceeds the {MAX_GRAPHML_BYTES // (1024 * 1024)} MB limit."
        )
    with graph_path.open("rb") as stream:
        if b"<!DOCTYPE" in stream.read(4096).upper():
            raise ValueError("GraphML files containing a DOCTYPE are not supported.")

    original_shape, original_affine, original_to_loaded = _source_geometry(
        source_volume
    )
    (
        node_ids,
        node_voxels,
        node_world,
        node_radii,
        node_components,
        edge_refs,
        edge_centerlines,
        edge_components,
    ) = _parse_graphml(graph_path)

    node_index = {node_id: index for index, node_id in enumerate(node_ids)}
    edge_indices = np.empty((len(edge_refs), 2), dtype=np.int32)
    for index, (source_id, target_id) in enumerate(edge_refs):
        try:
            edge_indices[index] = (
                node_index[source_id],
                node_index[target_id],
            )
        except KeyError as exc:
            raise ValueError(
                f"GraphML edge references missing node '{exc.args[0]}'."
            ) from exc
        if source_id == target_id:
            raise ValueError(f"GraphML edge {index} is a self-edge.")

    offsets = np.zeros(len(edge_centerlines) + 1, dtype=np.int64)
    for index, centerline in enumerate(edge_centerlines):
        offsets[index + 1] = offsets[index] + centerline.shape[0]
    flattened_centerlines = (
        np.concatenate(edge_centerlines, axis=0).astype(np.float64, copy=False)
        if edge_centerlines
        else np.empty((0, 3), dtype=np.float64)
    )

    warnings = _spatial_warnings(
        node_voxels,
        node_world,
        flattened_centerlines,
        original_shape,
        original_affine,
    )
    data = VesselGraphData(
        node_ids=tuple(node_ids),
        node_source_voxels=np.asarray(node_voxels, dtype=np.float64),
        node_world_positions=np.asarray(node_world, dtype=np.float64),
        node_radii=np.asarray(node_radii, dtype=np.float32),
        node_components=np.asarray(node_components, dtype=np.int64),
        edge_node_indices=edge_indices,
        edge_centerline_source_voxels=flattened_centerlines,
        edge_centerline_offsets=offsets,
        edge_components=np.asarray(edge_components, dtype=np.int64),
        original_shape=original_shape,
        original_affine=original_affine,
        original_to_loaded_voxel_affine=original_to_loaded,
        loaded_shape=tuple(int(value) for value in source_volume.shape[:3]),
    )
    return VesselGraphLayer(
        id=f"graphml-{uuid4().hex}",
        path=graph_path.resolve(strict=False),
        data=data,
        warnings=tuple(warnings),
        projection_safe=not warnings,
    )


def _source_geometry(
    volume: NiftiLoadResult,
) -> tuple[tuple[int, int, int], np.ndarray, np.ndarray]:
    original_shape_values = volume.original_shape or volume.shape
    if len(original_shape_values) < 3:
        raise ValueError("GraphML source image must be three-dimensional.")
    original_shape = tuple(int(value) for value in original_shape_values[:3])
    original_affine = np.asarray(
        volume.original_affine
        if volume.original_affine is not None
        else volume.affine,
        dtype=np.float64,
    )
    original_to_loaded = np.asarray(
        volume.original_to_loaded_voxel_affine
        if volume.original_to_loaded_voxel_affine is not None
        else np.eye(4),
        dtype=np.float64,
    )
    if original_affine.shape != (4, 4) or original_to_loaded.shape != (4, 4):
        raise ValueError("GraphML source image affines must be 4x4.")
    return original_shape, original_affine, original_to_loaded


def _parse_graphml(
    path: Path,
) -> tuple[
    list[str],
    list[tuple[float, float, float]],
    list[tuple[float, float, float]],
    list[float],
    list[int],
    list[tuple[str, str]],
    list[np.ndarray],
    list[int],
]:
    key_names: dict[str, str] = {}
    node_ids: list[str] = []
    node_voxels: list[tuple[float, float, float]] = []
    node_world: list[tuple[float, float, float]] = []
    node_radii: list[float] = []
    node_components: list[int] = []
    edge_refs: list[tuple[str, str]] = []
    edge_centerlines: list[np.ndarray] = []
    edge_components: list[int] = []
    seen_nodes: set[str] = set()
    graph_default: str | None = None

    try:
        for event, element in ET.iterparse(path, events=("start", "end")):
            tag = _local_name(element.tag)
            if event == "start":
                if tag == "key":
                    key_id = element.attrib.get("id")
                    name = element.attrib.get("attr.name")
                    if key_id and name:
                        key_names[key_id] = name
                elif tag == "graph" and graph_default is None:
                    graph_default = element.attrib.get("edgedefault")
                continue

            if tag == "node":
                node_id = element.attrib.get("id")
                if not node_id:
                    raise ValueError("GraphML node is missing its id.")
                if node_id in seen_nodes:
                    raise ValueError(f"Duplicate GraphML node id '{node_id}'.")
                seen_nodes.add(node_id)
                values = _data_values(element, key_names)
                node_ids.append(node_id)
                node_voxels.append(
                    _json_point(values.get("voxel_pos"), f"node {node_id} voxel_pos")
                )
                node_world.append(
                    tuple(
                        _finite_float(values.get(axis), f"node {node_id} {axis}")
                        for axis in ("X", "Y", "Z")
                    )
                )
                node_radii.append(
                    math.nan
                    if values.get("r") is None
                    else _finite_float(values.get("r"), f"node {node_id} r")
                )
                node_components.append(
                    _optional_integral(values.get("component_index"))
                )
                element.clear()
            elif tag == "edge":
                source_id = element.attrib.get("source")
                target_id = element.attrib.get("target")
                if not source_id or not target_id:
                    raise ValueError("GraphML edge is missing source or target.")
                values = _data_values(element, key_names)
                centerline = _json_polyline(
                    values.get("centerline_voxels"),
                    f"edge {source_id}-{target_id} centerline_voxels",
                )
                declared_count = values.get("num_centerline_voxels")
                if declared_count is not None and _integral(
                    declared_count,
                    f"edge {source_id}-{target_id} num_centerline_voxels",
                ) != centerline.shape[0]:
                    raise ValueError(
                        f"GraphML edge {source_id}-{target_id} centerline count "
                        "does not match its payload."
                    )
                edge_refs.append((source_id, target_id))
                edge_centerlines.append(centerline)
                edge_components.append(
                    _optional_integral(values.get("component_index"))
                )
                element.clear()
    except ET.ParseError as exc:
        raise ValueError(f"Invalid GraphML XML: {exc}") from exc

    if graph_default not in {None, "undirected"}:
        raise ValueError("Only undirected vessel GraphML files are supported.")
    if not node_ids:
        raise ValueError("GraphML file contains no nodes.")
    return (
        node_ids,
        node_voxels,
        node_world,
        node_radii,
        node_components,
        edge_refs,
        edge_centerlines,
        edge_components,
    )


def _data_values(element: ET.Element, key_names: dict[str, str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for child in element:
        if _local_name(child.tag) != "data":
            continue
        key_id = child.attrib.get("key")
        name = key_names.get(key_id or "")
        if name is not None:
            values[name] = "" if child.text is None else child.text.strip()
    return values


def _json_point(value: str | None, name: str) -> tuple[float, float, float]:
    array = _json_array(value, name)
    if array.shape != (3,):
        raise ValueError(f"GraphML {name} must contain three coordinates.")
    return tuple(float(item) for item in array)


def _json_polyline(value: str | None, name: str) -> np.ndarray:
    array = _json_array(value, name)
    if array.ndim != 2 or array.shape[1] != 3 or array.shape[0] == 0:
        raise ValueError(f"GraphML {name} must be a non-empty Nx3 array.")
    return array


def _json_array(value: str | None, name: str) -> np.ndarray:
    if value is None:
        raise ValueError(f"GraphML is missing required {name}.")
    try:
        parsed = json.loads(value)
        array = np.asarray(parsed, dtype=np.float64)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ValueError(f"GraphML {name} is not a numeric JSON array.") from exc
    if not np.all(np.isfinite(array)):
        raise ValueError(f"GraphML {name} contains non-finite coordinates.")
    return array


def _finite_float(value: str | None, name: str) -> float:
    if value is None:
        raise ValueError(f"GraphML is missing required {name}.")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"GraphML {name} must be numeric.") from exc
    if not math.isfinite(result):
        raise ValueError(f"GraphML {name} must be finite.")
    return result


def _optional_integral(value: str | None) -> int:
    return -1 if value is None else _integral(value, "component_index")


def _integral(value: str, name: str) -> int:
    numeric = _finite_float(value, name)
    rounded = int(round(numeric))
    if not math.isclose(numeric, rounded, abs_tol=1.0e-9):
        raise ValueError(f"GraphML {name} must be an integer value.")
    return rounded


def _spatial_warnings(
    node_voxels: np.ndarray,
    node_world: np.ndarray,
    centerlines: np.ndarray,
    shape: tuple[int, int, int],
    affine: np.ndarray,
) -> list[str]:
    warnings: list[str] = []
    shape_array = np.asarray(shape, dtype=np.float64)
    node_array = np.asarray(node_voxels, dtype=np.float64)
    world_array = np.asarray(node_world, dtype=np.float64)
    if np.any(node_array < -0.5) or np.any(node_array > shape_array - 0.5):
        warnings.append(
            "Some GraphML node voxel positions fall outside the source image cells."
        )
    if centerlines.size and (
        np.any(centerlines < 0.0)
        or np.any(centerlines > shape_array - 1.0)
    ):
        warnings.append(
            "Some GraphML centerline voxels fall outside the source image dimensions."
        )
    expected_world = np.asarray(apply_affine(affine, node_array), dtype=np.float64)
    maximum_error = float(np.max(np.linalg.norm(expected_world - world_array, axis=1)))
    if maximum_error > WORLD_COORDINATE_TOLERANCE:
        warnings.append(
            "GraphML X/Y/Z coordinates disagree with the loaded source NIfTI "
            f"affine (maximum error {maximum_error:.6g})."
        )
    return warnings


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
