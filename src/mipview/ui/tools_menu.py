from __future__ import annotations

from collections.abc import Callable

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QSpinBox,
    QToolButton,
    QWidget,
)

from mipview.tools import (
    ParameterValue,
    ToolDefinition,
    ToolParameter,
    all_tools,
    default_parameters_for_data,
    get_tool,
)


def build_tools_submenu(
    parent: QWidget,
    tools_menu: QMenu,
    on_tool_selected: Callable[[str], None],
) -> QMenu:
    utilities_menu = tools_menu.addMenu("&Utilities")
    for tool in all_tools():
        action = QAction(tool.label, parent)
        action.setStatusTip(tool.description)
        action.triggered.connect(
            lambda _checked=False, tool_id=tool.id: on_tool_selected(tool_id)
        )
        utilities_menu.addAction(action)
    return utilities_menu


def resolve_tool_parameters(
    parent: QWidget,
    tool_id: str,
    data: np.ndarray,
) -> dict[str, ParameterValue] | None:
    tool = get_tool(tool_id)
    defaults = default_parameters_for_data(tool, data)
    if not tool.parameters:
        return defaults
    dialog = _ToolParameterDialog(parent, tool, defaults)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.resolved_parameters()


class _ToolParameterDialog(QDialog):
    def __init__(
        self,
        parent: QWidget,
        tool: ToolDefinition,
        defaults: dict[str, ParameterValue],
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{tool.label} Parameters")
        self._tool = tool
        self._defaults = dict(defaults)
        self._editors: dict[str, QWidget] = {}

        form = QFormLayout()
        for parameter in tool.parameters:
            if not parameter.prompt:
                continue
            editor = self._create_editor(parameter, defaults.get(parameter.key, parameter.default))
            self._editors[parameter.key] = editor
            form.addRow(self._build_label_widget(parameter), editor)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            Qt.Orientation.Horizontal,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.setLayout(form)

    def resolved_parameters(self) -> dict[str, ParameterValue]:
        resolved: dict[str, ParameterValue] = {}
        for parameter in self._tool.parameters:
            if not parameter.prompt:
                resolved[parameter.key] = self._defaults.get(parameter.key, parameter.default)
                continue
            editor = self._editors.get(parameter.key)
            if editor is None:
                resolved[parameter.key] = self._defaults.get(parameter.key, parameter.default)
                continue
            if isinstance(editor, QSpinBox):
                value: ParameterValue = int(editor.value())
            elif isinstance(editor, QDoubleSpinBox):
                value = float(editor.value())
            elif isinstance(editor, QCheckBox):
                value = bool(editor.isChecked())
            elif isinstance(editor, QComboBox):
                value = str(editor.currentText()).strip()
            elif isinstance(editor, QLineEdit):
                value = str(editor.text()).strip()
            else:
                value = parameter.default

            if parameter.type == "string" and not str(value):
                raise ValueError(f"{parameter.label} must not be empty.")
            if parameter.require_odd and isinstance(value, int) and value % 2 == 0:
                raise ValueError(f"{parameter.label} must be an odd integer.")
            resolved[parameter.key] = value
        return resolved

    def accept(self) -> None:
        try:
            _ = self.resolved_parameters()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid Parameter", str(exc))
            return
        super().accept()

    def _build_label_widget(self, parameter: ToolParameter) -> QWidget:
        if not parameter.help_text:
            return _read_only_label(parameter.label, self)

        container = QWidget(self)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        text_label = _read_only_label(parameter.label, container)
        help_button = QToolButton(container)
        help_button.setText("?")
        help_button.setToolTip(parameter.help_text)
        help_button.setAutoRaise(True)
        layout.addWidget(text_label)
        layout.addWidget(help_button)
        layout.addStretch(1)
        return container

    def _create_editor(self, parameter: ToolParameter, initial: ParameterValue) -> QWidget:
        if parameter.type == "int":
            editor = QSpinBox(self)
            editor.setMinimum(
                int(parameter.minimum) if parameter.minimum is not None else -2_147_483_647
            )
            editor.setMaximum(
                int(parameter.maximum) if parameter.maximum is not None else 2_147_483_647
            )
            editor.setValue(int(initial))
            return editor
        if parameter.type == "float":
            editor = QDoubleSpinBox(self)
            editor.setDecimals(parameter.decimals)
            editor.setMinimum(float(parameter.minimum) if parameter.minimum is not None else -1e12)
            editor.setMaximum(float(parameter.maximum) if parameter.maximum is not None else 1e12)
            editor.setValue(float(initial))
            return editor
        if parameter.type == "bool":
            editor = QCheckBox(self)
            editor.setChecked(bool(initial))
            return editor
        if parameter.choices:
            editor = QComboBox(self)
            for choice in parameter.choices:
                editor.addItem(choice)
            choice_index = editor.findText(str(initial), Qt.MatchFlag.MatchFixedString)
            if choice_index >= 0:
                editor.setCurrentIndex(choice_index)
            return editor
        editor = QLineEdit(self)
        editor.setText(str(initial))
        return editor


def _read_only_label(text: str, parent: QWidget) -> QWidget:
    label = QLabel(text, parent)
    return label
