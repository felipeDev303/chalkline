"""Pitch geometry for the simulator.

Points are `(x, y)` tuples in an *attacking frame*: the team the point belongs to
attacks towards x = 105. Only arithmetic and `math.sqrt` are used (both exactly
specified by IEEE 754), so results are bit-identical on every OS.
"""

from __future__ import annotations

import math

from pitchside.events.schema import PITCH_LENGTH_M, PITCH_WIDTH_M, Point

XY = tuple[float, float]

CENTRE: XY = (PITCH_LENGTH_M / 2, PITCH_WIDTH_M / 2)
GOAL: XY = (PITCH_LENGTH_M, PITCH_WIDTH_M / 2)
MIDDLE_THIRD_X = PITCH_LENGTH_M / 3
FINAL_THIRD_X = PITCH_LENGTH_M * 2 / 3
BOX_DEPTH_M = 16.5
BOX_HALF_WIDTH_M = 20.16
GOAL_AREA_HALF_WIDTH_M = 9.16

# Zones, in increasing danger.
DEFENSIVE, MIDDLE, FINAL_THIRD, BOX = 0, 1, 2, 3


def clamp(x: float, y: float, margin: float = 0.0) -> XY:
    """Keep a point on the pitch, at least `margin` metres inside the lines."""
    return (
        min(max(x, margin), PITCH_LENGTH_M - margin),
        min(max(y, margin), PITCH_WIDTH_M - margin),
    )


def flip(p: XY) -> XY:
    """Rotate 180 degrees about the centre spot: switches between the teams' frames."""
    return (PITCH_LENGTH_M - p[0], PITCH_WIDTH_M - p[1])


def distance(a: XY, b: XY) -> float:
    dx = a[0] - b[0]
    dy = a[1] - b[1]
    return math.sqrt(dx * dx + dy * dy)


def in_box(p: XY) -> bool:
    return p[0] >= PITCH_LENGTH_M - BOX_DEPTH_M and abs(p[1] - GOAL[1]) <= BOX_HALF_WIDTH_M


def zone(p: XY) -> int:
    if in_box(p):
        return BOX
    if p[0] >= FINAL_THIRD_X:
        return FINAL_THIRD
    if p[0] >= MIDDLE_THIRD_X:
        return MIDDLE
    return DEFENSIVE


def to_point(p: XY) -> Point:
    x, y = clamp(*p)
    return Point(x=round(x, 2), y=round(y, 2))
