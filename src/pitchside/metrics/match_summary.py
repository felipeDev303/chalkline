"""Match summary: the scoreboard plus the basic team totals."""

from __future__ import annotations

from collections.abc import Sequence

from pitchside.events.match import Match
from pitchside.events.schema import MatchEvent
from pitchside.metrics._timeline import formation, match_minute, possession_seconds, view
from pitchside.metrics.contract import Fact, Table, ToolParams, ToolResult, fact, minute_fact

TOOL_NAME = "match_summary"
DESCRIPTION = (
    "The state of the match so far: scoreline (home-away), current minute, and per team "
    "goals, shots, shots on target, passes, pass completion, possession share and "
    "formation. Start here for any recap or when a viewer asks how the game is going."
)

THRESHOLDS: dict[str, float] = {
    "min_passes": 15,  # completion % needs this many passes by the team
    "min_in_play_s": 60.0,  # possession share needs this much in-play time in total
}


class Params(ToolParams):
    pass


def scoreline(events: Sequence[MatchEvent], home_id: str, away_id: str) -> str:
    goals = {home_id: 0, away_id: 0}
    for e in events:
        if e.type == "shot" and e.outcome == "goal":
            goals[e.team_id] += 1
    return f"{goals[home_id]}-{goals[away_id]}"


def run(match: Match, params: Params) -> ToolResult:
    v = view(match, params.as_of_seq)
    home, away = v.teams
    last = v.events[-1]
    minute, added = match_minute(last.period, last.clock_s)
    facts: list[Fact] = [
        fact("summary.scoreline", f"Scoreline ({home.short_name}-{away.short_name})",
             scoreline(v.events, home.team_id, away.team_id), "scoreline"),
        minute_fact("summary.minute", "Current minute", minute, added),
    ]
    cannot_tell: list[str] = []
    seconds = possession_seconds(v)
    in_play = sum(seconds.values())
    rows = []
    for team in v.teams:
        t = team.team_id
        shots = [e for e in v.events if e.type == "shot" and e.team_id == t]
        passes = [e for e in v.events if e.type == "pass" and e.team_id == t]
        goals = sum(1 for e in shots if e.outcome == "goal")
        on_target = sum(1 for e in shots if e.outcome in ("goal", "saved"))
        prefix = f"summary.team:{t}"
        facts += [
            fact(f"{prefix}.goals", "Goals", goals, "count"),
            fact(f"{prefix}.shots", "Shots", len(shots), "count"),
            fact(f"{prefix}.shots_on_target", "Shots on target", on_target, "count"),
            fact(f"{prefix}.passes", "Passes", len(passes), "count"),
            fact(f"{prefix}.formation", "Formation", formation(team), "formation"),
        ]
        completion = None
        if len(passes) >= THRESHOLDS["min_passes"]:
            completion = 100 * sum(1 for e in passes if e.outcome == "complete") / len(passes)
            facts.append(fact(f"{prefix}.completion_pct", "Pass completion", completion, "pct"))
        else:
            cannot_tell.append(f"{team.short_name}: fewer than "
                               f"{THRESHOLDS['min_passes']:g} passes, no completion %.")
        share = None
        if in_play >= THRESHOLDS["min_in_play_s"]:
            share = 100 * seconds[t] / in_play
            facts.append(fact(f"{prefix}.possession_share", "Possession share", share, "share"))
        rows.append((team.short_name, goals, len(shots), on_target, len(passes),
                     None if completion is None else round(completion, 1),
                     None if share is None else round(share)))
    if in_play < THRESHOLDS["min_in_play_s"]:
        cannot_tell.append(f"Less than {THRESHOLDS['min_in_play_s']:g} s of play; "
                           "no possession share.")
    return ToolResult(
        tool_name=TOOL_NAME,
        params=params.model_dump(),
        as_of_seq=v.as_of_seq,
        facts=tuple(facts),
        table=Table(columns=("team", "goals", "shots", "on_target", "passes",
                             "completion_pct", "possession_share"), rows=tuple(rows)),
        sample_size=len(v.events),
        method=(
            "Counts of the events so far. Shots on target are goals plus saved shots. "
            "Possession share is each team's share of in-play time, excluding dead time "
            "before restarts."
        ),
        caveats=("Possession is time-based, not pass-based, so it can differ from "
                 "broadcast figures.",),
        cannot_tell=tuple(cannot_tell),
    )
