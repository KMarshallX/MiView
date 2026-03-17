from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QMouseEvent
from PySide6.QtWidgets import QGroupBox, QListWidget, QListWidgetItem, QMenu, QToolTip, QVBoxLayout, QWidget

from mipview.patch_history import PatchHistoryNode


class _HoverDelayListWidget(QListWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self._hover_item: QListWidgetItem | None = None
        self._hover_pos = QPoint()
        self._tooltip_timer = QTimer(self)
        self._tooltip_timer.setInterval(1000)
        self._tooltip_timer.setSingleShot(True)
        self._tooltip_timer.timeout.connect(self._show_hover_tooltip)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        hovered = self.itemAt(event.position().toPoint())
        if hovered is not self._hover_item:
            self._tooltip_timer.stop()
            QToolTip.hideText()
            self._hover_item = hovered
        self._hover_pos = event.position().toPoint()
        if hovered is not None and hovered.toolTip():
            self._tooltip_timer.start()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self._tooltip_timer.stop()
        self._hover_item = None
        QToolTip.hideText()
        super().leaveEvent(event)

    def _show_hover_tooltip(self) -> None:
        if self._hover_item is None:
            return
        tooltip = self._hover_item.toolTip()
        if not tooltip:
            return
        QToolTip.showText(
            self.viewport().mapToGlobal(self._hover_pos),
            tooltip,
            self,
        )


class PatchHistoryPanel(QGroupBox):
    restore_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Patch History", parent)
        layout = QVBoxLayout(self)
        self._list_widget = _HoverDelayListWidget(self)
        self._list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list_widget.customContextMenuRequested.connect(self._open_context_menu)
        layout.addWidget(self._list_widget)
        self._active_node_id: str | None = None

    def set_history(self, nodes: list[PatchHistoryNode], active_node_id: str) -> None:
        self._active_node_id = active_node_id
        self._list_widget.clear()
        for node in nodes:
            label = f"{node.step_index:02d}  {node.operation_label}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, node.node_id)
            item.setToolTip(self._build_tooltip(node))
            if node.node_id == active_node_id:
                font = QFont(item.font())
                font.setBold(True)
                item.setFont(font)
                item.setBackground(QColor(222, 235, 255))
            self._list_widget.addItem(item)

    def _open_context_menu(self, position: QPoint) -> None:
        item = self._list_widget.itemAt(position)
        if item is None:
            return
        node_id = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(node_id, str):
            return
        menu = QMenu(self)
        restore_action = QAction("Restore This State", menu)
        restore_action.triggered.connect(lambda: self.restore_requested.emit(node_id))
        menu.addAction(restore_action)
        menu.exec(self._list_widget.viewport().mapToGlobal(position))

    def _build_tooltip(self, node: PatchHistoryNode) -> str:
        timestamp = node.timestamp.astimezone().strftime("%Y-%m-%d %H:%M:%S")
        checkpoint = "yes" if node.is_checkpoint else "no"
        summary = node.parameter_summary if node.parameter_summary else "No parameters"
        return (
            f"Operation: {node.operation_type}\n"
            f"Parameters: {summary}\n"
            f"Checkpoint: {checkpoint}\n"
            f"Time: {timestamp}"
        )
