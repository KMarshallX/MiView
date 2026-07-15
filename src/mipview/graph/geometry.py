from __future__ import annotations

import math


def point_to_segment_distance(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    """Return the shortest screen-space distance from a point to a line segment."""
    point_x, point_y = point
    start_x, start_y = start
    end_x, end_y = end
    delta_x = end_x - start_x
    delta_y = end_y - start_y
    squared_length = (delta_x * delta_x) + (delta_y * delta_y)
    if squared_length <= 0.0:
        return math.hypot(point_x - start_x, point_y - start_y)
    projection = (
        ((point_x - start_x) * delta_x) + ((point_y - start_y) * delta_y)
    ) / squared_length
    clamped_projection = min(max(projection, 0.0), 1.0)
    closest_x = start_x + (clamped_projection * delta_x)
    closest_y = start_y + (clamped_projection * delta_y)
    return math.hypot(point_x - closest_x, point_y - closest_y)
