from __future__ import annotations

import argparse
import json
import socket
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from mipview.control.ipc_server import default_socket_path


class _HelpFormatter(
    argparse.ArgumentDefaultsHelpFormatter,
    argparse.RawDescriptionHelpFormatter,
):
    """Keep examples readable while still showing defaults."""


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        command, command_args, postprocess = _command_from_args(args)
    except ValueError as exc:
        parser.error(str(exc))

    response = _send_command(
        command,
        command_args,
        socket_path=Path(args.socket),
    )
    if postprocess is not None and response.get("ok") is True:
        postprocess(response)
    if response.get("ok") is True:
        _print_response_warnings(response)

    print(json.dumps(response))
    return 0 if response.get("ok") is True else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mipview-ctl",
        description=(
            "Control an already-running MipView GUI through its local IPC socket. "
            "Commands return structured JSON on stdout."
        ),
        epilog=(
            "Typical workflow:\n"
            "  mipview-ctl status\n"
            "  mipview-ctl patch size 64 64 10\n"
            "  mipview-ctl patch center 120 80 45\n"
            "  mipview-ctl patch export-raw ./patch_raw.npz\n"
            "  mipview-ctl projection mode minip\n"
            "  mipview-ctl projection save axial ./patch_axial.png --annotation-preview\n"
            "  mipview-ctl annotation save ./annotation_mask.nii.gz\n\n"
            "Use 'mipview-ctl GROUP --help' or 'mipview-ctl GROUP COMMAND --help' "
            "for command details."
        ),
        formatter_class=_HelpFormatter,
    )
    parser.add_argument(
        "--socket",
        metavar="SOCKET",
        default=str(default_socket_path()),
        help="Path to the running MipView IPC Unix socket.",
    )
    subparsers = parser.add_subparsers(
        dest="group",
        required=True,
        metavar="COMMAND_GROUP",
    )

    subparsers.add_parser(
        "status",
        help="Show loaded image, cursor, patch, annotation, and segmentation state.",
        description="Show a concise JSON summary of the running MipView session.",
        formatter_class=_HelpFormatter,
    )

    send_parser = subparsers.add_parser(
        "send",
        help="Advanced: send a raw command name with JSON arguments.",
        description=(
            "Advanced direct IPC command dispatch. Use this for commands that do "
            "not have a dedicated CLI wrapper."
        ),
        formatter_class=_HelpFormatter,
    )
    send_parser.add_argument(
        "command",
        metavar="COMMAND",
        help="Registered command name, e.g. cursor.move.",
    )
    send_parser.add_argument(
        "--args-json",
        metavar="JSON",
        default="{}",
        help="JSON object containing command arguments.",
    )

    viewer_parser = subparsers.add_parser(
        "viewer",
        help="Save screenshots or structured viewer state.",
        description="Viewer export commands for screenshots and machine-readable state.",
        formatter_class=_HelpFormatter,
    )
    viewer_subparsers = viewer_parser.add_subparsers(dest="viewer_command", required=True)
    viewer_screenshot = viewer_subparsers.add_parser(
        "screenshot",
        help="Save a full-window screenshot.",
        description="Save a full-window screenshot and return viewer state metadata.",
        formatter_class=_HelpFormatter,
    )
    viewer_screenshot.add_argument("path", metavar="PATH", help="Output image path.")
    viewer_state = viewer_subparsers.add_parser(
        "state",
        help="Write structured viewer state JSON.",
        description="Write the returned viewer state data object to a JSON file.",
        formatter_class=_HelpFormatter,
    )
    viewer_state.add_argument("path", metavar="PATH", help="Output JSON path.")

    cursor_parser = subparsers.add_parser(
        "cursor",
        help="Move the cursor by voxel coordinates.",
        description="Cursor commands use source voxel coordinates as X Y Z integers.",
        formatter_class=_HelpFormatter,
    )
    cursor_subparsers = cursor_parser.add_subparsers(dest="cursor_command", required=True)
    cursor_move = cursor_subparsers.add_parser(
        "move",
        help="Move cursor to an in-bounds voxel.",
        description="Move the cursor to an in-bounds source voxel coordinate.",
        formatter_class=_HelpFormatter,
    )
    cursor_move.add_argument("x", metavar="X", type=int, help="X voxel coordinate.")
    cursor_move.add_argument("y", metavar="Y", type=int, help="Y voxel coordinate.")
    cursor_move.add_argument("z", metavar="Z", type=int, help="Z voxel coordinate.")

    patch_parser = subparsers.add_parser(
        "patch",
        help="Select, save, and export current image patches.",
        description=(
            "Patch commands operate on the fixed-size patch centered at the current "
            "patch center or cursor."
        ),
        formatter_class=_HelpFormatter,
    )
    patch_subparsers = patch_parser.add_subparsers(dest="patch_command", required=True)
    patch_size = patch_subparsers.add_parser(
        "size",
        help="Set patch size in voxels.",
        description="Set the fixed patch size in voxel units; all values must be positive.",
        formatter_class=_HelpFormatter,
    )
    patch_size.add_argument("sx", metavar="SX", type=int, help="Patch size along X.")
    patch_size.add_argument("sy", metavar="SY", type=int, help="Patch size along Y.")
    patch_size.add_argument("sz", metavar="SZ", type=int, help="Patch size along Z.")
    patch_center = patch_subparsers.add_parser(
        "center",
        help="Set patch center voxel.",
        description="Set the patch center to an in-bounds source voxel coordinate.",
        formatter_class=_HelpFormatter,
    )
    patch_center.add_argument("x", metavar="X", type=int, help="X voxel coordinate.")
    patch_center.add_argument("y", metavar="Y", type=int, help="Y voxel coordinate.")
    patch_center.add_argument("z", metavar="Z", type=int, help="Z voxel coordinate.")
    patch_subparsers.add_parser(
        "select",
        help="Extract and store the current patch.",
        description="Extract and store the current patch using current patch bounds.",
        formatter_class=_HelpFormatter,
    )
    patch_export_raw = patch_subparsers.add_parser(
        "export-raw",
        help="Export patch arrays and metadata to .npz.",
        description=(
            "Export a compressed .npz with image_patch, bounds, patch_size, "
            "patch_center, affine, voxel_spacing, source_image_path, and "
            "viewer_state_json. Includes annotation_patch when an active annotation "
            "exists and segmentation_patch when the active segmentation is file-backed."
        ),
        formatter_class=_HelpFormatter,
    )
    patch_export_raw.add_argument("path", metavar="PATH", help="Output .npz path.")
    patch_save = patch_subparsers.add_parser(
        "save",
        help="Save selected image patch as NIfTI.",
        description="Save the selected image patch as .nii or .nii.gz.",
        formatter_class=_HelpFormatter,
    )
    patch_save.add_argument("path", metavar="PATH", help="Output NIfTI path.")

    projection_parser = subparsers.add_parser(
        "projection",
        help="Set MIP/MinIP mode and save patch projections.",
        description="Projection commands operate on the selected patch.",
        formatter_class=_HelpFormatter,
    )
    projection_subparsers = projection_parser.add_subparsers(
        dest="projection_command",
        required=True,
    )
    projection_mode = projection_subparsers.add_parser(
        "mode",
        help="Set image projection mode.",
        description="Set image projection mode for later projection saves.",
        formatter_class=_HelpFormatter,
    )
    projection_mode.add_argument(
        "mode",
        metavar="MODE",
        help="Image projection mode: mip or minip.",
    )
    projection_save = projection_subparsers.add_parser(
        "save",
        help="Save one patch projection image.",
        description=(
            "Save one grayscale patch projection for VIEW. The image projection "
            "uses the current mode. With --annotation-preview, overlay the active "
            "annotation MIP; annotation projection is always MIP."
        ),
        formatter_class=_HelpFormatter,
    )
    projection_save.add_argument(
        "view",
        metavar="VIEW",
        help="Projection view: axial, coronal, or sagittal.",
    )
    projection_save.add_argument(
        "path",
        metavar="PATH",
        help="Output .png, .jpg, or .jpeg path.",
    )
    projection_save.add_argument(
        "--annotation-preview",
        action="store_true",
        help="Overlay active annotation MIP onto the image projection.",
    )

    graph_parser = subparsers.add_parser(
        "graph",
        help="Inspect and edit projection graphs in open patch windows.",
        description=(
            "Graph commands use an open patch window session ID. Projection nodes "
            "resolve depth from the current MIP/MinIP; voxel nodes use patch-local "
            "source-array coordinates."
        ),
        formatter_class=_HelpFormatter,
    )
    graph_subparsers = graph_parser.add_subparsers(
        dest="graph_command",
        required=True,
    )
    graph_status = graph_subparsers.add_parser("status", help="Show graph session state.")
    graph_status.add_argument("session_id", metavar="SESSION_ID")
    graph_activate = graph_subparsers.add_parser("activate", help="Activate Graph mode.")
    graph_activate.add_argument("session_id", metavar="SESSION_ID")
    graph_exit = graph_subparsers.add_parser("exit", help="Exit Graph mode.")
    graph_exit.add_argument("session_id", metavar="SESSION_ID")
    graph_display = graph_subparsers.add_parser(
        "display",
        help="Update graph visibility and rendering options.",
    )
    graph_display.add_argument("session_id", metavar="SESSION_ID")
    graph_display.add_argument(
        "--visible",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Show or hide graph overlays.",
    )
    graph_display.add_argument("--opacity", type=float, default=None)
    graph_display.add_argument("--node-size", type=int, default=None)
    graph_display.add_argument("--edge-thickness", type=int, default=None)

    graph_add_node = graph_subparsers.add_parser("add-node", help="Create a graph node.")
    graph_add_node.add_argument("session_id", metavar="SESSION_ID")
    graph_add_node.add_argument("view", metavar="VIEW")
    graph_add_node.add_argument("horizontal", metavar="HORIZONTAL", type=int)
    graph_add_node.add_argument("vertical", metavar="VERTICAL", type=int)
    graph_add_voxel_node = graph_subparsers.add_parser(
        "add-voxel-node",
        help="Create a node at an explicit patch-local source voxel.",
    )
    graph_add_voxel_node.add_argument("session_id", metavar="SESSION_ID")
    graph_add_voxel_node.add_argument("x", metavar="X", type=int)
    graph_add_voxel_node.add_argument("y", metavar="Y", type=int)
    graph_add_voxel_node.add_argument("z", metavar="Z", type=int)
    graph_delete_node = graph_subparsers.add_parser(
        "delete-node", help="Delete a graph node and its connected edges."
    )
    graph_delete_node.add_argument("session_id", metavar="SESSION_ID")
    graph_delete_node.add_argument("view", metavar="VIEW")
    graph_delete_node.add_argument("node_id", metavar="NODE_ID", type=int)

    graph_add_edge = graph_subparsers.add_parser("add-edge", help="Create a graph edge.")
    graph_add_edge.add_argument("session_id", metavar="SESSION_ID")
    graph_add_edge.add_argument("view", metavar="VIEW")
    graph_add_edge.add_argument("start_node_id", metavar="START_NODE_ID", type=int)
    graph_add_edge.add_argument("end_node_id", metavar="END_NODE_ID", type=int)
    graph_delete_edge = graph_subparsers.add_parser(
        "delete-edge", help="Delete a graph edge."
    )
    graph_delete_edge.add_argument("session_id", metavar="SESSION_ID")
    graph_delete_edge.add_argument("view", metavar="VIEW")
    graph_delete_edge.add_argument("start_node_id", metavar="START_NODE_ID", type=int)
    graph_delete_edge.add_argument("end_node_id", metavar="END_NODE_ID", type=int)

    graph_curve_edge = graph_subparsers.add_parser(
        "curve-edge", help="Set a quadratic control point for an existing edge."
    )
    graph_curve_edge.add_argument("session_id", metavar="SESSION_ID")
    graph_curve_edge.add_argument("view", metavar="VIEW")
    graph_curve_edge.add_argument("start_node_id", metavar="START_NODE_ID", type=int)
    graph_curve_edge.add_argument("end_node_id", metavar="END_NODE_ID", type=int)
    graph_curve_edge.add_argument("control_horizontal", metavar="CONTROL_H", type=float)
    graph_curve_edge.add_argument("control_vertical", metavar="CONTROL_V", type=float)
    graph_straighten_edge = graph_subparsers.add_parser(
        "straighten-edge", help="Remove the control point from an existing edge."
    )
    graph_straighten_edge.add_argument("session_id", metavar="SESSION_ID")
    graph_straighten_edge.add_argument("view", metavar="VIEW")
    graph_straighten_edge.add_argument("start_node_id", metavar="START_NODE_ID", type=int)
    graph_straighten_edge.add_argument("end_node_id", metavar="END_NODE_ID", type=int)
    graph_split_edge = graph_subparsers.add_parser(
        "split-edge", help="Create a node on an edge and replace it with two edges."
    )
    graph_split_edge.add_argument("session_id", metavar="SESSION_ID")
    graph_split_edge.add_argument("view", metavar="VIEW")
    graph_split_edge.add_argument("start_node_id", metavar="START_NODE_ID", type=int)
    graph_split_edge.add_argument("end_node_id", metavar="END_NODE_ID", type=int)
    graph_split_edge.add_argument("horizontal", metavar="HORIZONTAL", type=int)
    graph_split_edge.add_argument("vertical", metavar="VERTICAL", type=int)
    graph_calculate_angle = graph_subparsers.add_parser(
        "calculate-angle", help="Calculate an angle from four ordered graph node IDs."
    )
    graph_calculate_angle.add_argument("session_id", metavar="SESSION_ID")
    graph_calculate_angle.add_argument("view", metavar="VIEW")
    graph_calculate_angle.add_argument("vector_1_source", metavar="V1_SOURCE", type=int)
    graph_calculate_angle.add_argument("vector_1_target", metavar="V1_TARGET", type=int)
    graph_calculate_angle.add_argument("vector_2_source", metavar="V2_SOURCE", type=int)
    graph_calculate_angle.add_argument("vector_2_target", metavar="V2_TARGET", type=int)
    graph_clear_angle = graph_subparsers.add_parser(
        "clear-angle", help="Clear the stored graph angle measurement."
    )
    graph_clear_angle.add_argument("session_id", metavar="SESSION_ID")

    annotation_parser = subparsers.add_parser(
        "annotation",
        help="Create, edit, and save voxel-space annotations.",
        description=(
            "Annotation commands modify the active voxel-space annotation mask. "
            "Stroke points are voxel coordinates, not screen pixels."
        ),
        formatter_class=_HelpFormatter,
    )
    annotation_subparsers = annotation_parser.add_subparsers(
        dest="annotation_command",
        required=True,
    )
    annotation_create = annotation_subparsers.add_parser(
        "create",
        help="Create or enable active annotation mask.",
        description="Create or enable the active annotation mask and set the active label.",
        formatter_class=_HelpFormatter,
    )
    annotation_create.add_argument(
        "--label",
        metavar="LABEL",
        type=int,
        default=1,
        help="Active label to paint.",
    )
    annotation_paint = annotation_subparsers.add_parser(
        "paint-stroke",
        help="Paint a voxel-space stroke.",
        description=(
            "Paint a stroke into the active annotation mask. --points is a JSON "
            "file containing voxel-space points like [[x,y,z], [x,y,z]]."
        ),
        formatter_class=_HelpFormatter,
    )
    annotation_paint.add_argument(
        "--label",
        metavar="LABEL",
        type=int,
        required=True,
        help="Positive label value to paint.",
    )
    annotation_paint.add_argument(
        "--radius",
        metavar="RADIUS",
        type=int,
        required=True,
        help="Brush radius in voxels.",
    )
    annotation_paint.add_argument(
        "--view",
        metavar="VIEW",
        required=True,
        help="Stroke disk plane: axial, coronal, or sagittal.",
    )
    annotation_paint.add_argument(
        "--points",
        metavar="POINTS_JSON",
        required=True,
        help="Path to JSON file of voxel-space stroke points.",
    )
    annotation_erase = annotation_subparsers.add_parser(
        "erase-stroke",
        help="Erase a voxel-space stroke.",
        description=(
            "Erase a stroke from the active annotation mask. --points is a JSON "
            "file containing voxel-space points like [[x,y,z], [x,y,z]]."
        ),
        formatter_class=_HelpFormatter,
    )
    annotation_erase.add_argument(
        "--radius",
        metavar="RADIUS",
        type=int,
        required=True,
        help="Brush radius in voxels.",
    )
    annotation_erase.add_argument(
        "--view",
        metavar="VIEW",
        required=True,
        help="Stroke disk plane: axial, coronal, or sagittal.",
    )
    annotation_erase.add_argument(
        "--points",
        metavar="POINTS_JSON",
        required=True,
        help="Path to JSON file of voxel-space stroke points.",
    )
    annotation_save = annotation_subparsers.add_parser(
        "save",
        help="Save active annotation mask as NIfTI.",
        description="Save the active full-volume annotation mask as .nii or .nii.gz.",
        formatter_class=_HelpFormatter,
    )
    annotation_save.add_argument("path", metavar="PATH", help="Output NIfTI path.")

    return parser


