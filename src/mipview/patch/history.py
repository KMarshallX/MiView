"""Patch-specific compatibility names for the shared processing history."""

import numpy as np

from mipview.tools.history import (
    ApplyHistoryOperation as PatchApplyOperation,
    HistoryParameter,
    ProcessingHistoryManager,
    ProcessingHistoryNode,
    ProcessingReconstructionEngine,
)


class PatchHistoryManager(ProcessingHistoryManager):
    """Processing history configured for small patch volumes."""

    def __init__(
        self,
        initial_patch: np.ndarray,
        apply_operation: PatchApplyOperation,
        checkpoint_interval: int = 5,
    ) -> None:
        super().__init__(
            initial_patch,
            apply_operation,
            checkpoint_interval,
            initial_label="Initial Patch",
            initial_summary="Initial selected patch state",
            copy_initial_state=True,
        )

    def record_operation(
        self,
        operation_type: str,
        operation_label: str,
        operation_parameters: dict[str, HistoryParameter],
        resulting_patch: np.ndarray,
        *,
        parameter_summary: str = "",
        is_expensive: bool = False,
    ) -> ProcessingHistoryNode:
        return super().record_operation(
            operation_type,
            operation_label,
            operation_parameters,
            resulting_patch,
            parameter_summary=parameter_summary,
            is_expensive=is_expensive,
        )


PatchHistoryNode = ProcessingHistoryNode
PatchReconstructionEngine = ProcessingReconstructionEngine

__all__ = [
    "PatchApplyOperation",
    "PatchHistoryManager",
    "PatchHistoryNode",
    "PatchReconstructionEngine",
]
