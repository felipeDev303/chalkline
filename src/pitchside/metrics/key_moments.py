"""Key moments: the ranked list of what mattered so far, each with its evidence."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from typing import Annotated, Literal

from pydantic import Field

from pitchside.events.match import Match
from pitchside.events.schema import MatchEvent
from pitchside.metrics._timeline import MatchView, match_minute, possessions, view
from pitchside.metrics.contract import Fact, Table, ToolParams, ToolResult, fact, minute_fact
from pitchside.metrics.control_vs_chaos import window_bounds, window_stats
from pitchside.metrics.pass_profile import hardest_completed, pass_difficulty, pass_distance_m
from pitchside.metrics.pressure_shift import detect_shifts, shift_facts
from pitchside.metrics.shot_profile import chance_quality

TOOL_NAME = "key_moments"
DESCRIPTION = (
    "Ranked list of the most important moments so far (goals, big chances, swings "
    "between control and chaos, pressure shifts, long passing sequences, the hardest "
    "completed pass, milestones such as a player's 50th pass). Each moment has its "
    "minute, an importance score and the evidence ids behind it. Use it for recaps, "
    "highlights or to decide what to talk about."
)

THRESHOLDS: dict[str, float] = {
    # Non-goal shots with chance quality at least this: about 2.5 per team per
    # simulated match (seeds 0-99), close to typical "big chance" counts.
    "big_chance_quality": 90,
    "sequence_passes": 10,  # possessions with at least this many passes
    "milestone_passes": 50,  # a player's n-th pass
}
# Importance scores, documented in docs/METHODS.md.
IMPORTANCE = {
    "goal": 100.0,
    "swing": 50.0,
    "pressure_shift": 40.0,
    "hardest_pass": 35.0,
    "milestone": 20.0,
    "sequence_cap": 90.0,  # a long sequence never outranks a goal
}


class Params(ToolParams):
    limit: Annotated[Literal[5, 10, 20], Field(description="How many moments to return.")]


@dataclass(frozen=True)
class Moment:
    kind: str
    seq: int
    importance: float
    team_id: str | None
    player_id: str | None
    facts: tuple[Fact, ...]

    @property
    def moment_id(self) -> str:
        return f"moment:{self.kind}@{self.seq}"

    @property
    def minute(self) -> Fact:
        return self.facts[0]


def _minute(mid: str, e: MatchEvent) -> Fact:
    minute, added = match_minute(e.period, e.clock_s)
    return minute_fact(f"{mid}.minute", "Minute", minute, added)


def _moment(kind: str, e: MatchEvent, importance: float, extra: list[Fact] | None = None,
            *, team_id: str | None = None, player_id: str | None = None) -> Moment:
    mid = f"moment:{kind}@{e.seq}"
    return Moment(kind, e.seq, importance, team_id, player_id,
                  (_minute(mid, e), *(extra or [])))


def all_moments(v: MatchView) -> list[Moment]:
    """Every candidate moment up to the view, unranked."""
    meta = v.metadata
    home, away = meta.home.team_id, meta.away.team_id
    out: list[Moment] = []

    goals = {home: 0, away: 0}
    for e in v.events:
        if e.type != "shot":
            continue
        mid = f"moment:{{}}@{e.seq}"
        quality = chance_quality(meta, e)
        if e.outcome == "goal":
            goals[e.team_id] += 1
            out.append(_moment("goal", e, IMPORTANCE["goal"], [
                fact(f"{mid.format('goal')}.scoreline", "Scoreline after the goal",
                     f"{goals[home]}-{goals[away]}", "scoreline"),
                fact(f"{mid.format('goal')}.chance_quality", "Chance quality", quality, "score"),
            ], team_id=e.team_id, player_id=e.player_id))
        elif quality >= THRESHOLDS["big_chance_quality"]:
            out.append(_moment("big_chance", e, 40 + 0.4 * quality, [
                fact(f"{mid.format('big_chance')}.chance_quality", "Chance quality", quality,
                     "score"),
                fact(f"{mid.format('big_chance')}.outcome", "Outcome",
                     e.outcome.replace("_", " "), "label"),
            ], team_id=e.team_id, player_id=e.player_id))

    eligible = [s for s in window_stats(v) if s.eligible and s.window.events]
    for prev, cur in pairwise(eligible):
        if {prev.state, cur.state} == {"control", "chaos"}:
            first = cur.window.events[0]
            mid = f"moment:swing@{first.seq}"
            (minute, added), _ = window_bounds(cur.window)
            out.append(Moment("swing", first.seq, IMPORTANCE["swing"], None, None, (
                minute_fact(f"{mid}.minute", "Window start", minute, added),
                fact(f"{mid}.from_state", "State before", prev.state, "label"),
                fact(f"{mid}.to_state", "State after", cur.state, "label"),
            )))

    for team_id in (home, away):
        for shift in detect_shifts(v, team_id):
            if not shift.window.events:
                continue
            first = shift.window.events[0]
            mid = f"moment:pressure_shift@{first.seq}.team:{team_id}"
            facts = shift_facts(shift, mid)
            out.append(Moment("pressure_shift", first.seq, IMPORTANCE["pressure_shift"],
                              team_id, None, tuple(facts)))

    for p in possessions(v.events):
        n = p.passes
        if n >= THRESHOLDS["sequence_passes"]:
            start = next(e for e in v.events if e.seq == p.first_seq)
            importance = min(30.0 + 2.0 * (n - THRESHOLDS["sequence_passes"]),
                             IMPORTANCE["sequence_cap"])
            out.append(_moment("sequence", start, importance,
                               [fact(f"moment:sequence@{start.seq}.passes",
                                     "Passes in the sequence", n, "count")],
                               team_id=p.team_id))

    passes = [e for e in v.events if e.type == "pass"]
    hardest = hardest_completed(meta, passes, 1)
    if hardest:
        p = hardest[0]
        out.append(_moment("hardest_pass", p, IMPORTANCE["hardest_pass"], [
            fact(f"moment:hardest_pass@{p.seq}.difficulty", "Pass difficulty",
                 pass_difficulty(meta, p), "score"),
            fact(f"moment:hardest_pass@{p.seq}.distance_m", "Pass length",
                 pass_distance_m(p), "m"),
        ], team_id=p.team_id, player_id=p.player_id))

    counts: dict[str, int] = {}
    for p in passes:
        if p.player_id is None:
            continue
        counts[p.player_id] = counts.get(p.player_id, 0) + 1
        if counts[p.player_id] == THRESHOLDS["milestone_passes"]:
            out.append(_moment("milestone", p, IMPORTANCE["milestone"], [
                fact(f"moment:milestone@{p.seq}.passes", "Pass number",
                     THRESHOLDS["milestone_passes"], "count"),
            ], team_id=p.team_id, player_id=p.player_id))
    return out


def ranked(moments: list[Moment]) -> list[Moment]:
    return sorted(moments, key=lambda m: (-m.importance, m.seq, m.moment_id))


def moment_ids(m: Moment) -> str:
    return " ".join(f.evidence_id for f in m.facts)


def run(match: Match, params: Params) -> ToolResult:
    v = view(match, params.as_of_seq)
    candidates = all_moments(v)
    top = ranked(candidates)[:params.limit]
    rows = tuple(
        (rank, m.minute.display, m.kind, round(m.importance, 1), m.team_id, m.player_id,
         moment_ids(m))
        for rank, m in enumerate(top, start=1)
    )
    return ToolResult(
        tool_name=TOOL_NAME,
        params=params.model_dump(),
        as_of_seq=v.as_of_seq,
        facts=tuple(f for m in top for f in m.facts),
        table=Table(columns=("rank", "minute", "kind", "importance", "team", "player",
                             "evidence_ids"), rows=rows) if rows else None,
        sample_size=len(candidates),
        method=(
            "Candidate moments are scored with fixed weights (goal 100, big chance 40 + 0.4 "
            "x quality, control/chaos swing 50, pressure shift 40, hardest pass 35, long "
            "sequence 30 + 2 per pass beyond 10 up to 90, milestone 20) and ranked by score, "
            "then time."
        ),
        caveats=("Importance is a fixed editorial weighting, not a measure of match impact.",
                 "Pressure shifts catch clear increases in pressing but miss most drops; "
                 "swings use percentile-based thresholds (docs/data/CALIBRATION.md)."),
        cannot_tell=() if candidates else ("No notable moment yet.",),
    )
