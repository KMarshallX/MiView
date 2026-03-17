from __future__ import annotations

import numpy as np
import pytest

from miview.patch_history import PatchHistoryManager
from miview.tools import apply_tool, get_tool


def _apply_operation(
    patch_state: np.ndarray,
    operation_type: str,
    parameters: dict[str, int | float | bool | str],
) -> np.ndarray:
    return apply_tool(operation_type, patch_state, parameters)


def _record_result(
    manager: PatchHistoryManager,
    current: np.ndarray,
    operation_type: str,
    parameters: dict[str, int | float | bool | str],
) -> tuple[np.ndarray, str]:
    tool = get_tool(operation_type)
    new_state = apply_tool(operation_type, current, parameters)
    node = manager.record_operation(
        operation_type=operation_type,
        operation_label=tool.label,
        operation_parameters=parameters,
        resulting_patch=new_state,
        parameter_summary="",
        is_expensive=False,
    )
    return new_state, node.node_id


def test_sequential_patch_operations_create_linear_history_chain() -> None:
    initial = np.arange(27, dtype=np.float32).reshape(3, 3, 3)
    manager = PatchHistoryManager(initial, apply_operation=_apply_operation)
    current = initial
    current, node_1 = _record_result(manager, current, "normalize", {})
    current, node_2 = _record_result(
        manager,
        current,
        "invert_minus",
        {"reference_value": 1.0},
    )

    nodes = manager.nodes_by_step()
    assert [node.step_index for node in nodes] == [0, 1, 2]
    assert nodes[1].parent_id == manager.root_node_id
    assert nodes[2].parent_id == node_1
    assert manager.node(node_1).child_ids == [node_2]
    assert manager.active_node_id == node_2


def test_restore_changes_active_patch_state() -> None:
    initial = np.arange(8, dtype=np.float32).reshape(2, 2, 2)
    manager = PatchHistoryManager(initial, apply_operation=_apply_operation)
    current = initial
    state_1, node_1 = _record_result(manager, current, "normalize", {})
    current, _ = _record_result(
        manager,
        state_1,
        "invert_minus",
        {"reference_value": 1.0},
    )

    restored = manager.restore(node_1)
    np.testing.assert_allclose(restored, state_1)
    assert manager.active_node_id == node_1


def test_reconstruction_from_checkpoint_matches_direct_result() -> None:
    initial = np.arange(64, dtype=np.float32).reshape(4, 4, 4)
    manager = PatchHistoryManager(
        initial,
        apply_operation=_apply_operation,
        checkpoint_interval=2,
    )
    current = initial
    operation_sequence = [
        ("normalize", {}),
        ("invert_minus", {"reference_value": 1.0}),
        ("standardize", {}),
        ("invert_divide", {"numerator": 5.0}),
    ]

    final_node_id = manager.root_node_id
    for operation_type, params in operation_sequence:
        current, final_node_id = _record_result(manager, current, operation_type, params)

    reconstructed = manager.reconstruct(final_node_id)
    np.testing.assert_allclose(reconstructed, current)


def test_restore_then_new_operation_deletes_old_downstream_path() -> None:
    initial = np.arange(27, dtype=np.float32).reshape(3, 3, 3)
    manager = PatchHistoryManager(initial, apply_operation=_apply_operation)
    current = initial
    state_1, node_1 = _record_result(manager, current, "normalize", {})
    state_2, node_2 = _record_result(
        manager,
        state_1,
        "invert_minus",
        {"reference_value": 1.0},
    )
    _, node_3 = _record_result(
        manager,
        state_2,
        "invert_divide",
        {"numerator": 2.0},
    )

    restored = manager.restore(node_1)
    assert manager.active_node_id == node_1
    _, new_node = _record_result(
        manager,
        restored,
        "standardize",
        {},
    )

    with pytest.raises(ValueError):
        manager.node(node_2)
    with pytest.raises(ValueError):
        manager.node(node_3)
    assert manager.node(node_1).child_ids == [new_node]
    assert manager.active_node_id == new_node


def test_patch_history_actions_do_not_mutate_main_viewer_data() -> None:
    main_viewer_volume = np.arange(125, dtype=np.float32).reshape(5, 5, 5)
    main_snapshot = main_viewer_volume.copy()
    selected_patch = main_viewer_volume[1:4, 1:4, 1:4].copy()
    manager = PatchHistoryManager(selected_patch, apply_operation=_apply_operation)

    patch_state, _ = _record_result(manager, selected_patch, "normalize", {})
    _ = manager.restore(manager.active_node_id)
    _ = _record_result(
        manager,
        patch_state,
        "invert_minus",
        {"reference_value": 1.0},
    )

    np.testing.assert_allclose(main_viewer_volume, main_snapshot)
