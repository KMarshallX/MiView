from __future__ import annotations

from collections.abc import Callable

import numpy as np
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QInputDialog, QMenu, QMessageBox, QWidget

from miview.tools import (
    ToolDefinition,
    ToolParameter,
    all_tools,
    default_parameters_for_data,
    get_tool,
)


def build_tools_submenu(
    parent: QWidget,
    tools_menu: QMenu,
    on_tool_selected: Callable[[str], None],
) -> QMenu:
    utilities_menu = tools_menu.addMenu("&Utilities")
    for tool in all_tools():
        action = QAction(tool.label, parent)
        action.setStatusTip(tool.description)
        action.triggered.connect(
            lambda _checked=False, tool_id=tool.id: on_tool_selected(tool_id)
        )
        utilities_menu.addAction(action)
    return utilities_menu


def resolve_tool_parameters(
    parent: QWidget,
    tool_id: str,
    data: np.ndarray,
) -> dict[str, int | float] | None:
    tool = get_tool(tool_id)
    defaults = default_parameters_for_data(tool, data)

    resolved = dict(defaults)
    for parameter in tool.parameters:
        if not parameter.prompt:
            continue
        value = _prompt_parameter(parent, tool, parameter, resolved[parameter.key])
        if value is None:
            return None
        resolved[parameter.key] = value
    return resolved


def _prompt_parameter(
    parent: QWidget,
    tool: ToolDefinition,
    parameter: ToolParameter,
    initial: int | float,
) -> int | float | None:
    while True:
        if parameter.type == "int":
            value, ok = QInputDialog.getInt(
                parent,
                f"{tool.label} Parameter",
                parameter.label,
                int(initial),
                int(parameter.minimum) if parameter.minimum is not None else -2_147_483_647,
                int(parameter.maximum) if parameter.maximum is not None else 2_147_483_647,
                1,
            )
            if not ok:
                return None
            if parameter.require_odd and value % 2 == 0:
                QMessageBox.warning(
                    parent,
                    "Invalid Parameter",
                    f"{parameter.label} must be an odd integer.",
                )
                initial = value
                continue
            return int(value)

        value, ok = QInputDialog.getDouble(
            parent,
            f"{tool.label} Parameter",
            parameter.label,
            float(initial),
            float(parameter.minimum) if parameter.minimum is not None else -1e12,
            float(parameter.maximum) if parameter.maximum is not None else 1e12,
            parameter.decimals,
        )
        if not ok:
            return None
        return float(value)
