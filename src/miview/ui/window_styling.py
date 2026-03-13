from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QMainWindow, QWidget

WINDOW_CONTENT_FRAME_OBJECT_NAME = "windowContentFrame"

WINDOW_FRAME_STYLE = f"""
QWidget#{WINDOW_CONTENT_FRAME_OBJECT_NAME} {{
    border: 1px solid #a7adb5;
    background-color: palette(base);
}}
"""


class ResponsiveFontScaler:
    """Applies smooth, centralized font scaling for a window's normal UI text."""

    def __init__(
        self,
        window: QMainWindow,
        reference_width: int,
        reference_height: int,
    ) -> None:
        self._window = window
        self._reference_width = max(reference_width, 1)
        self._reference_height = max(reference_height, 1)
        self._base_font = QFont(window.font())
        point_size = self._base_font.pointSizeF()
        self._base_point_size = point_size if point_size > 0 else 10.0
        self._last_point_size = -1.0

    def apply(self) -> None:
        width_ratio = self._window.width() / float(self._reference_width)
        height_ratio = self._window.height() / float(self._reference_height)
        scale = min(width_ratio, height_ratio)
        clamped_scale = min(max(scale, 0.85), 1.45)
        target_point_size = self._base_point_size * clamped_scale
        if abs(target_point_size - self._last_point_size) < 0.05:
            return

        scaled_font = QFont(self._base_font)
        scaled_font.setPointSizeF(target_point_size)
        self._window.setFont(scaled_font)

        self._apply_to_widgets(scaled_font)

        self._last_point_size = target_point_size

    def _apply_to_widgets(self, scaled_font: QFont) -> None:
        for widget in self._window.findChildren(QWidget):
            if bool(widget.property("exclude_responsive_scaling")):
                continue
            widget.setFont(scaled_font)


def apply_window_content_frame(window: QMainWindow, content_widget: QWidget) -> None:
    """Apply a subtle fallback frame to the in-app content area."""
    content_widget.setObjectName(WINDOW_CONTENT_FRAME_OBJECT_NAME)
    existing_style = window.styleSheet().strip()
    if existing_style:
        window.setStyleSheet(f"{existing_style}\n{WINDOW_FRAME_STYLE}")
    else:
        window.setStyleSheet(WINDOW_FRAME_STYLE)
