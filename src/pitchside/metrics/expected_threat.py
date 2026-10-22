"""Expected threat (xT): how much each completed pass raised the chance of a goal.

The value of a zone is the probability that possession from there ends in a goal
(the football counterpart of basketball's expected possession value). A completed
pass is worth xT(end) - xT(start). The grid is fitted on simulated seeds 0-99 by
scripts/fit_xt.py and evaluated on seeds 200-399 in docs/data/CALIBRATION.md.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from pitchside.events.match import Match
from pitchside.events.schema import PITCH_LENGTH_M, PITCH_WIDTH_M, MatchMetadata, Pass
from pitchside.metrics._timeline import XY, Subject, attack_frame, by_subject, match_minute, view
from pitchside.metrics._xt_grid import XT
from pitchside.metrics.contract import Fact, Table, ToolParams, ToolResult, fact, minute_fact

TOOL_NAME = "threat_profile"
DESCRIPTION = (
    "Expected threat (xT) added by one team's or one player's completed passes so far: "
    "how much each pass raised the chance that the possession ends in a goal, the "
    "total, and the three most dangerous passes with their minute. Use it to say who "
    "moves the ball into dangerous areas, not just who has it."
)

GRID_X, GRID_Y = 12, 8  # zones along the attacking direction x across the pitch
THRESHOLDS: dict[str, float] = {
    "top_shown": 3,  # most valuable passes listed
}


class Params(ToolParams):
    subject: Annotated[Subject, Field(description="'team' or 'player'.")]
    subject_id: Annotated[str, Field(description="Team id (e.g. 'T06') or player id "
                                                 "(e.g. 'T06-09'), matching `subject`.")]


def zone_of(p: XY) -> int:
    """Zone index x * GRID_Y + y of a point in the attacking frame."""
    x = min(int(p[0] / PITCH_LENGTH_M * GRID_X), GRID_X - 1)
    y = min(int(p[1] / PITCH_WIDTH_M * GRID_Y), GRID_Y - 1)
    return x * GRID_Y + y


def xt_at(p: XY) -> float:
    z = zone_of(p)
    return XT[z // GRID_Y][z % GRID_Y]


def pass_threat(metadata: MatchMetadata, p: Pass) -> float | None:
    """xT(end) - xT(start) for a completed pass; None for any other outcome."""
    if p.outcome != "complete":
        return None
    start = attack_frame(metadata, p.team_id, p.period, p.location)
    end = attack_frame(metadata, p.team_id, p.period, p.end_location)
    return xt_at(end) - xt_at(start)


def run(match: Match, params: Params) -> ToolResult:
    v = view(match, params.as_of_seq)
    credited = by_subject(v, params.subject, params.subject_id)
    valued = [(p, pass_threat(v.metadata, p)) for p in v.events
              if p.type == "pass" and credited(p) and p.outcome == "complete"]
    prefix = f"threat.{params.subject}:{params.subject_id}"
    facts: list[Fact] = [
        fact(f"{prefix}.added", "Expected threat added by completed passes",
             sum(d for _, d in valued if d is not None), "xg"),
        fact(f"{prefix}.passes_valued", "Completed passes valued", len(valued), "count"),
    ]
    top = sorted(valued, key=lambda pd: (-(pd[1] or 0.0), pd[0].seq))
    rows = []
    for k, (p, delta) in enumerate(top[:int(THRESHOLDS["top_shown"])], start=1):
        minute, added = match_minute(p.period, p.clock_s)
        facts += [
            fact(f"{prefix}.top{k}.delta", "Threat added by a top pass", delta or 0.0, "xg"),
            minute_fact(f"{prefix}.top{k}.minute", "Minute of that pass", minute, added),
        ]
        rows.append((k, p.seq, f"{minute}+{added}" if added else minute, p.player_id,
                     p.recipient_id, round(delta or 0.0, 3)))
    return ToolResult(
        tool_name=TOOL_NAME,
        params=params.model_dump(),
        as_of_seq=v.as_of_seq,
        facts=tuple(facts),
        table=Table(columns=("rank", "seq", "minute", "passer", "recipient", "xt_added"),
                    rows=tuple(rows)) if rows else None,
        sample_size=len(valued),
        method=(
            "Each zone of the pitch has an expected threat: the chance that possession from "
            "there ends in a goal, fitted on simulated matches. A completed pass adds the "
            "threat of where it ends minus the threat of where it started."
        ),
        caveats=("Fitted on simulated matches, so it reflects that league's style; failed "
                 "passes and carries are not credited.",),
        cannot_tell=("Off-ball movement that made the pass possible.",),
    )
