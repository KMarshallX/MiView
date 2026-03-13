from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

import numpy as np

from miview.tools.processing import (
    invert_divide,
    invert_minus,
    local_normalize,
    normalize,
    standardize,
)

ParameterType = Literal["int", "float"]


@dataclass(frozen=True)
class ToolParameter:
    key: str
    label: str
    type: ParameterType
    default: int | float
    prompt: bool = True
    minimum: int | float | None = None
    maximum: int | float | None = None
    decimals: int = 3
    require_odd: bool = False
    default_from_data: Literal["none", "min", "max"] = "none"


@dataclass(frozen=True)
class ToolDefinition:
    id: str
    label: str
    description: str
    parameters: tuple[ToolParameter, ...]
    apply: Callable[[np.ndarray, dict[str, int | float]], np.ndarray]


def all_tools() -> tuple[ToolDefinition, ...]:
    return _TOOL_DEFINITIONS


def get_tool(tool_id: str) -> ToolDefinition:
    for tool in _TOOL_DEFINITIONS:
        if tool.id == tool_id:
            return tool
    raise ValueError(f"Unknown tool id: {tool_id}")


def apply_tool(
    tool_id: str,
    data: np.ndarray,
    parameters: dict[str, int | float],
) -> np.ndarray:
    tool = get_tool(tool_id)
    return np.asarray(tool.apply(data, parameters), dtype=np.float32)


def default_parameters_for_data(
    tool: ToolDefinition,
    data: np.ndarray,
) -> dict[str, int | float]:
    source = np.asarray(data)
    source_min = float(np.min(source))
    source_max = float(np.max(source))

    defaults: dict[str, int | float] = {}
    for parameter in tool.parameters:
        if parameter.default_from_data == "min":
            defaults[parameter.key] = (
                int(source_min) if parameter.type == "int" else source_min
            )
        elif parameter.default_from_data == "max":
            defaults[parameter.key] = (
                int(source_max) if parameter.type == "int" else source_max
            )
        else:
            defaults[parameter.key] = parameter.default
    return defaults


_TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        id="normalize",
        label="Normalization",
        description="Rescale intensities to [0, 1].",
        parameters=(),
        apply=lambda data, _params: normalize(data, 0.0, 1.0),
    ),
    ToolDefinition(
        id="standardize",
        label="Standardisation",
        description="Apply global z-score standardisation.",
        parameters=(),
        apply=lambda data, _params: standardize(data),
    ),
    ToolDefinition(
        id="local_normalize",
        label="Local Normalisation",
        description="Apply local z-score normalization with odd window size.",
        parameters=(
            ToolParameter(
                key="window_size",
                label="Window size (odd voxels)",
                type="int",
                default=9,
                minimum=1,
                require_odd=True,
            ),
        ),
        apply=lambda data, params: local_normalize(
            data,
            window_size=int(params["window_size"]),
        ),
    ),
    ToolDefinition(
        id="invert_minus",
        label="Contrast Inversion (Minus)",
        description="Compute output = reference - input.",
        parameters=(
            ToolParameter(
                key="reference_value",
                label="Reference value",
                type="float",
                default=0.0,
                default_from_data="max",
            ),
        ),
        apply=lambda data, params: invert_minus(
            data,
            reference_value=float(params["reference_value"]),
        ),
    ),
    ToolDefinition(
        id="invert_divide",
        label="Contrast Inversion (Divide)",
        description="Compute output = numerator / input with safe near-zero handling.",
        parameters=(
            ToolParameter(
                key="numerator",
                label="Numerator value",
                type="float",
                default=1.0,
                default_from_data="max",
            ),
        ),
        apply=lambda data, params: invert_divide(
            data,
            numerator=float(params["numerator"]),
        ),
    ),
)
