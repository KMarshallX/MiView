from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QWidget

from miview.nifti_io import NiftiLoadResult
from miview.tools import apply_tool, derive_volume
from miview.ui.tools_menu import resolve_tool_parameters


def apply_tool_to_volume(
    parent: QWidget,
    tool_id: str,
    volume: NiftiLoadResult,
) -> tuple[NiftiLoadResult | None, str]:
    """Prompt for tool parameters and apply the tool to a volume."""
    parameters = resolve_tool_parameters(parent, tool_id, volume.data)
    if parameters is None:
        return None, "Tool application canceled"

    try:
        transformed_data = apply_tool(tool_id, volume.data, parameters)
        transformed_volume = derive_volume(volume, transformed_data)
    except ValueError as exc:
        QMessageBox.critical(parent, "Tool Application Failed", str(exc))
        return None, "Tool application failed"

    return transformed_volume, ""
