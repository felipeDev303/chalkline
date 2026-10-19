"""Shot profile of a team or a player: volume, accuracy, shot speed, chance quality."""

from __future__ import annotations

import math
from statistics import fmean
from typing import Annotated

from pydantic import Field

from pitchside.events.match import Match
from pitchside.events.schema import PITCH_LENGTH_M, PITCH_WIDTH_M, MatchMetadata, Shot
from pitchside.metrics._timeline import Subject, attack_frame, by_subject, match_minute, view
from pitchside.metrics.contract import Fact, Table, ToolParams, ToolResult, fact, minute_fact

TOOL_NAME = "shot_profile"
DESCRIPTION = (
    "Shooting of one team or one player so far: shots, on target, goals, mean and "
    "fastest shot speed (km/h) and chance quality (0-100, how much of the goal mouth "
    "the shooter could see), including the best chance and its minute. Use it to say "
    "whether a team creates good chances or shoots from poor positions."
)

THRESHOLDS: dict[str, float] = {
    "min_shots": 3,  # means need this many shots
}
GOAL_HALF_WIDTH_M = 3.66
PENALTY_SPOT_DISTANCE_M = 11.0
HEADER_FACTOR = 0.7
# Visible angle of the goal mouth from the penalty spot: the reference for 100.
REFERENCE_ANGLE = 2 * math.atan(GOAL_HALF_WIDTH_M / PENALTY_SPOT_DISTANCE_M)


class Params(ToolParams):
    subject: Annotated[Subject, Field(description="'team' or 'player'.")]
    subject_id: Annotated[str, Field(description="Team id (e.g. 'T06') or player id "
                                                 "(e.g. 'T06-09'), matching `subject`.")]


def goal_mouth_angle(x: float, y: float) -> float:
    """Angle (radians) between the two posts seen from (x, y), attacking towards x=105."""
    ax, ay = PITCH_LENGTH_M - x, PITCH_WIDTH_M / 2 - GOAL_HALF_WIDTH_M - y
    bx, by = PITCH_LENGTH_M - x, PITCH_WIDTH_M / 2 + GOAL_HALF_WIDTH_M - y
    return abs(math.atan2(ax * by - ay * bx, ax * bx + ay * by))


def chance_quality(metadata: MatchMetadata, shot: Shot) -> float:
    """0-100: visible goal angle relative to the penalty spot, capped; headers x0.7."""
    x, y = attack_frame(metadata, shot.team_id, shot.period, shot.location)
    quality = 100 * min(goal_mouth_angle(x, y) / REFERENCE_ANGLE, 1.0)
    return quality * HEADER_FACTOR if shot.body_part == "head" else quality


def run(match: Match, params: Params) -> ToolResult:
    v = view(match, params.as_of_seq)
    credited = by_subject(v, params.subject, params.subject_id)
    shots = [e for e in v.events if e.type == "shot" and credited(e)]
    prefix = f"shot.{params.subject}:{params.subject_id}"
    facts: list[Fact] = [
        fact(f"{prefix}.shots", "Shots", len(shots), "count"),
        fact(f"{prefix}.on_target", "Shots on target",
             sum(1 for s in shots if s.outcome in ("goal", "saved")), "count"),
        fact(f"{prefix}.goals", "Goals", sum(1 for s in shots if s.outcome == "goal"), "count"),
    ]
    cannot_tell: list[str] = []
    qualities = [chance_quality(v.metadata, s) for s in shots]
    if shots:
        best = max(range(len(shots)), key=lambda i: (qualities[i], -shots[i].seq))
        minute, added = match_minute(shots[best].period, shots[best].clock_s)
        facts += [
            fact(f"{prefix}.max_speed_kmh", "Fastest shot", max(s.speed_kmh for s in shots),
                 "km/h"),
            fact(f"{prefix}.best_chance.quality", "Best chance quality", qualities[best],
                 "score"),
            minute_fact(f"{prefix}.best_chance.minute", "Minute of the best chance",
                        minute, added),
        ]
    if len(shots) >= THRESHOLDS["min_shots"]:
        facts += [
            fact(f"{prefix}.mean_speed_kmh", "Mean shot speed",
                 fmean(s.speed_kmh for s in shots), "km/h"),
            fact(f"{prefix}.mean_chance_quality", "Mean chance quality", fmean(qualities),
                 "score"),
        ]
    else:
        cannot_tell.append(f"Fewer than {THRESHOLDS['min_shots']:g} shots: no averages.")
    order = sorted(range(len(shots)), key=lambda i: (-qualities[i], shots[i].seq))[:20]
    rows = []
    for i in sorted(order, key=lambda i: shots[i].seq):
        s = shots[i]
        minute, added = match_minute(s.period, s.clock_s)
        rows.append((s.seq, f"{minute}+{added}" if added else minute, s.player_id, s.outcome,
                     s.body_part, s.speed_kmh, round(qualities[i])))
    return ToolResult(
        tool_name=TOOL_NAME,
        params=params.model_dump(),
        as_of_seq=v.as_of_seq,
        facts=tuple(facts),
        table=Table(columns=("seq", "minute", "player", "outcome", "body_part", "speed_kmh",
                             "chance_quality"), rows=tuple(rows)) if rows else None,
        sample_size=len(shots),
        method=(
            "Chance quality is the angle between the posts seen from the shot location, "
            "relative to the angle from the penalty spot (capped at 100), times 0.7 for "
            "headers. On target means goal or saved."
        ),
        caveats=("Chance quality is a geometric index, not a probability, and is not "
                 "calibrated to real conversion rates; it ignores defenders and the "
                 "goalkeeper (no tracking data).",),
        cannot_tell=tuple(cannot_tell),
    )
