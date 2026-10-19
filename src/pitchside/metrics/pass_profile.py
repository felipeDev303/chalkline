"""Pass profile of a team or a player: volume, accuracy, length, ball speed, difficulty."""

from __future__ import annotations

import math
from statistics import fmean
from typing import Annotated

from pydantic import Field

from pitchside.events.match import Match
from pitchside.events.schema import MatchMetadata, Pass
from pitchside.metrics._timeline import (
    Subject,
    attack_frame,
    by_subject,
    in_box,
    in_final_third,
    match_minute,
    view,
)
from pitchside.metrics.contract import Fact, Table, ToolParams, ToolResult, fact, minute_fact

TOOL_NAME = "pass_profile"
DESCRIPTION = (
    "Passing of one team or one player so far: number of passes, completion %, mean "
    "pass length (m), mean ball speed (km/h), mean difficulty (0-100) and the three "
    "hardest completed passes with their minute. Use it to judge how ambitious or "
    "accurate someone's passing is."
)

THRESHOLDS: dict[str, float] = {
    "min_passes": 15,  # rates and means need this many passes
    "hardest_shown": 3,  # hardest completed passes listed
}
# Pass difficulty weights (sum 1.0), documented in docs/METHODS.md.
DIFFICULTY_WEIGHTS = {"distance": 0.30, "pressure": 0.20, "height": 0.15, "progress": 0.20,
                      "zone": 0.15}
HEIGHT_SCORE = {"ground": 0.0, "low": 0.5, "high": 1.0}


class Params(ToolParams):
    subject: Annotated[Subject, Field(description="'team' or 'player'.")]
    subject_id: Annotated[str, Field(description="Team id (e.g. 'T06') or player id "
                                                 "(e.g. 'T06-09'), matching `subject`.")]


def pass_distance_m(p: Pass) -> float:
    return math.dist((p.location.x, p.location.y), (p.end_location.x, p.end_location.y))


def pass_speed_kmh(p: Pass) -> float:
    return pass_distance_m(p) / p.duration_s * 3.6


def pass_difficulty(metadata: MatchMetadata, p: Pass) -> float:
    """0-100: longer, pressured, lofted, forward and into danger zones is harder."""
    start = attack_frame(metadata, p.team_id, p.period, p.location)
    end = attack_frame(metadata, p.team_id, p.period, p.end_location)
    zone = 1.0 if in_box(end) else 0.5 if in_final_third(end) else 0.0
    w = DIFFICULTY_WEIGHTS
    score = (
        w["distance"] * min(pass_distance_m(p) / 50, 1.0)
        + w["pressure"] * float(p.under_pressure)
        + w["height"] * HEIGHT_SCORE[p.height]
        + w["progress"] * min(max((end[0] - start[0]) / 30, 0.0), 1.0)
        + w["zone"] * zone
    )
    return 100 * min(max(score, 0.0), 1.0)


def hardest_completed(metadata: MatchMetadata, passes: list[Pass], k: int) -> list[Pass]:
    done = [p for p in passes if p.outcome == "complete"]
    return sorted(done, key=lambda p: (-pass_difficulty(metadata, p), p.seq))[:k]


def run(match: Match, params: Params) -> ToolResult:
    v = view(match, params.as_of_seq)
    credited = by_subject(v, params.subject, params.subject_id)
    passes = [e for e in v.events if e.type == "pass" and credited(e)]
    prefix = f"pass.{params.subject}:{params.subject_id}"
    facts: list[Fact] = [fact(f"{prefix}.count", "Passes", len(passes), "count")]
    cannot_tell: list[str] = []
    if len(passes) >= THRESHOLDS["min_passes"]:
        completed = sum(1 for p in passes if p.outcome == "complete")
        facts += [
            fact(f"{prefix}.completion_pct", "Pass completion", 100 * completed / len(passes),
                 "pct"),
            fact(f"{prefix}.mean_distance_m", "Mean pass length",
                 fmean(pass_distance_m(p) for p in passes), "m"),
            fact(f"{prefix}.mean_speed_kmh", "Mean ball speed",
                 fmean(pass_speed_kmh(p) for p in passes), "km/h"),
            fact(f"{prefix}.mean_difficulty", "Mean pass difficulty",
                 fmean(pass_difficulty(v.metadata, p) for p in passes), "score"),
        ]
    else:
        cannot_tell.append(f"Fewer than {THRESHOLDS['min_passes']:g} passes: no completion, "
                           "length, speed or difficulty averages.")
    rows = []
    for k, p in enumerate(hardest_completed(v.metadata, passes,
                                            int(THRESHOLDS["hardest_shown"])), start=1):
        minute, added = match_minute(p.period, p.clock_s)
        difficulty = pass_difficulty(v.metadata, p)
        facts += [
            fact(f"{prefix}.hardest{k}.difficulty", "Difficulty of a hard completed pass",
                 difficulty, "score"),
            minute_fact(f"{prefix}.hardest{k}.minute", "Minute of that pass", minute, added),
            fact(f"{prefix}.hardest{k}.distance_m", "Length of that pass",
                 pass_distance_m(p), "m"),
        ]
        rows.append((k, p.seq, f"{minute}+{added}" if added else minute, p.player_id,
                     p.recipient_id, round(pass_distance_m(p), 1), round(difficulty)))
    return ToolResult(
        tool_name=TOOL_NAME,
        params=params.model_dump(),
        as_of_seq=v.as_of_seq,
        facts=tuple(facts),
        table=Table(columns=("rank", "seq", "minute", "passer", "recipient", "distance_m",
                             "difficulty"), rows=tuple(rows)) if rows else None,
        sample_size=len(passes),
        method=(
            "Length is the straight line from start to end location; ball speed is length "
            "over flight time. Difficulty (0-100) weighs length, pressure, height, forward "
            "progress and whether the pass ends in the final third or the box."
        ),
        caveats=("Difficulty is a fixed formula, not a learned model, and ignores the "
                 "positions of other players (no tracking data).",),
        cannot_tell=tuple(cannot_tell),
    )
