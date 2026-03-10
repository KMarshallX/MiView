from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from miview.viewer.slice_geometry import clamp_cursor_to_volume


class CursorState(QObject):
    """Shared logical voxel cursor for synchronized slice views."""

    cursor_changed = Signal(int, int, int)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._volume_shape: tuple[int, int, int] | None = None
        self._cursor_position: tuple[int, int, int] | None = None

    def set_volume_shape(self, shape: tuple[int, int, int]) -> None:
        if len(shape) != 3:
            raise ValueError(f"Cursor state expects a 3D shape, got {shape}.")

        self._volume_shape = shape
        if self._cursor_position is not None:
            self.set_cursor_position(self._cursor_position)

    def cursor_position(self) -> tuple[int, int, int] | None:
        return self._cursor_position

    def set_cursor_position(self, cursor_position: tuple[int, int, int]) -> None:
        if self._volume_shape is None:
            self._cursor_position = cursor_position
            return

        clamped_cursor = clamp_cursor_to_volume(cursor_position, self._volume_shape)
        if clamped_cursor == self._cursor_position:
            return

        self._cursor_position = clamped_cursor
        self.cursor_changed.emit(*clamped_cursor)
