from __future__ import annotations

import argparse
import json
import socket
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from mipview.control.ipc_server import default_socket_path


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

    print(json.dumps(response))
    return 0 if response.get("ok") is True else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mipview-ctl")
    parser.add_argument(
        "--socket",
        default=str(default_socket_path()),
        help="Path to the MipView Unix domain socket.",
    )
    subparsers = parser.add_subparsers(dest="group", required=True)

    subparsers.add_parser("status")

    send_parser = subparsers.add_parser("send")
    send_parser.add_argument("command")
    send_parser.add_argument("--args-json", default="{}")

    viewer_parser = subparsers.add_parser("viewer")
    viewer_subparsers = viewer_parser.add_subparsers(dest="viewer_command", required=True)
    viewer_screenshot = viewer_subparsers.add_parser("screenshot")
    viewer_screenshot.add_argument("path")
    viewer_state = viewer_subparsers.add_parser("state")
    viewer_state.add_argument("path")

    cursor_parser = subparsers.add_parser("cursor")
    cursor_subparsers = cursor_parser.add_subparsers(dest="cursor_command", required=True)
    cursor_move = cursor_subparsers.add_parser("move")
    cursor_move.add_argument("x", type=int)
    cursor_move.add_argument("y", type=int)
    cursor_move.add_argument("z", type=int)

    patch_parser = subparsers.add_parser("patch")
    patch_subparsers = patch_parser.add_subparsers(dest="patch_command", required=True)
    patch_size = patch_subparsers.add_parser("size")
    patch_size.add_argument("sx", type=int)
    patch_size.add_argument("sy", type=int)
    patch_size.add_argument("sz", type=int)
    patch_center = patch_subparsers.add_parser("center")
    patch_center.add_argument("x", type=int)
    patch_center.add_argument("y", type=int)
    patch_center.add_argument("z", type=int)
    patch_subparsers.add_parser("select")
    patch_export_raw = patch_subparsers.add_parser("export-raw")
    patch_export_raw.add_argument("path")
    patch_save = patch_subparsers.add_parser("save")
    patch_save.add_argument("path")

    projection_parser = subparsers.add_parser("projection")
    projection_subparsers = projection_parser.add_subparsers(
        dest="projection_command",
        required=True,
    )
    projection_mode = projection_subparsers.add_parser("mode")
    projection_mode.add_argument("mode")
    projection_save = projection_subparsers.add_parser("save")
    projection_save.add_argument("view")
    projection_save.add_argument("path")

    annotation_parser = subparsers.add_parser("annotation")
    annotation_subparsers = annotation_parser.add_subparsers(
        dest="annotation_command",
        required=True,
    )
    annotation_create = annotation_subparsers.add_parser("create")
    annotation_create.add_argument("--label", type=int, default=1)
    annotation_paint = annotation_subparsers.add_parser("paint-stroke")
    annotation_paint.add_argument("--label", type=int, required=True)
    annotation_paint.add_argument("--radius", type=int, required=True)
    annotation_paint.add_argument("--view", required=True)
    annotation_paint.add_argument("--points", required=True)
    annotation_erase = annotation_subparsers.add_parser("erase-stroke")
    annotation_erase.add_argument("--radius", type=int, required=True)
    annotation_erase.add_argument("--view", required=True)
    annotation_erase.add_argument("--points", required=True)
    annotation_save = annotation_subparsers.add_parser("save")
    annotation_save.add_argument("path")

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
            return "projection.save", {"view": args.view, "path": args.path}, None

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


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
