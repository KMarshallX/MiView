from __future__ import annotations

import math

from PySide6.QtCore import QObject, Signal


class ZoomState(QObject):
    """Shared zoom factor for synchronized slice views."""

    zoom_changed = Signal(float)

    MIN_ZOOM = 0.25
    MAX_ZOOM = 20.0

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        maximum_zoom: float = MAX_ZOOM,
    ) -> None:
        super().__init__(parent)
        if not math.isfinite(maximum_zoom) or maximum_zoom < self.MIN_ZOOM:
            raise ValueError(
                f"Maximum zoom must be finite and at least {self.MIN_ZOOM}."
            )
        self._maximum_zoom = float(maximum_zoom)
        self._zoom_factor = 1.0

    def zoom_factor(self) -> float:
        return self._zoom_factor

    def maximum_zoom(self) -> float:
        return self._maximum_zoom

    def set_zoom_factor(self, zoom_factor: float) -> None:
        clamped_zoom = min(max(zoom_factor, self.MIN_ZOOM), self._maximum_zoom)
        if abs(clamped_zoom - self._zoom_factor) < 1e-6:
            return

        self._zoom_factor = clamped_zoom
        self.zoom_changed.emit(clamped_zoom)
