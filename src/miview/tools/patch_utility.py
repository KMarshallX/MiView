from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from miview.tools.registry import ParameterValue, apply_tool, get_tool


@dataclass(frozen=True)
class RegistryPatchUtility:
    utility_id: str
    label: str

    def apply(
        self,
        patch_state: np.ndarray,
        params: dict[str, ParameterValue],
    ) -> np.ndarray:
        return apply_tool(self.utility_id, patch_state, params)

    def summarize(self, params: dict[str, ParameterValue]) -> str:
        if not params:
            return "No parameters"
        ordered_items = sorted(params.items(), key=lambda item: item[0])
        return ", ".join(f"{key}={value}" for key, value in ordered_items)


def patch_utility_from_tool(tool_id: str) -> RegistryPatchUtility:
    tool = get_tool(tool_id)
    return RegistryPatchUtility(utility_id=tool.id, label=tool.label)
