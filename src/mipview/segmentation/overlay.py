from __future__ import annotations

import colorsys

import numpy as np


_GOLDEN_RATIO_CONJUGATE = 0.6180339887498949


def build_segmentation_overlay_rgba(
    label_slice: np.ndarray,
    *,
    opacity: float,
) -> np.ndarray:
    """Convert a 2D multi-label segmentation into a deterministic RGBA overlay."""
    labels = np.asarray(label_slice)
    if labels.ndim != 2:
        raise ValueError(
            f"Segmentation overlay expects a 2D label slice, got {labels.ndim}D."
        )

    overlay = np.zeros((*labels.shape, 4), dtype=np.uint8)
    alpha_value = int(round(min(max(float(opacity), 0.0), 1.0) * 255.0))
    foreground = np.isfinite(labels) & (labels > 0)
    if alpha_value == 0 or not np.any(foreground):
        return overlay

    for raw_label in np.unique(labels[foreground]):
        label_value = int(raw_label)
        label_mask = labels == raw_label
        overlay[label_mask, :3] = segmentation_label_color(label_value)
        overlay[label_mask, 3] = alpha_value
    return overlay


def segmentation_label_color(label: int) -> np.ndarray:
    """Return a stable high-contrast RGB color for a positive integer label."""
    label_value = int(label)
    if label_value <= 0:
        raise ValueError("Segmentation label colors require a positive label.")
    hue = ((label_value - 1) * _GOLDEN_RATIO_CONJUGATE) % 1.0
    red, green, blue = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
    return np.asarray(
        [round(red * 255.0), round(green * 255.0), round(blue * 255.0)],
        dtype=np.uint8,
    )
