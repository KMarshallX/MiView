from __future__ import annotations

import numpy as np


_ACTIVE_LABEL_COLOR = np.array([0, 220, 120], dtype=np.uint8)
_LABEL_COLORS = np.array(
    [
        [0, 220, 120],
        [255, 196, 0],
        [0, 170, 255],
        [255, 90, 90],
        [190, 120, 255],
        [255, 140, 0],
    ],
    dtype=np.uint8,
)


def build_annotation_overlay_rgba(
    label_slice: np.ndarray,
    *,
    opacity: float,
    active_label: int,
) -> np.ndarray:
    """Convert a 2D integer label slice into a simple transparent RGBA overlay."""
    labels = np.asarray(label_slice)
    if labels.ndim != 2:
        raise ValueError(f"Annotation overlay expects a 2D label slice, got {labels.ndim}D.")

    alpha_value = int(round(min(max(float(opacity), 0.0), 1.0) * 255.0))
    overlay = np.zeros((*labels.shape, 4), dtype=np.uint8)
    foreground = labels > 0
    if not np.any(foreground) or alpha_value == 0:
        return overlay

    active_label_value = int(active_label)
    for label in np.unique(labels[foreground]):
        label_value = int(label)
        label_mask = labels == label_value
        if label_value == active_label_value:
            color = _ACTIVE_LABEL_COLOR
        else:
            color = _LABEL_COLORS[(label_value - 1) % len(_LABEL_COLORS)]
        overlay[label_mask, :3] = color
        overlay[label_mask, 3] = alpha_value
    return overlay