def _command_from_args(args: argparse.Namespace) -> tuple[str, dict[str, Any], Any]:
    if args.group == "status":
        return "viewer.status", {}, None

    if args.group == "send":
        return args.command, _parse_args_json(args.args_json), None

    if args.group == "viewer":
        if args.viewer_command == "screenshot":
            return "viewer.screenshot", {"path": args.path}, None
        if args.viewer_command == "state":
            output_path = Path(args.path)
            return "viewer.export_state", {}, lambda response: _write_response_data(
                output_path,
                response,
            )

    if args.group == "cursor" and args.cursor_command == "move":
        return "cursor.move", {"x": args.x, "y": args.y, "z": args.z}, None

    if args.group == "patch":
        if args.patch_command == "size":
            return "patch.size", {"sx": args.sx, "sy": args.sy, "sz": args.sz}, None
        if args.patch_command == "center":
            return "patch.center", {"x": args.x, "y": args.y, "z": args.z}, None
        if args.patch_command == "select":
            return "patch.select", {}, None
        if args.patch_command == "export-raw":
            return "patch.export_raw", {"path": args.path}, None
        if args.patch_command == "save":
            return "patch.save", {"path": args.path}, None

    if args.group == "projection":
        if args.projection_command == "mode":
            return "projection.mode", {"mode": args.mode}, None
        if args.projection_command == "save":
            return (
                "projection.save",
                {
                    "view": args.view,
                    "path": args.path,
                    "annotation_preview": bool(args.annotation_preview),
                },
                None,
            )

    if args.group == "graph":
        if args.graph_command == "status":
            return "graph.status", {"session_id": args.session_id}, None
        if args.graph_command in {"activate", "exit"}:
            return (
                "graph.activate",
                {
                    "session_id": args.session_id,
                    "enabled": args.graph_command == "activate",
                },
                None,
            )
        if args.graph_command == "display":
            return (
                "graph.set_display",
                {
                    "session_id": args.session_id,
                    "visible": args.visible,
                    "opacity": args.opacity,
                    "node_size": args.node_size,
                    "edge_thickness": args.edge_thickness,
                },
                None,
            )
        if args.graph_command == "add-node":
            return (
                "graph.add_node",
                {
                    "session_id": args.session_id,
                    "view": args.view,
                    "horizontal": args.horizontal,
                    "vertical": args.vertical,
                },
                None,
            )
        if args.graph_command == "add-voxel-node":
            return (
                "graph.add_voxel_node",
                {
                    "session_id": args.session_id,
                    "x": args.x,
                    "y": args.y,
                    "z": args.z,
                },
                None,
            )
        if args.graph_command == "delete-node":
            return (
                "graph.delete_node",
                {
                    "session_id": args.session_id,
                    "view": args.view,
                    "node_id": args.node_id,
                },
                None,
            )
        if args.graph_command in {"add-edge", "delete-edge"}:
            return (
                (
                    "graph.add_edge"
                    if args.graph_command == "add-edge"
                    else "graph.delete_edge"
                ),
                {
                    "session_id": args.session_id,
                    "view": args.view,
                    "start_node_id": args.start_node_id,
                    "end_node_id": args.end_node_id,
                },
                None,
            )
        if args.graph_command in {"curve-edge", "straighten-edge"}:
            arguments = {
                "session_id": args.session_id,
                "view": args.view,
                "start_node_id": args.start_node_id,
                "end_node_id": args.end_node_id,
            }
            if args.graph_command == "curve-edge":
                arguments.update(
                    {
                        "control_horizontal": args.control_horizontal,
                        "control_vertical": args.control_vertical,
                    }
                )
            return (
                (
                    "graph.curve_edge"
                    if args.graph_command == "curve-edge"
                    else "graph.straighten_edge"
                ),
                arguments,
                None,
            )
        if args.graph_command == "split-edge":
            return (
                "graph.split_edge",
                {
                    "session_id": args.session_id,
                    "view": args.view,
                    "start_node_id": args.start_node_id,
                    "end_node_id": args.end_node_id,
                    "horizontal": args.horizontal,
                    "vertical": args.vertical,
                },
                None,
            )
        if args.graph_command == "calculate-angle":
            return (
                "graph.calculate_angle",
                {
                    "session_id": args.session_id,
                    "view": args.view,
                    "vector_1_source": args.vector_1_source,
                    "vector_1_target": args.vector_1_target,
                    "vector_2_source": args.vector_2_source,
                    "vector_2_target": args.vector_2_target,
                },
                None,
            )
        if args.graph_command == "clear-angle":
            return "graph.clear_angle", {"session_id": args.session_id}, None

    if args.group == "annotation":
        if args.annotation_command == "create":
            return "annotation.create", {"label": args.label}, None
        if args.annotation_command == "paint-stroke":
            return (
                "annotation.paint_stroke",
                {
                    "label": args.label,
                    "radius": args.radius,
                    "view": args.view,
                    "points": _load_points(args.points),
                },
                None,
            )
        if args.annotation_command == "erase-stroke":
            return (
                "annotation.erase_stroke",
                {
                    "radius": args.radius,
                    "view": args.view,
                    "points": _load_points(args.points),
                },
                None,
            )
        if args.annotation_command == "save":
            return "annotation.save", {"path": args.path}, None

    raise ValueError("Unsupported command.")


