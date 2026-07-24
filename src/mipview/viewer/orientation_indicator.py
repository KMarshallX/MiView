from __future__ import annotations

from typing import Literal


ORIENTATION_INDICATOR_LABELS = "labels"
ORIENTATION_INDICATOR_WIDGET = "widget"
ORIENTATION_INDICATOR_OFF = "off"
ORIENTATION_INDICATOR_MODES = (
    ORIENTATION_INDICATOR_LABELS,
    ORIENTATION_INDICATOR_WIDGET,
    ORIENTATION_INDICATOR_OFF,
)
ORIENTATION_AXIS_COLOURS = {
    "L": "#ef5350",
    "R": "#ef5350",
    "A": "#66bb6a",
    "P": "#66bb6a",
    "I": "#42a5f5",
    "S": "#42a5f5",
}

OrientationIndicatorMode = Literal["labels", "widget", "off"]


def normalize_orientation_indicator_mode(mode: str) -> OrientationIndicatorMode:
    normalized = str(mode).strip().lower()
    if normalized not in ORIENTATION_INDICATOR_MODES:
        raise ValueError(
            "Unknown orientation indicator mode "
            f"{mode!r}; expected one of {', '.join(ORIENTATION_INDICATOR_MODES)}."
        )
    return normalized  # type: ignore[return-value]


def orientation_axis_colour(label: str) -> str:
    try:
        return ORIENTATION_AXIS_COLOURS[label.upper()]
    except KeyError as exc:
        raise ValueError(f"Unknown anatomical orientation label: {label!r}.") from exc
