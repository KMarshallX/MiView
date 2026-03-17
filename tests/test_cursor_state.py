from __future__ import annotations

from mipview.state.cursor_state import CursorState


def test_cursor_state_clamps_and_emits_once() -> None:
    state = CursorState()
    state.set_volume_shape((6, 8, 10))

    recorded: list[tuple[int, int, int]] = []
    state.cursor_changed.connect(lambda x, y, z: recorded.append((x, y, z)))

    state.set_cursor_position((20, -3, 4))
    state.set_cursor_position((7, 0, 4))

    assert state.cursor_position() == (5, 0, 4)
    assert recorded == [(5, 0, 4)]


def test_cursor_state_retains_position_when_shape_changes() -> None:
    state = CursorState()
    state.set_cursor_position((3, 4, 5))

    state.set_volume_shape((5, 6, 7))

    assert state.cursor_position() == (3, 4, 5)
