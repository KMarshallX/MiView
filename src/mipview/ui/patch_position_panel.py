from __future__ import annotations

from PySide6.QtCore import QElapsedTimer, QEvent, QObject, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QHBoxLayout,
    QToolButton,
    QWidget,
)

from mipview.patch.selector import PatchBounds
from mipview.ui.collapsible_group_box import CollapsibleGroupBox


_DIRECTION_BUTTONS = (
    ("LR:", "L", "R"),
    ("AP:", "A", "P"),
    ("SI:", "S", "I"),
)

_DIRECTION_AXIS_SIGN = {
    "L": (0, -1),
    "R": (0, 1),
    "A": (1, -1),
    "P": (1, 1),
    "S": (2, -1),
    "I": (2, 1),
}


class PatchPositionPanel(CollapsibleGroupBox):
    """Six-button fixed-voxel patch translation control."""

    movement_requested = Signal(str)
    movement_finished = Signal(str, int)
    display_location_changed = Signal(bool)

    INITIAL_REPEAT_DELAY_MS = 400
    ACCELERATION_STAGE_MS = 750
    INITIAL_REPEAT_RATE = 4
    MAX_REPEAT_RATE = 16

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Patch Position", parent)
        self._buttons: dict[str, QToolButton] = {}
        self._source_available = False
        self._bounds: PatchBounds | None = None
        self._source_shape: tuple[int, int, int] | None = None
        self._held_direction: str | None = None
        self._applied_during_hold = 0
        self._hold_elapsed = QElapsedTimer()
        self._repeat_timer = QTimer(self)
        self._repeat_timer.setSingleShot(True)
        self._repeat_timer.timeout.connect(self._repeat_once)

        form = QFormLayout(self)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        for label, negative_direction, positive_direction in _DIRECTION_BUTTONS:
            row = QWidget(self)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(6)
            row_layout.addWidget(
                self._make_button(negative_direction, Qt.ArrowType.LeftArrow)
            )
            row_layout.addWidget(
                self._make_button(positive_direction, Qt.ArrowType.RightArrow)
            )
            form.addRow(label, row)

        self.display_location_checkbox = QCheckBox(self)
        self.display_location_checkbox.toggled.connect(
            self.display_location_changed.emit
        )
        form.addRow("Display Patch Location:", self.display_location_checkbox)

        self._refresh_button_availability()

    def set_source_geometry(
        self,
        bounds: PatchBounds | None,
        source_shape: tuple[int, int, int] | None,
    ) -> None:
        if source_shape is not None and (
            len(source_shape) != 3 or any(int(length) <= 0 for length in source_shape)
        ):
            raise ValueError(
                f"Expected a positive 3D source shape, got {source_shape}."
            )
        self._bounds = bounds
        self._source_shape = source_shape
        self._source_available = bounds is not None and source_shape is not None
        self._refresh_button_availability()
        if self._held_direction is not None:
            button = self._buttons[self._held_direction]
            if not button.isEnabled():
                self.stop_movement()

    def record_applied_movement(self, direction: str, voxels: int) -> None:
        if direction == self._held_direction:
            self._applied_during_hold += abs(int(voxels))

    def cancel_movement(self) -> None:
        self._stop_movement(emit_finished=False)

    def stop_movement(self) -> None:
        self._stop_movement(emit_finished=True)

    def repeat_rate_for_elapsed_ms(self, elapsed_ms: int) -> int:
        repeating_ms = max(int(elapsed_ms) - self.INITIAL_REPEAT_DELAY_MS, 0)
        stage = min(repeating_ms // self.ACCELERATION_STAGE_MS, 2)
        return min(
            self.INITIAL_REPEAT_RATE * (2**stage),
            self.MAX_REPEAT_RATE,
        )

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            watched in self._buttons.values()
            and event.type() in {QEvent.Type.FocusOut, QEvent.Type.Hide}
            and self._held_direction is not None
        ):
            self.stop_movement()
        return super().eventFilter(watched, event)

    def _make_button(
        self,
        direction: str,
        arrow_type: Qt.ArrowType,
    ) -> QToolButton:
        button = QToolButton(self)
        button.setArrowType(arrow_type)
        button.setMinimumSize(32, 30)
        button.setAutoRepeat(False)
        button.setAccessibleName(f"Move patch toward {direction}")
        button.setToolTip(f"Move patch 1 voxel toward {direction}")
        button.installEventFilter(self)
        button.pressed.connect(lambda value=direction: self._start_movement(value))
        button.released.connect(lambda value=direction: self._release_movement(value))
        self._buttons[direction] = button
        return button

    def _start_movement(self, direction: str) -> None:
        if not self._buttons[direction].isEnabled():
            return
        if self._held_direction is not None:
            self.stop_movement()
        self._held_direction = direction
        self._applied_during_hold = 0
        self._hold_elapsed.start()
        self.movement_requested.emit(direction)
        if (
            self._held_direction == direction
            and self._buttons[direction].isEnabled()
        ):
            self._repeat_timer.start(self.INITIAL_REPEAT_DELAY_MS)

    def _release_movement(self, direction: str) -> None:
        if direction == self._held_direction:
            self.stop_movement()

    def _repeat_once(self) -> None:
        direction = self._held_direction
        if direction is None or not self._buttons[direction].isEnabled():
            self.stop_movement()
            return
        self.movement_requested.emit(direction)
        if (
            direction != self._held_direction
            or not self._buttons[direction].isEnabled()
        ):
            return
        rate = self.repeat_rate_for_elapsed_ms(self._hold_elapsed.elapsed())
        self._repeat_timer.start(max(1, round(1000 / rate)))

    def _stop_movement(self, *, emit_finished: bool = True) -> None:
        direction = self._held_direction
        applied = self._applied_during_hold
        self._repeat_timer.stop()
        self._held_direction = None
        self._applied_during_hold = 0
        if emit_finished and direction is not None and applied > 0:
            self.movement_finished.emit(direction, applied)

    def _refresh_button_availability(self) -> None:
        for direction, button in self._buttons.items():
            button.setEnabled(
                self._source_available and self._can_move(direction)
            )

    def _can_move(self, direction: str) -> bool:
        if self._bounds is None or self._source_shape is None:
            return False
        axis, sign = _DIRECTION_AXIS_SIGN[direction]
        starts = (
            self._bounds.x_start,
            self._bounds.y_start,
            self._bounds.z_start,
        )
        ends = (
            self._bounds.x_end,
            self._bounds.y_end,
            self._bounds.z_end,
        )
        return starts[axis] > 0 if sign < 0 else ends[axis] < self._source_shape[axis]
