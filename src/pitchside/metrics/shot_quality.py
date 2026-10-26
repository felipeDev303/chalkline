"""Shot quality: one shot's expected goals, why it is that high or low, and team totals."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from pitchside.events.match import Match
from pitchside.metrics._timeline import match_minute, view
from pitchside.metrics.contract import Fact, Table, ToolParams, ToolResult, fact, minute_fact
from pitchside.metrics.models import XG_EFFECT_LABELS, odds_one_in, xg, xg_effects

TOOL_NAME = "shot_quality"
DESCRIPTION = (
    "Explains one shot: its expected goals (xG, the chance a shot like it is scored), "
    "how often such a shot goes in (once every N shots), and how much the distance, the "
    "angle of the goal mouth, a header and pressure raised or lowered it compared with "
    "an average shot. Also each team's goals against its total xG so far. Use it to say "
    "why a chance was good or poor, or whether a scoreline flatters a team."
)

THRESHOLDS: dict[str, float] = {
    "min_effect": 0.1,  # effects smaller than this (log-odds) are left out as negligible
}


class Params(ToolParams):
    scope: Annotated[Literal["latest", "best"], Field(description=(
        "'latest': the most recent shot; 'best': the shot with the highest xG so far."))]


def run(match: Match, params: Params) -> ToolResult:
    v = view(match, params.as_of_seq)
    meta = v.metadata
    shots = [e for e in v.events if e.type == "shot"]
    xgs = {s.seq: xg(meta, s) for s in shots}
    facts: list[Fact] = []
    for team in v.teams:
        mine = [s for s in shots if s.team_id == team.team_id]
        facts += [
            fact(f"xg.team:{team.team_id}.goals", f"{team.name} goals",
                 sum(s.outcome == "goal" for s in mine), "count"),
            fact(f"xg.team:{team.team_id}.xg", f"{team.name} expected goals",
                 sum(xgs[s.seq] for s in mine), "xg"),
        ]
    rows: tuple = ()
    cannot_tell: list[str] = []
    if shots:
        shot = shots[-1] if params.scope == "latest" else max(
            shots, key=lambda s: (xgs[s.seq], -s.seq))
        p = xgs[shot.seq]
        prefix = f"xg.shot@{shot.seq}"
        minute, added = match_minute(shot.period, shot.clock_s)
        names = {pl.player_id: pl.name for t in (meta.home, meta.away) for pl in t.players}
        facts += [
            minute_fact(f"{prefix}.minute", "Minute of the shot", minute, added),
            fact(f"{prefix}.shooter", "Shooter", names[shot.player_id or ""], "label"),
            fact(f"{prefix}.xg", "Expected goals of the shot", p, "xg"),
            fact(f"{prefix}.odds_one_in", "Scored about once every this many such shots",
                 odds_one_in(p), "count"),
            fact(f"{prefix}.outcome", "Outcome", shot.outcome.replace("_", " "), "label"),
        ]
        effects = xg_effects(meta, shot)
        shown = [(f, e) for f, e in effects.items() if abs(e) >= THRESHOLDS["min_effect"]]
        for feature, effect in sorted(shown, key=lambda fe: -abs(fe[1])):
            facts.append(fact(
                f"{prefix}.effect.{feature}",
                f"Effect of the {XG_EFFECT_LABELS[feature]} on the scoring odds, against an "
                "average shot (log-odds; negative lowers the chance)", effect, "decimal"))
        rows = tuple((f, round(e, 2)) for f, e in effects.items())
    else:
        cannot_tell.append("No shot yet.")
    return ToolResult(
        tool_name=TOOL_NAME,
        params=params.model_dump(),
        as_of_seq=v.as_of_seq,
        facts=tuple(facts),
        table=Table(columns=("feature", "effect_log_odds"), rows=rows) if rows else None,
        sample_size=len(shots),
        method=(
            "Logistic regression of goals on distance to goal, angle of the goal mouth, "
            "headers and pressure, fitted on simulated matches. Each effect is the "
            "feature's coefficient times how far this shot is from the average shot; with "
            "the average shot's log-odds they add up to this shot's."
        ),
        caveats=("Defenders and the goalkeeper's position are not in the model.",
                 "Checked against the simulator's true scoring probabilities on held-out "
                 "matches (docs/data/CALIBRATION.md)."),
        cannot_tell=tuple(cannot_tell),
    )
