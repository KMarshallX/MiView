from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from uuid import uuid4

import numpy as np

HistoryParameter = int | float | bool | str
ApplyHistoryOperation = Callable[
    [np.ndarray, str, dict[str, HistoryParameter]],
    np.ndarray,
]


@dataclass
class ProcessingHistoryNode:
    node_id: str
    parent_id: str | None
    child_ids: list[str]
    step_index: int
    timestamp: datetime
    operation_type: str
    operation_label: str
    operation_parameters: dict[str, HistoryParameter]
    parameter_summary: str
    is_checkpoint: bool
    checkpoint_patch: np.ndarray | None = None

    @property
    def checkpoint_state(self) -> np.ndarray | None:
        """Generic name for the retained reconstruction snapshot."""
        return self.checkpoint_patch

    @checkpoint_state.setter
    def checkpoint_state(self, value: np.ndarray | None) -> None:
        self.checkpoint_patch = value


class ProcessingReconstructionEngine:
    """Deterministically reconstruct an image state from recorded operations."""

    def __init__(self, apply_operation: ApplyHistoryOperation) -> None:
        self._apply_operation = apply_operation

    def reconstruct(
        self,
        nodes: dict[str, ProcessingHistoryNode],
        target_node_id: str,
    ) -> np.ndarray:
        lineage = self._lineage_to_root(nodes, target_node_id)
        checkpoint_index = self._nearest_checkpoint_index(lineage)
        checkpoint_node = lineage[checkpoint_index]
        if checkpoint_node.checkpoint_state is None:
            raise ValueError("Checkpoint node is missing snapshot data.")

        state = np.asarray(checkpoint_node.checkpoint_state).copy()
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
        nodes: dict[str, ProcessingHistoryNode],
        target_node_id: str,
    ) -> list[ProcessingHistoryNode]:
        if target_node_id not in nodes:
            raise ValueError(f"Unknown processing history node id: {target_node_id}")

        lineage: list[ProcessingHistoryNode] = []
        current_id: str | None = target_node_id
        while current_id is not None:
            node = nodes.get(current_id)
            if node is None:
                raise ValueError(f"Missing history node referenced by id: {current_id}")
            lineage.append(node)
            current_id = node.parent_id
        lineage.reverse()
        return lineage

    @staticmethod
    def _nearest_checkpoint_index(
        lineage: list[ProcessingHistoryNode],
    ) -> int:
        for index in range(len(lineage) - 1, -1, -1):
            if lineage[index].is_checkpoint:
                return index
        raise ValueError("Processing history has no checkpoint ancestor.")


class ProcessingHistoryManager:
    """Linear processing history with configurable in-memory checkpoints."""

    def __init__(
        self,
        initial_state: np.ndarray,
        apply_operation: ApplyHistoryOperation,
        checkpoint_interval: int | None = 5,
        *,
        initial_label: str,
        initial_summary: str,
        copy_initial_state: bool = True,
    ) -> None:
        if checkpoint_interval is not None and checkpoint_interval < 1:
            raise ValueError("checkpoint_interval must be >= 1 or None")
        self._checkpoint_interval = checkpoint_interval
        self._initial_label = str(initial_label)
        self._initial_summary = str(initial_summary)
        self._copy_initial_state = bool(copy_initial_state)
        self._reconstructor = ProcessingReconstructionEngine(apply_operation)
        self._nodes: dict[str, ProcessingHistoryNode] = {}
        self._root_node_id: str | None = None
        self._active_node_id: str | None = None
        self.reset(initial_state)

    @property
    def active_node_id(self) -> str:
        if self._active_node_id is None:
            raise ValueError("Processing history has no active node.")
        return self._active_node_id

    @property
    def root_node_id(self) -> str:
        if self._root_node_id is None:
            raise ValueError("Processing history has no root node.")
        return self._root_node_id

    def nodes_by_step(self) -> list[ProcessingHistoryNode]:
        return sorted(self._nodes.values(), key=lambda node: node.step_index)

    def has_operations(self) -> bool:
        return len(self._nodes) > 1

    def node(self, node_id: str) -> ProcessingHistoryNode:
        node = self._nodes.get(node_id)
        if node is None:
            raise ValueError(f"Unknown processing history node id: {node_id}")
        return node

    def reset(self, initial_state: np.ndarray) -> None:
        state = np.asarray(initial_state)
        checkpoint_state = state.copy() if self._copy_initial_state else state
        root_node_id = self._new_node_id()
        root = ProcessingHistoryNode(
            node_id=root_node_id,
            parent_id=None,
            child_ids=[],
            step_index=0,
            timestamp=datetime.now(timezone.utc),
            operation_type="initial",
            operation_label=self._initial_label,
            operation_parameters={},
            parameter_summary=self._initial_summary,
            is_checkpoint=True,
            checkpoint_patch=checkpoint_state,
        )
        self._nodes = {root_node_id: root}
        self._root_node_id = root_node_id
        self._active_node_id = root_node_id

    def record_operation(
        self,
        operation_type: str,
        operation_label: str,
        operation_parameters: dict[str, HistoryParameter],
        resulting_state: np.ndarray,
        *,
        parameter_summary: str = "",
        is_expensive: bool = False,
    ) -> ProcessingHistoryNode:
        active_id = self.active_node_id
        active_node = self.node(active_id)
        if active_node.child_ids:
            for stale_child_id in list(active_node.child_ids):
                self._delete_subtree(stale_child_id)
            active_node.child_ids.clear()

        step_index = active_node.step_index + 1
        is_periodic_checkpoint = (
            self._checkpoint_interval is not None
            and step_index % self._checkpoint_interval == 0
        )
        is_checkpoint = is_expensive or is_periodic_checkpoint
        checkpoint_state = (
            np.asarray(resulting_state).copy()
            if is_checkpoint
            else None
        )
        node = ProcessingHistoryNode(
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
            checkpoint_patch=checkpoint_state,
        )
        self._nodes[node.node_id] = node
        active_node.child_ids.append(node.node_id)
        self._active_node_id = node.node_id
        return node

    def restore(self, node_id: str) -> np.ndarray:
        restored = self._reconstructor.reconstruct(self._nodes, node_id)
        self._active_node_id = node_id
        return restored

    def delete(self, node_id: str) -> np.ndarray:
        """Delete a state and its descendants, then restore its parent."""
        node = self.node(node_id)
        if node.node_id == self.root_node_id or node.parent_id is None:
            raise ValueError("The initial history state cannot be deleted.")

        parent = self.node(node.parent_id)
        parent.child_ids = [
            child_id for child_id in parent.child_ids if child_id != node.node_id
        ]
        self._delete_subtree(node.node_id)
        restored = self._reconstructor.reconstruct(self._nodes, parent.node_id)
        self._active_node_id = parent.node_id
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

    @staticmethod
    def _new_node_id() -> str:
        return uuid4().hex
