from __future__ import annotations

from mipview.state.zoom_state import ZoomState


def test_zoom_state_clamps_and_emits() -> None:
    state = ZoomState()
    recorded: list[float] = []
    state.zoom_changed.connect(recorded.append)

    state.set_zoom_factor(3.0)
    state.set_zoom_factor(20.0)

    assert state.zoom_factor() == 8.0
    assert recorded == [3.0, 8.0]


def test_zoom_state_ignores_duplicate_updates() -> None:
    state = ZoomState()
    recorded: list[float] = []
    state.zoom_changed.connect(recorded.append)

    state.set_zoom_factor(1.0)

    assert recorded == []
