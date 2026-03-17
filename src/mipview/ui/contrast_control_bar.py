from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QWidget,
)


class DualHandleSlider(QWidget):
    """Lightweight horizontal range slider with independent lower/upper handles."""

    range_changed = Signal(int, int)

    HANDLE_RADIUS = 7.0
    TRACK_HEIGHT = 4.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._minimum = 0
        self._maximum = 1000
        self._lower_value = 0
        self._upper_value = 1000
        self._active_handle: str | None = None
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(28)

    def set_range(self, minimum: int, maximum: int) -> None:
        if maximum < minimum:
            minimum, maximum = maximum, minimum
        self._minimum = minimum
        self._maximum = maximum
        self.set_values(self._lower_value, self._upper_value)

    def set_values(self, lower_value: int, upper_value: int) -> None:
        lower = self._clamp(lower_value)
        upper = self._clamp(upper_value)
        if upper < lower:
            lower, upper = upper, lower

        if lower == self._lower_value and upper == self._upper_value:
            return

        self._lower_value = lower
        self._upper_value = upper
        self.range_changed.emit(self._lower_value, self._upper_value)
        self.update()

    def lower_value(self) -> int:
        return self._lower_value

    def upper_value(self) -> int:
        return self._upper_value

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        track_rect = self._track_rect()
        lower_x = self._value_to_x(self._lower_value)
        upper_x = self._value_to_x(self._upper_value)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#505050"))
        painter.drawRoundedRect(track_rect, 2.0, 2.0)

        selection_rect = QRectF(
            lower_x,
            track_rect.top(),
            max(upper_x - lower_x, 1.0),
            track_rect.height(),
        )
        painter.setBrush(QColor("#80b6ff"))
        painter.drawRoundedRect(selection_rect, 2.0, 2.0)

        painter.setPen(QPen(QColor("#2a2a2a"), 1.0))
        painter.setBrush(QColor("#dcdcdc"))
        painter.drawEllipse(
            QPointF(lower_x, track_rect.center().y()),
            self.HANDLE_RADIUS,
            self.HANDLE_RADIUS,
        )
        painter.drawEllipse(
            QPointF(upper_x, track_rect.center().y()),
            self.HANDLE_RADIUS,
            self.HANDLE_RADIUS,
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        lower_x = self._value_to_x(self._lower_value)
        upper_x = self._value_to_x(self._upper_value)
        distance_to_lower = abs(event.position().x() - lower_x)
        distance_to_upper = abs(event.position().x() - upper_x)
        self._active_handle = "lower" if distance_to_lower <= distance_to_upper else "upper"
        self._update_from_mouse(event.position().x())

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._active_handle is None:
            return
        self._update_from_mouse(event.position().x())

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        del event
        self._active_handle = None

    def _update_from_mouse(self, x_position: float) -> None:
        value = self._x_to_value(x_position)
        if self._active_handle == "lower":
            self.set_values(min(value, self._upper_value), self._upper_value)
        elif self._active_handle == "upper":
            self.set_values(self._lower_value, max(value, self._lower_value))

    def _clamp(self, value: int) -> int:
        return min(max(value, self._minimum), self._maximum)

    def _track_rect(self) -> QRectF:
        horizontal_margin = self.HANDLE_RADIUS + 2.0
        track_y = (self.height() - self.TRACK_HEIGHT) / 2.0
        return QRectF(
            horizontal_margin,
            track_y,
            max(self.width() - (2.0 * horizontal_margin), 1.0),
            self.TRACK_HEIGHT,
        )

    def _value_to_x(self, value: int) -> float:
        if self._maximum <= self._minimum:
            return self._track_rect().left()
        fraction = (value - self._minimum) / (self._maximum - self._minimum)
        track_rect = self._track_rect()
        return track_rect.left() + (fraction * track_rect.width())

    def _x_to_value(self, x_position: float) -> int:
        track_rect = self._track_rect()
        if track_rect.width() <= 0.0 or self._maximum <= self._minimum:
            return self._minimum
        clamped_x = min(max(x_position, track_rect.left()), track_rect.right())
        fraction = (clamped_x - track_rect.left()) / track_rect.width()
        value = self._minimum + fraction * (self._maximum - self._minimum)
        return int(round(value))


class ContrastControlBar(QWidget):
    """Contrast controls: min/max fields, dual-ended slider, and Auto button."""

    window_changed = Signal(float, float)
    auto_requested = Signal()

    SLIDER_STEPS = 10000

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._range_min = 0.0
        self._range_max = 1.0
        self._updating = False

        self.min_spinbox = QDoubleSpinBox(self)
        self.min_spinbox.setDecimals(3)
        self.min_spinbox.setKeyboardTracking(False)
        self.min_spinbox.setMinimumWidth(105)

        self.max_spinbox = QDoubleSpinBox(self)
        self.max_spinbox.setDecimals(3)
        self.max_spinbox.setKeyboardTracking(False)
        self.max_spinbox.setMinimumWidth(105)

        self.range_slider = DualHandleSlider(self)
        self.auto_button = QPushButton("Auto", self)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 4)
        layout.setSpacing(8)
        layout.addWidget(self.min_spinbox)
        layout.addWidget(self.range_slider, 1)
        layout.addWidget(self.max_spinbox)
        layout.addWidget(self.auto_button)

        self.min_spinbox.valueChanged.connect(self._on_spinbox_changed)
        self.max_spinbox.valueChanged.connect(self._on_spinbox_changed)
        self.range_slider.range_changed.connect(self._on_slider_changed)
        self.auto_button.clicked.connect(self.auto_requested.emit)

        self.range_slider.set_range(0, self.SLIDER_STEPS)
        self.set_enabled_state(False)

    def set_enabled_state(self, enabled: bool) -> None:
        self.min_spinbox.setEnabled(enabled)
        self.max_spinbox.setEnabled(enabled)
        self.range_slider.setEnabled(enabled)
        self.auto_button.setEnabled(enabled)

    def set_available_range(self, range_min: float, range_max: float) -> None:
        if range_max < range_min:
            range_min, range_max = range_max, range_min
        self._range_min = range_min
        self._range_max = range_max

        self._updating = True
        self.min_spinbox.setRange(range_min, range_max)
        self.max_spinbox.setRange(range_min, range_max)
        self._updating = False

        self.set_window(range_min, range_max)

    def set_window(self, window_min: float, window_max: float) -> None:
        if window_max < window_min:
            window_min, window_max = window_max, window_min

        lower = min(max(window_min, self._range_min), self._range_max)
        upper = min(max(window_max, self._range_min), self._range_max)
        if upper < lower:
            lower, upper = upper, lower

        self._updating = True
        self.min_spinbox.setValue(lower)
        self.max_spinbox.setValue(upper)
        self.range_slider.set_values(
            self._float_to_slider(lower),
            self._float_to_slider(upper),
        )
        self._updating = False

    def _on_slider_changed(self, lower_value: int, upper_value: int) -> None:
        if self._updating:
            return

        lower = self._slider_to_float(lower_value)
        upper = self._slider_to_float(upper_value)

        self._updating = True
        self.min_spinbox.setValue(lower)
        self.max_spinbox.setValue(upper)
        self._updating = False
        self.window_changed.emit(lower, upper)

    def _on_spinbox_changed(self, _: float) -> None:
        if self._updating:
            return

        lower = self.min_spinbox.value()
        upper = self.max_spinbox.value()
        if upper < lower:
            sender = self.sender()
            if sender is self.min_spinbox:
                upper = lower
                self.max_spinbox.setValue(upper)
            else:
                lower = upper
                self.min_spinbox.setValue(lower)

        self._updating = True
        self.range_slider.set_values(
            self._float_to_slider(lower),
            self._float_to_slider(upper),
        )
        self._updating = False
        self.window_changed.emit(lower, upper)

    def _float_to_slider(self, value: float) -> int:
        if self._range_max <= self._range_min:
            return 0
        fraction = (value - self._range_min) / (self._range_max - self._range_min)
        return int(round(min(max(fraction, 0.0), 1.0) * self.SLIDER_STEPS))

    def _slider_to_float(self, value: int) -> float:
        if self._range_max <= self._range_min:
            return self._range_min
        fraction = value / self.SLIDER_STEPS
        return self._range_min + fraction * (self._range_max - self._range_min)
