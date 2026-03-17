from __future__ import annotations

from mipview.state.contrast_state import ContrastState


def test_contrast_state_window_clamps_to_available_range() -> None:
    state = ContrastState()
    state.set_available_range(-10.0, 20.0)

    recorded: list[tuple[float, float]] = []
    state.window_changed.connect(lambda low, high: recorded.append((low, high)))

    state.set_window(-100.0, 100.0)

    assert state.window() == (-10.0, 20.0)
    assert recorded == [(-10.0, 20.0)]


def test_contrast_state_clear_disables_state() -> None:
    state = ContrastState()
    availability: list[bool] = []
    state.availability_changed.connect(availability.append)

    state.set_available_range(0.0, 100.0)
    state.clear()

    assert state.is_enabled() is False
    assert availability == [True, False]
