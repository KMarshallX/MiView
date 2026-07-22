from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QGroupBox, QStyle, QStyleOptionGroupBox, QWidget


class CollapsibleGroupBox(QGroupBox):
    """A group box with a disclosure-arrow header for showing its contents."""

    def __init__(
        self,
        title: str,
        parent: QWidget | None = None,
        *,
        expanded: bool = False,
    ) -> None:
        super().__init__("", parent)
        self._title_text = title
        self._header_pressed = False
        # Retain QGroupBox's native child enable/disable behavior while
        # replacing its checkbox indicator with a disclosure arrow.
        self.setStyleSheet("QGroupBox::indicator { width: 0px; height: 0px; }")
        self.setCheckable(True)
        self.toggled.connect(self._apply_expanded_state)
        self.setChecked(bool(expanded))
        self._apply_expanded_state(bool(expanded))

    def is_expanded(self) -> bool:
        return self.isChecked()

    def set_expanded(self, expanded: bool) -> None:
        self.setChecked(bool(expanded))

    def _apply_expanded_state(self, expanded: bool) -> None:
        self.setTitle(f"{'▾' if expanded else '▸'}  {self._title_text}")
        if expanded:
            self.setMaximumHeight(16777215)
        else:
            self.setMaximumHeight(self._header_height())
        self.updateGeometry()
        self._refresh_ancestor_layouts()

    def _refresh_ancestor_layouts(self) -> None:
        if self.layout() is None:
            return
        ancestors: list[QWidget] = []
        ancestor = self.parentWidget()
        while ancestor is not None:
            ancestors.append(ancestor)
            ancestor.updateGeometry()
            layout = ancestor.layout()
            if layout is not None:
                layout.invalidate()
            ancestor = ancestor.parentWidget()

        # Reflow from the window inward so each child receives its new space.
        for ancestor in reversed(ancestors):
            layout = ancestor.layout()
            if layout is not None:
                layout.activate()

    def _header_height(self) -> int:
        option = QStyleOptionGroupBox()
        self.initStyleOption(option)
        label_rect = self.style().subControlRect(
            QStyle.ComplexControl.CC_GroupBox,
            option,
            QStyle.SubControl.SC_GroupBoxLabel,
            self,
        )
        indicator_rect = self.style().subControlRect(
            QStyle.ComplexControl.CC_GroupBox,
            option,
            QStyle.SubControl.SC_GroupBoxCheckBox,
            self,
        )
        content_bottom = max(label_rect.bottom(), indicator_rect.bottom())
        return max(content_bottom + 4, self.fontMetrics().height() + 6)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self._header_pressed = (
            event.button() == Qt.MouseButton.LeftButton
            and event.position().y() <= self._header_height()
        )
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        was_expanded = self.is_expanded()
        header_clicked = (
            self._header_pressed
            and event.button() == Qt.MouseButton.LeftButton
            and event.position().y() <= self._header_height()
        )
        self._header_pressed = False
        super().mouseReleaseEvent(event)
        if header_clicked and self.is_expanded() == was_expanded:
            # QGroupBox handles its label and indicator; this covers the rest
            # of the header so the entire title row behaves consistently.
            self.set_expanded(not was_expanded)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if (
            event.type()
            in {
                QEvent.Type.FontChange,
                QEvent.Type.StyleChange,
                QEvent.Type.PaletteChange,
            }
            and not self.is_expanded()
        ):
            self._apply_expanded_state(False)
