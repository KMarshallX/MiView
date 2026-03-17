from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

import numpy as np

from mipview.tools.processing import (
    frangi_filter,
    gaussian_filter,
    hessian_filter,
    invert_divide,
    invert_minus,
    local_normalize,
    normalize,
    standardize,
)

ParameterType = Literal["int", "float", "bool", "string"]
ParameterValue = int | float | bool | str


@dataclass(frozen=True)
class ToolParameter:
    key: str
    label: str
    type: ParameterType
    default: ParameterValue
    prompt: bool = True
    minimum: int | float | None = None
    maximum: int | float | None = None
    decimals: int = 3
    require_odd: bool = False
    default_from_data: Literal["none", "min", "max"] = "none"
    choices: tuple[str, ...] = ()
    help_text: str = ""


@dataclass(frozen=True)
class ToolDefinition:
    id: str
    label: str
    description: str
    parameters: tuple[ToolParameter, ...]
    apply: Callable[[np.ndarray, dict[str, ParameterValue]], np.ndarray]


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
    parameters: dict[str, ParameterValue],
) -> np.ndarray:
    tool = get_tool(tool_id)
    return np.asarray(tool.apply(data, parameters), dtype=np.float32)


def default_parameters_for_data(
    tool: ToolDefinition,
    data: np.ndarray,
) -> dict[str, ParameterValue]:
    source = np.asarray(data)
    source_min = float(np.min(source))
    source_max = float(np.max(source))

    defaults: dict[str, ParameterValue] = {}
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
    ToolDefinition(
        id="gaussian_filter",
        label="Gaussian Filter",
        description="Smooth intensities with Gaussian filtering.",
        parameters=(
            ToolParameter(
                key="sigma",
                label="Sigma",
                type="string",
                default="1.0",
                help_text=(
                    "Use a single value like 1.0, or comma-separated values "
                    "like 1.0,1.5,2.0 for per-axis sigma."
                ),
            ),
            ToolParameter(
                key="mode",
                label="Border mode",
                type="string",
                default="reflect",
                choices=("reflect", "constant", "nearest", "mirror", "wrap"),
            ),
        ),
        apply=lambda data, params: gaussian_filter(
            data,
            sigma=str(params["sigma"]),
            mode=str(params["mode"]),
        ),
    ),
    ToolDefinition(
        id="hessian_filter",
        label="Hessian Filter",
        description="Enhance ridge-like structures with Hessian vesselness.",
        parameters=(
            ToolParameter(
                key="sigma",
                label="Sigma",
                type="float",
                default=1.0,
                minimum=0.001,
            ),
            ToolParameter(
                key="gamma",
                label="Gamma",
                type="float",
                default=15.0,
                minimum=0.001,
            ),
            ToolParameter(
                key="black_ridges",
                label="Detect black ridges",
                type="bool",
                default=True,
            ),
        ),
        apply=lambda data, params: hessian_filter(
            data,
            sigma=float(params["sigma"]),
            gamma=float(params["gamma"]),
            black_ridges=bool(params["black_ridges"]),
        ),
    ),
    ToolDefinition(
        id="frangi_filter",
        label="Frangi Filter",
        description="Enhance vessel-like structures with Frangi filtering.",
        parameters=(
            ToolParameter(
                key="sigma",
                label="Sigma",
                type="float",
                default=1.0,
                minimum=0.001,
            ),
            ToolParameter(
                key="gamma",
                label="Gamma",
                type="float",
                default=15.0,
                minimum=0.001,
            ),
            ToolParameter(
                key="black_ridges",
                label="Detect black ridges",
                type="bool",
                default=True,
            ),
        ),
        apply=lambda data, params: frangi_filter(
            data,
            sigma=float(params["sigma"]),
            gamma=float(params["gamma"]),
            black_ridges=bool(params["black_ridges"]),
        ),
    ),
)
