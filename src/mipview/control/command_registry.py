from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mipview.control.controller import MipViewController
from mipview.control.result import CommandResult


CommandHandler = Callable[..., CommandResult]


class CommandRegistry:
    """Map stable command names to controller methods."""

    def __init__(self, controller: MipViewController) -> None:
        self.controller = controller
        self._commands: dict[str, CommandHandler] = {}
        self._register_defaults()

    def register(self, name: str, handler: CommandHandler) -> None:
        self._commands[name] = handler

    def execute(self, name: str, args: dict[str, Any]) -> CommandResult:
        if name not in self._commands:
            return CommandResult(False, f"Unknown command: {name}")

        if not isinstance(args, dict):
            return CommandResult(
                False,
                f"Invalid arguments for {name}: args must be a dict.",
            )

        try:
            return self._commands[name](**args)
        except TypeError as exc:
            return CommandResult(False, f"Invalid arguments for {name}: {exc}")
        except Exception as exc:
            return CommandResult(False, f"Command failed: {exc}")

    def command_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._commands))

    def _register_defaults(self) -> None:
        self.register("viewer.status", self.controller.get_status)
        self.register("viewer.screenshot", self.controller.capture_screenshot)
        self.register("viewer.export_state", self.controller.export_viewer_state)
        self.register("cursor.move", self.controller.move_cursor)
        self.register("patch.size", self.controller.set_patch_size)
        self.register("patch.center", self.controller.set_patch_center)
        self.register("patch.select", self.controller.select_patch)
        self.register("patch.export_raw", self.controller.export_raw_patch)
        self.register("patch.save", self.controller.save_patch)
        self.register("patch.screenshot", self.controller.capture_patch_screenshot)
        self.register("projection.mode", self.controller.set_projection_mode)
        self.register("projection.save", self.controller.save_projection)
        self.register("graph.status", self.controller.get_graph_status)
        self.register("graph.save", self.controller.save_graph_state)
        self.register("graph.load", self.controller.load_graph_state)
        self.register("graph.open", self.controller.open_graph_state)
        self.register("graph.activate", self.controller.set_graph_active)
        self.register("graph.set_display", self.controller.set_graph_display)
        self.register("graph.add_node", self.controller.add_graph_node)
        self.register("graph.add_voxel_node", self.controller.add_graph_voxel_node)
        self.register("graph.delete_node", self.controller.delete_graph_node)
        self.register("graph.add_edge", self.controller.add_graph_edge)
        self.register("graph.delete_edge", self.controller.delete_graph_edge)
        self.register("graph.curve_edge", self.controller.curve_graph_edge)
        self.register("graph.straighten_edge", self.controller.straighten_graph_edge)
        self.register("graph.set_normal_line", self.controller.set_graph_normal_line)
        self.register(
            "graph.set_extension_line",
            self.controller.set_graph_extension_line,
        )
        self.register("graph.add_node_vector", self.controller.add_graph_node_vector)
        self.register(
            "graph.add_tangent_vector",
            self.controller.add_graph_tangent_vector,
        )
        self.register(
            "graph.add_normal_vector",
            self.controller.add_graph_normal_vector,
        )
        self.register("graph.flip_vector", self.controller.flip_graph_vector)
        self.register("graph.delete_vector", self.controller.delete_graph_vector)
        self.register("graph.split_edge", self.controller.split_graph_edge)
        self.register("graph.calculate_angle", self.controller.calculate_graph_angle)
        self.register(
            "graph.set_angle_label_position",
            self.controller.set_graph_angle_label_position,
        )
        self.register("graph.delete_angle", self.controller.delete_graph_angle)
        self.register("graph.clear_angles", self.controller.clear_graph_angles)
        self.register("graph.clear", self.controller.clear_graph)
        self.register("annotation.create", self.controller.create_annotation)
        self.register("annotation.paint_stroke", self.controller.paint_annotation_stroke)
        self.register("annotation.erase_stroke", self.controller.erase_annotation_stroke)
        self.register("annotation.save", self.controller.save_annotation)
