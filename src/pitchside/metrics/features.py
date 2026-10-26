"""Model inputs from events alone: what the fitted xG and xPass models see.

Shared by the tools (metrics/models.py) and the fit (scripts/fit_models.py), so a
model is always applied to exactly the features it was fitted on.
"""

from __future__ import annotations

import math

from pitchside.events.schema import PITCH_LENGTH_M, PITCH_WIDTH_M, MatchMetadata, Pass, Shot
from pitchside.metrics._timeline import attack_frame, in_box, in_final_third

GOAL_HALF_WIDTH_M = 3.66
GOAL_CENTRE = (PITCH_LENGTH_M, PITCH_WIDTH_M / 2)

XG_FEATURES = ("distance_m", "angle_rad", "header", "under_pressure")
XPASS_FEATURES = ("distance_m", "forward_m", "high", "low", "under_pressure",
                  "into_final_third", "into_box")


def goal_mouth_angle(x: float, y: float) -> float:
    """Angle (radians) between the two posts seen from (x, y), attacking towards x=105."""
    ax, ay = PITCH_LENGTH_M - x, PITCH_WIDTH_M / 2 - GOAL_HALF_WIDTH_M - y
    bx, by = PITCH_LENGTH_M - x, PITCH_WIDTH_M / 2 + GOAL_HALF_WIDTH_M - y
    return abs(math.atan2(ax * by - ay * bx, ax * bx + ay * by))


def xg_features(metadata: MatchMetadata, shot: Shot) -> tuple[float, ...]:
    x, y = attack_frame(metadata, shot.team_id, shot.period, shot.location)
    return (math.dist((x, y), GOAL_CENTRE), goal_mouth_angle(x, y),
            float(shot.body_part == "head"), float(shot.under_pressure))


def xpass_features(metadata: MatchMetadata, p: Pass) -> tuple[float, ...]:
    start = attack_frame(metadata, p.team_id, p.period, p.location)
    end = attack_frame(metadata, p.team_id, p.period, p.end_location)
    return (math.dist(start, end), end[0] - start[0], float(p.height == "high"),
            float(p.height == "low"), float(p.under_pressure), float(in_final_third(end)),
            float(in_box(end)))
