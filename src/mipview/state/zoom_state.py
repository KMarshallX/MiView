from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class ZoomState(QObject):
    """Shared zoom factor for synchronized slice views."""

    zoom_changed = Signal(float)

    MIN_ZOOM = 0.25
    MAX_ZOOM = 8.0

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._zoom_factor = 1.0

    def zoom_factor(self) -> float:
        return self._zoom_factor

    def set_zoom_factor(self, zoom_factor: float) -> None:
        clamped_zoom = min(max(zoom_factor, self.MIN_ZOOM), self.MAX_ZOOM)
        if abs(clamped_zoom - self._zoom_factor) < 1e-6:
            return

        self._zoom_factor = clamped_zoom
        self.zoom_changed.emit(clamped_zoom)
