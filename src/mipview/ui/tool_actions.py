from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtWidgets import QMessageBox, QWidget

from mipview.nifti_io import NiftiLoadResult
from mipview.tools import ParameterValue, apply_tool, derive_volume
from mipview.ui.tools_menu import resolve_tool_parameters


@dataclass(frozen=True)
class ToolApplicationResult:
    transformed_volume: NiftiLoadResult
    parameters: dict[str, ParameterValue]


def apply_tool_to_volume(
    parent: QWidget,
    tool_id: str,
    volume: NiftiLoadResult,
) -> tuple[NiftiLoadResult | None, str]:
    """Prompt for tool parameters and apply the tool to a volume."""
    result, status = apply_tool_to_volume_with_metadata(parent, tool_id, volume)
    if result is None:
        return None, status
    return result.transformed_volume, status


def apply_tool_to_volume_with_metadata(
    parent: QWidget,
    tool_id: str,
    volume: NiftiLoadResult,
) -> tuple[ToolApplicationResult | None, str]:
    """Prompt for tool parameters and apply a tool, returning resolved parameters."""
    parameters = resolve_tool_parameters(parent, tool_id, volume.data)
    if parameters is None:
        return None, "Tool application canceled"

    try:
        transformed_data = apply_tool(tool_id, volume.data, parameters)
        transformed_volume = derive_volume(volume, transformed_data)
    except ValueError as exc:
        QMessageBox.critical(parent, "Tool Application Failed", str(exc))
        return None, "Tool application failed"

    return ToolApplicationResult(
        transformed_volume=transformed_volume,
        parameters=parameters,
    ), ""
