from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from uuid import uuid4

import numpy as np

PatchApplyOperation = Callable[[np.ndarray, str, dict[str, int | float | bool | str]], np.ndarray]


@dataclass
class PatchHistoryNode:
    node_id: str
    parent_id: str | None
    child_ids: list[str]
    step_index: int
    timestamp: datetime
    operation_type: str
    operation_label: str
    operation_parameters: dict[str, int | float | bool | str]
    parameter_summary: str
    is_checkpoint: bool
    checkpoint_patch: np.ndarray | None = None


class PatchReconstructionEngine:
    """Deterministic, side-effect-free patch reconstruction from history nodes."""

    def __init__(self, apply_operation: PatchApplyOperation) -> None:
        self._apply_operation = apply_operation

    def reconstruct(
        self,
        nodes: dict[str, PatchHistoryNode],
        target_node_id: str,
    ) -> np.ndarray:
        lineage = self._lineage_to_root(nodes, target_node_id)
        checkpoint_index = self._nearest_checkpoint_index(lineage)
        checkpoint_node = lineage[checkpoint_index]
        if checkpoint_node.checkpoint_patch is None:
            raise ValueError("Checkpoint node is missing patch snapshot data.")

        state = np.asarray(checkpoint_node.checkpoint_patch).copy()
        for node in lineage[checkpoint_index + 1 :]:
            state = np.asarray(
                self._apply_operation(
                    state,
                    node.operation_type,
                    dict(node.operation_parameters),
                )
            )
        return state

    def _lineage_to_root(
        self,
        nodes: dict[str, PatchHistoryNode],
        target_node_id: str,
    ) -> list[PatchHistoryNode]:
        if target_node_id not in nodes:
            raise ValueError(f"Unknown patch history node id: {target_node_id}")

        lineage: list[PatchHistoryNode] = []
        current_id: str | None = target_node_id
        while current_id is not None:
            node = nodes.get(current_id)
            if node is None:
                raise ValueError(f"Missing history node referenced by id: {current_id}")
            lineage.append(node)
            current_id = node.parent_id
        lineage.reverse()
        return lineage

    def _nearest_checkpoint_index(self, lineage: list[PatchHistoryNode]) -> int:
        for index in range(len(lineage) - 1, -1, -1):
            if lineage[index].is_checkpoint:
                return index
        raise ValueError("Patch history has no checkpoint ancestor for reconstruction.")


class PatchHistoryManager:
    """Patch-window-only history manager with linear timeline behavior."""

    def __init__(
        self,
        initial_patch: np.ndarray,
        apply_operation: PatchApplyOperation,
        checkpoint_interval: int = 5,
    ) -> None:
        if checkpoint_interval < 1:
            raise ValueError("checkpoint_interval must be >= 1")
        self._checkpoint_interval = checkpoint_interval
        self._reconstructor = PatchReconstructionEngine(apply_operation)
        self._nodes: dict[str, PatchHistoryNode] = {}
        self._root_node_id: str | None = None
        self._active_node_id: str | None = None
        self.reset(initial_patch)

    @property
    def active_node_id(self) -> str:
        if self._active_node_id is None:
            raise ValueError("Patch history has no active node.")
        return self._active_node_id

    @property
    def root_node_id(self) -> str:
        if self._root_node_id is None:
            raise ValueError("Patch history has no root node.")
        return self._root_node_id

    def nodes_by_step(self) -> list[PatchHistoryNode]:
        return sorted(self._nodes.values(), key=lambda node: node.step_index)

    def node(self, node_id: str) -> PatchHistoryNode:
        node = self._nodes.get(node_id)
        if node is None:
            raise ValueError(f"Unknown patch history node id: {node_id}")
        return node

    def reset(self, initial_patch: np.ndarray) -> None:
        initial_state = np.asarray(initial_patch).copy()
        root_node_id = self._new_node_id()
        root = PatchHistoryNode(
            node_id=root_node_id,
            parent_id=None,
            child_ids=[],
            step_index=0,
            timestamp=datetime.now(timezone.utc),
            operation_type="initial",
            operation_label="Initial Patch",
            operation_parameters={},
            parameter_summary="Initial selected patch state",
            is_checkpoint=True,
            checkpoint_patch=initial_state,
        )
        self._nodes = {root_node_id: root}
        self._root_node_id = root_node_id
        self._active_node_id = root_node_id

    def record_operation(
        self,
        operation_type: str,
        operation_label: str,
        operation_parameters: dict[str, int | float | bool | str],
        resulting_patch: np.ndarray,
        *,
        parameter_summary: str = "",
        is_expensive: bool = False,
    ) -> PatchHistoryNode:
        active_id = self.active_node_id
        active_node = self.node(active_id)
        if active_node.child_ids:
            for stale_child_id in list(active_node.child_ids):
                self._delete_subtree(stale_child_id)
            active_node.child_ids.clear()

        step_index = active_node.step_index + 1
        is_checkpoint = is_expensive or (step_index % self._checkpoint_interval == 0)
        checkpoint_patch = (
            np.asarray(resulting_patch).copy()
            if is_checkpoint
            else None
        )
        node = PatchHistoryNode(
            node_id=self._new_node_id(),
            parent_id=active_id,
            child_ids=[],
            step_index=step_index,
            timestamp=datetime.now(timezone.utc),
            operation_type=operation_type,
            operation_label=operation_label,
            operation_parameters=dict(operation_parameters),
            parameter_summary=parameter_summary,
            is_checkpoint=is_checkpoint,
            checkpoint_patch=checkpoint_patch,
        )
        self._nodes[node.node_id] = node
        active_node.child_ids.append(node.node_id)
        self._active_node_id = node.node_id
        return node

    def restore(self, node_id: str) -> np.ndarray:
        restored = self._reconstructor.reconstruct(self._nodes, node_id)
        self._active_node_id = node_id
        return restored

    def reconstruct(self, node_id: str) -> np.ndarray:
        return self._reconstructor.reconstruct(self._nodes, node_id)

    def _delete_subtree(self, node_id: str) -> None:
        node = self._nodes.get(node_id)
        if node is None:
            return
        for child_id in list(node.child_ids):
            self._delete_subtree(child_id)
        del self._nodes[node_id]

    def _new_node_id(self) -> str:
        return uuid4().hex
