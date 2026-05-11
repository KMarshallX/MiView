from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from mipview.control.command_registry import CommandRegistry
from mipview.control.result import CommandResult


@dataclass(frozen=True)
class IpcRequest:
    id: str
    command: str
    args: dict[str, Any]


def parse_request_json(payload: str | bytes) -> IpcRequest:
    try:
        request = json.loads(payload)
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise ValueError(f"Invalid JSON request: {exc}") from exc

    if not isinstance(request, dict):
        raise ValueError("IPC request must be a JSON object.")

    request_id = request.get("id")
    if not isinstance(request_id, str):
        raise ValueError("IPC request id must be a string.")

    command = request.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ValueError("IPC request command must be a non-empty string.")

    args = request.get("args", {})
    if not isinstance(args, dict):
        raise ValueError("IPC request args must be a JSON object.")

    return IpcRequest(
        id=request_id,
        command=command,
        args=args,
    )


def response_json(request_id: str | None, result: CommandResult) -> str:
    response = {
        "id": request_id,
        **result.to_dict(),
    }
    try:
        return json.dumps(response)
    except (TypeError, ValueError) as exc:
        fallback = {
            "id": request_id,
            "ok": False,
            "message": f"Response serialization failed: {exc}",
            "data": {},
        }
        return json.dumps(fallback)


def handle_json_request(registry: CommandRegistry, payload: str | bytes) -> str:
    try:
        request = parse_request_json(payload)
    except ValueError as exc:
        return response_json(None, CommandResult(False, str(exc)))

    result = registry.execute(request.command, request.args)
    return response_json(request.id, result)
