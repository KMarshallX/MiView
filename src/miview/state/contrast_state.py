from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class ContrastState(QObject):
    """Shared display window for intensity contrast across all slice views."""

    availability_changed = Signal(bool)
    range_changed = Signal(float, float)
    window_changed = Signal(float, float)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._enabled = False
        self._range_min = 0.0
        self._range_max = 1.0
        self._window_min = 0.0
        self._window_max = 1.0

    def is_enabled(self) -> bool:
        return self._enabled

    def available_range(self) -> tuple[float, float]:
        return (self._range_min, self._range_max)

    def window(self) -> tuple[float, float]:
        return (self._window_min, self._window_max)

    def clear(self) -> None:
        if not self._enabled:
            return
        self._enabled = False
        self.availability_changed.emit(False)

    def set_available_range(self, range_min: float, range_max: float) -> None:
        if range_max < range_min:
            range_min, range_max = range_max, range_min

        changed = (
            abs(range_min - self._range_min) > 1e-6
            or abs(range_max - self._range_max) > 1e-6
        )
        self._range_min = range_min
        self._range_max = range_max

        previous_enabled = self._enabled
        self._enabled = True
        if not previous_enabled:
            self.availability_changed.emit(True)

        if changed:
            self.range_changed.emit(self._range_min, self._range_max)

    def set_window(
        self, window_min: float, window_max: float, force_emit: bool = False
    ) -> None:
        if not self._enabled:
            return

        if window_max < window_min:
            window_min, window_max = window_max, window_min

        clamped_min = min(max(window_min, self._range_min), self._range_max)
        clamped_max = min(max(window_max, self._range_min), self._range_max)
        if clamped_max < clamped_min:
            clamped_min, clamped_max = clamped_max, clamped_min

        if (
            not force_emit
            and (
                abs(clamped_min - self._window_min) < 1e-6
                and abs(clamped_max - self._window_max) < 1e-6
            )
        ):
            return

        self._window_min = clamped_min
        self._window_max = clamped_max
        self.window_changed.emit(self._window_min, self._window_max)
