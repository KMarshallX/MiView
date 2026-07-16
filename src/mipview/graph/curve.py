from __future__ import annotations

import math

from mipview.graph.geometry import point_to_segment_distance

Point2D = tuple[float, float]


def quadratic_bezier_point(
    start: Point2D,
    control: Point2D,
    end: Point2D,
    t: float,
) -> Point2D:
    """Evaluate a quadratic Bezier curve at ``t`` in the inclusive range [0, 1]."""
    parameter = min(max(float(t), 0.0), 1.0)
    inverse = 1.0 - parameter
    return (
        (inverse * inverse * start[0])
        + (2.0 * inverse * parameter * control[0])
        + (parameter * parameter * end[0]),
        (inverse * inverse * start[1])
        + (2.0 * inverse * parameter * control[1])
        + (parameter * parameter * end[1]),
    )


def adaptive_bezier_sample_count(
    start: Point2D,
    control: Point2D,
    end: Point2D,
    *,
    maximum_segment_length: float = 6.0,
    minimum_segments: int = 8,
    maximum_segments: int = 256,
) -> int:
    """Choose a bounded sample count from the control-polygon length."""
    if maximum_segment_length <= 0.0:
        raise ValueError("Maximum Bezier segment length must be positive.")
    control_length = math.dist(start, control) + math.dist(control, end)
    requested = int(math.ceil(control_length / maximum_segment_length))
    return min(max(requested, int(minimum_segments)), int(maximum_segments))


def sample_quadratic_bezier(
    start: Point2D,
    control: Point2D,
    end: Point2D,
    *,
    segments: int | None = None,
) -> list[Point2D]:
    """Sample a quadratic Bezier curve, including both endpoints."""
    segment_count = (
        adaptive_bezier_sample_count(start, control, end)
        if segments is None
        else int(segments)
    )
    if segment_count <= 0:
        raise ValueError("Bezier sample segment count must be positive.")
    return [
        quadratic_bezier_point(start, control, end, index / segment_count)
        for index in range(segment_count + 1)
    ]


def point_to_quadratic_bezier_distance(
    point: Point2D,
    start: Point2D,
    control: Point2D,
    end: Point2D,
    *,
    segments: int | None = None,
) -> float:
    """Approximate point-to-curve distance using short sampled segments."""
    samples = sample_quadratic_bezier(
        start,
        control,
        end,
        segments=segments,
    )
    return min(
        point_to_segment_distance(point, first, second)
        for first, second in zip(samples[:-1], samples[1:], strict=True)
    )


def nearest_quadratic_bezier_parameter(
    point: Point2D,
    start: Point2D,
    control: Point2D,
    end: Point2D,
    *,
    coarse_segments: int = 64,
    refinement_steps: int = 24,
) -> float:
    """Return the curve parameter nearest to a point using bounded refinement."""
    if coarse_segments <= 0 or refinement_steps < 0:
        raise ValueError("Bezier parameter search counts must be non-negative.")
    samples = sample_quadratic_bezier(
        start,
        control,
        end,
        segments=coarse_segments,
    )
    nearest_index = min(
        range(len(samples)),
        key=lambda index: math.dist(point, samples[index]),
    )
    lower = max((nearest_index - 1) / coarse_segments, 0.0)
    upper = min((nearest_index + 1) / coarse_segments, 1.0)
    for _ in range(refinement_steps):
        first = lower + ((upper - lower) / 3.0)
        second = upper - ((upper - lower) / 3.0)
        first_distance = math.dist(
            point,
            quadratic_bezier_point(start, control, end, first),
        )
        second_distance = math.dist(
            point,
            quadratic_bezier_point(start, control, end, second),
        )
        if first_distance <= second_distance:
            upper = second
        else:
            lower = first
    return (lower + upper) / 2.0


def split_quadratic_bezier(
    start: Point2D,
    control: Point2D,
    end: Point2D,
    t: float,
) -> tuple[Point2D, Point2D, Point2D]:
    """Return split point and left/right controls using de Casteljau subdivision."""
    parameter = min(max(float(t), 0.0), 1.0)
    left_control = _interpolate(start, control, parameter)
    right_control = _interpolate(control, end, parameter)
    split_point = _interpolate(left_control, right_control, parameter)
    return split_point, left_control, right_control


def _interpolate(start: Point2D, end: Point2D, t: float) -> Point2D:
    return (
        start[0] + ((end[0] - start[0]) * t),
        start[1] + ((end[1] - start[1]) * t),
    )