def _send_command(
    command: str,
    args: dict[str, Any],
    *,
    socket_path: Path,
) -> dict[str, Any]:
    request = {
        "id": f"cli-{uuid4().hex}",
        "command": command,
        "args": args,
    }
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client_socket:
            client_socket.connect(str(socket_path))
            client_socket.sendall(json.dumps(request).encode("utf-8") + b"\n")
            client_file = client_socket.makefile("rb")
            try:
                response_line = client_file.readline()
            finally:
                client_file.close()
    except OSError as exc:
        return {
            "id": None,
            "ok": False,
            "message": f"Unable to connect to MipView IPC server: {exc}",
            "data": {},
        }

    if not response_line:
        return {
            "id": request["id"],
            "ok": False,
            "message": "MipView IPC server closed the connection without a response.",
            "data": {},
        }

    try:
        response = json.loads(response_line)
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        return {
            "id": request["id"],
            "ok": False,
            "message": f"Invalid JSON response from MipView IPC server: {exc}",
            "data": {},
        }
    if not isinstance(response, dict):
        return {
            "id": request["id"],
            "ok": False,
            "message": "MipView IPC server response was not a JSON object.",
            "data": {},
        }
    return response


def _parse_args_json(args_json: str) -> dict[str, Any]:
    try:
        parsed = json.loads(args_json)
    except ValueError as exc:
        raise ValueError(f"--args-json must be valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("--args-json must be a JSON object.")
    return parsed


def _load_points(path: str) -> list[list[int]]:
    point_path = Path(path)
    try:
        points = json.loads(point_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"Unable to read points file {point_path}: {exc}") from exc
    except ValueError as exc:
        raise ValueError(f"Points file must contain JSON: {exc}") from exc
    if not isinstance(points, list):
        raise ValueError("Points file must contain a JSON array.")
    return points


def _write_response_data(path: Path, response: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(response.get("data", {}), indent=2),
        encoding="utf-8",
    )


def _print_response_warnings(response: dict[str, Any]) -> None:
    data = response.get("data")
    if not isinstance(data, dict):
        return
    warnings = data.get("warnings")
    if not isinstance(warnings, list):
        return
    for warning in warnings:
        print(f"Warning: {warning}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
