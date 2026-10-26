"""Shot profile of a team or a player: volume, accuracy, shot speed, expected goals."""

from __future__ import annotations

from statistics import fmean
from typing import Annotated

from pydantic import Field

from pitchside.events.match import Match
from pitchside.metrics._timeline import Subject, by_subject, match_minute, view
from pitchside.metrics.contract import Fact, Table, ToolParams, ToolResult, fact, minute_fact
from pitchside.metrics.models import xg

TOOL_NAME = "shot_profile"
DESCRIPTION = (
    "Shooting of one team or one player so far: shots, on target, goals, expected goals "
    "(xG: how many goals those chances are worth), mean and fastest shot speed (km/h), "
    "and the best chance with its minute. Use it to say whether a team creates good "
    "chances or shoots from poor positions, or scores more or less than its chances."
)

THRESHOLDS: dict[str, float] = {
    "min_shots": 3,  # means need this many shots
}


class Params(ToolParams):
    subject: Annotated[Subject, Field(description="'team' or 'player'.")]
    subject_id: Annotated[str, Field(description="Team id (e.g. 'T06') or player id "
                                                 "(e.g. 'T06-09'), matching `subject`.")]


def run(match: Match, params: Params) -> ToolResult:
    v = view(match, params.as_of_seq)
    credited = by_subject(v, params.subject, params.subject_id)
    shots = [e for e in v.events if e.type == "shot" and credited(e)]
    prefix = f"shot.{params.subject}:{params.subject_id}"
    xgs = [xg(v.metadata, s) for s in shots]
    facts: list[Fact] = [
        fact(f"{prefix}.shots", "Shots", len(shots), "count"),
        fact(f"{prefix}.on_target", "Shots on target",
             sum(1 for s in shots if s.outcome in ("goal", "saved")), "count"),
        fact(f"{prefix}.goals", "Goals", sum(1 for s in shots if s.outcome == "goal"), "count"),
        fact(f"{prefix}.xg", "Expected goals (sum of the chances' xG)", sum(xgs), "xg"),
    ]
    cannot_tell: list[str] = []
    if shots:
        best = max(range(len(shots)), key=lambda i: (xgs[i], -shots[i].seq))
        minute, added = match_minute(shots[best].period, shots[best].clock_s)
        facts += [
            fact(f"{prefix}.max_speed_kmh", "Fastest shot", max(s.speed_kmh for s in shots),
                 "km/h"),
            fact(f"{prefix}.best_chance.xg", "Expected goals of the best chance", xgs[best],
                 "xg"),
            minute_fact(f"{prefix}.best_chance.minute", "Minute of the best chance",
                        minute, added),
        ]
    if len(shots) >= THRESHOLDS["min_shots"]:
        facts += [
            fact(f"{prefix}.mean_speed_kmh", "Mean shot speed",
                 fmean(s.speed_kmh for s in shots), "km/h"),
            fact(f"{prefix}.xg_per_shot", "Expected goals per shot", fmean(xgs), "xg"),
        ]
    else:
        cannot_tell.append(f"Fewer than {THRESHOLDS['min_shots']:g} shots: no averages.")
    order = sorted(range(len(shots)), key=lambda i: (-xgs[i], shots[i].seq))[:20]
    rows = []
    for i in sorted(order, key=lambda i: shots[i].seq):
        s = shots[i]
        minute, added = match_minute(s.period, s.clock_s)
        rows.append((s.seq, f"{minute}+{added}" if added else minute, s.player_id, s.outcome,
                     s.body_part, s.speed_kmh, round(xgs[i], 2)))
    return ToolResult(
        tool_name=TOOL_NAME,
        params=params.model_dump(),
        as_of_seq=v.as_of_seq,
        facts=tuple(facts),
        table=Table(columns=("seq", "minute", "player", "outcome", "body_part", "speed_kmh",
                             "xg"), rows=tuple(rows)) if rows else None,
        sample_size=len(shots),
        method=(
            "Expected goals (xG) is the probability a shot like this one is scored, from a "
            "logistic regression on distance to goal, the angle of the goal mouth, headers "
            "and pressure, fitted on simulated matches. On target means goal or saved."
        ),
        caveats=("xG ignores where defenders and the goalkeeper stand; it is checked against "
                 "the simulator's true scoring probabilities on held-out matches "
                 "(docs/data/CALIBRATION.md).",),
        cannot_tell=tuple(cannot_tell),
    )
